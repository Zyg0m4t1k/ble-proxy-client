#!/usr/bin/env python3
"""
Client BLE Proxy pour matterjs-server - test depuis Windows avec Bleak.

Usage:
    python ble_proxy_client.py ws://192.168.1.139:5580/ble

Implémente le protocole BLE Proxy WebSocket v1:
- Handshake (hello / hello_response)
- start_scan / stop_scan (filtré sur le service Matter fff6)
- connect / disconnect
- discover_services / discover_characteristics
- read_characteristic / write_characteristic
- subscribe_characteristic / write_and_subscribe (BTP handshake)
- Frames binaires (BTP write/notification/read_response)
"""

import asyncio
import base64
import json
import logging
import struct
import sys

import websockets
from bleak import BleakScanner, BleakClient
from bleak.backends.scanner import AdvertisementData

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ble-proxy")

PROTOCOL_VERSION = 1

# UUIDs Matter
MATTER_SERVICE_UUID = "0000fff6-0000-1000-8000-00805f9b34fb"
MATTER_SERVICE_SHORT = "fff6"
C1_UUID = "18ee2ef5-263d-4559-959f-4f9c429f9d11"
C2_UUID = "18ee2ef5-263d-4559-959f-4f9c429f9d12"
C3_UUID = "18ee2ef5-263d-4559-959f-4f9c429f9d13"

# Opcodes binaires
OP_WRITE_DATA = 0x01
OP_NOTIFICATION = 0x02
OP_READ_RESPONSE = 0x03


def normalize_uuid(uuid_str: str) -> str:
    """Normalise un UUID vers la forme 128-bit canonique attendue par Bleak."""
    u = uuid_str.lower().replace("-", "")
    if len(u) == 4:  # short form, ex: "fff6"
        return f"0000{u}-0000-1000-8000-00805f9b34fb"
    if len(u) == 32:
        return f"{u[0:8]}-{u[8:12]}-{u[12:16]}-{u[16:20]}-{u[20:32]}"
    return uuid_str.lower()


def short_uuid(uuid_str: str) -> str:
    """Retourne la forme courte (4 chars) si c'est un UUID Bluetooth standard."""
    u = uuid_str.lower().replace("-", "")
    if len(u) == 32 and u.startswith("0000") and u.endswith("00001000800000805f9b34fb"):
        return u[4:8]
    return uuid_str.lower()


class BleProxyClient:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = None
        # connection_handle -> BleakClient
        self.connections: dict[int, BleakClient] = {}
        # connection_handle -> dernière characteristic ciblée par write_characteristic (pour binaire 0x01)
        self.last_write_char: dict[int, str] = {}
        # connection_handle -> dernière characteristic abonnée (pour binaire 0x02)
        self.last_subscribe_char: dict[int, str] = {}
        self.scanning = False
        self.scanner: BleakScanner | None = None
        self.next_handle = 1

    # ------------------------------------------------------------------
    # Connexion WebSocket + handshake
    # ------------------------------------------------------------------
    async def run(self):
        log.info(f"Connexion à {self.ws_url} ...")
        async with websockets.connect(self.ws_url, max_size=None) as ws:
            self.ws = ws
            await self.handshake()
            await self.message_loop()

    async def handshake(self):
        await self.ws.send(json.dumps({"type": "hello", "version": PROTOCOL_VERSION}))
        raw = await self.ws.recv()
        msg = json.loads(raw)
        log.info(f"hello_response: {msg}")
        if msg.get("error"):
            raise RuntimeError(f"Handshake refusé: {msg.get('message')}")

    async def message_loop(self):
        async for raw in self.ws:
            if isinstance(raw, bytes):
                await self.handle_binary(raw)
            else:
                msg = json.loads(raw)
                await self.handle_json(msg)

    # ------------------------------------------------------------------
    # Dispatch JSON
    # ------------------------------------------------------------------
    async def handle_json(self, msg: dict):
        if "command" in msg:
            await self.handle_command(msg)
        else:
            log.info(f"Message reçu (non-commande): {msg}")

    async def handle_command(self, msg: dict):
        cmd_id = msg["id"]
        command = msg["command"]
        args = msg.get("args", {})
        log.info(f"-> commande reçue: {command} args={args}")

        try:
            result = await self.dispatch(command, args)
            await self.send_response(cmd_id, success=True, result=result)
        except CommandError as e:
            await self.send_response(cmd_id, success=False, error=e.code, message=str(e))
        except Exception as e:
            log.exception(f"Erreur sur commande {command}")
            await self.send_response(cmd_id, success=False, error="internal_error", message=str(e))

    async def send_response(self, cmd_id, success, result=None, error=None, message=None):
        resp = {"id": cmd_id, "success": success}
        if success:
            resp["result"] = result or {}
        else:
            resp["error"] = error
            resp["message"] = message
        await self.ws.send(json.dumps(resp))
        log.info(f"<- réponse envoyée: {resp}")

    async def send_event(self, event: str, data: dict):
        await self.ws.send(json.dumps({"event": event, "data": data}))

    # ------------------------------------------------------------------
    # Dispatch des commandes
    # ------------------------------------------------------------------
    async def dispatch(self, command: str, args: dict):
        handler = getattr(self, f"cmd_{command}", None)
        if handler is None:
            raise CommandError("internal_error", f"Commande inconnue: {command}")
        return await handler(args)

    # --- Scan ---------------------------------------------------------
    async def cmd_start_scan(self, args: dict):
        if self.scanning:
            raise CommandError("already_scanning", "Un scan est déjà en cours")

        service_uuids = args.get("service_uuids", [])
        normalized_filters = [normalize_uuid(u) for u in service_uuids] if service_uuids else None

        def detection_callback(device, advertisement_data: AdvertisementData):
            asyncio.create_task(self._on_device_discovered(device, advertisement_data, normalized_filters))

        self.scanner = BleakScanner(detection_callback=detection_callback)
        await self.scanner.start()
        self.scanning = True
        log.info(f"Scan démarré (filtre service_uuids={service_uuids or 'aucun'})")
        return {}

    async def _on_device_discovered(self, device, adv: AdvertisementData, filters):
        service_data = {}
        for uuid, data in (adv.service_data or {}).items():
            key = short_uuid(uuid)
            service_data[key] = base64.b64encode(data).decode()

        # Filtre côté client (optionnel, le serveur peut aussi filtrer)
        if filters:
            adv_uuids_norm = {normalize_uuid(u) for u in (adv.service_uuids or [])}
            sd_uuids_norm = {normalize_uuid(k) for k in service_data.keys()}
            if not (adv_uuids_norm & set(filters) or sd_uuids_norm & set(filters)):
                return

        manufacturer_data = {}
        for mfg_id, data in (adv.manufacturer_data or {}).items():
            manufacturer_data[str(mfg_id)] = base64.b64encode(data).decode()

        data = {
            "address": device.address,
            "connectable": True,  # Bleak/Windows ne distingue pas toujours; on suppose True
            "rssi": adv.rssi,
            "service_uuids": [short_uuid(u) for u in (adv.service_uuids or [])],
        }
        if adv.local_name or device.name:
            data["name"] = adv.local_name or device.name
        if service_data:
            data["service_data"] = service_data
        if manufacturer_data:
            data["manufacturer_data"] = manufacturer_data

        log.info(f"device_discovered: {data}")
        await self.send_event("device_discovered", data)

    async def cmd_stop_scan(self, args: dict):
        if not self.scanning:
            log.info("stop_scan: aucun scan en cours (no-op)")
            return {}
        await self.scanner.stop()
        self.scanning = False
        self.scanner = None
        log.info("Scan arrêté")
        return {}

    # --- Connexion ------------------------------------------------------
    async def cmd_connect(self, args: dict):
        address = args["address"]
        timeout = args.get("timeout", 30_000) / 1000.0

        for h, c in self.connections.items():
            if c.address.lower() == address.lower():
                raise CommandError("already_connected", f"Déjà connecté à {address}")

        handle = self.next_handle
        self.next_handle += 1

        def make_disconnect_cb(h):
            def _cb(c):
                asyncio.create_task(self._on_disconnected(h, "unexpected"))
            return _cb

        # BlueZ refuse une connexion si un scan est en cours (InProgress)
        if self.scanning:
            log.info("Auto-stop du scan avant connexion (BlueZ InProgress workaround)")
            try:
                await self.scanner.stop()
            except Exception:
                pass
            self.scanning = False
            self.scanner = None

        client = BleakClient(
            address,
            timeout=timeout,
            disconnected_callback=make_disconnect_cb(handle),
        )
        try:
            await client.connect()
        except Exception as e:
            raise CommandError("connection_failed", str(e))

        self.connections[handle] = client

        mtu = getattr(client, "mtu_size", 247) or 247
        log.info(f"Connecté à {address} (handle={handle}, mtu={mtu})")
        return {"connection_handle": handle, "mtu": mtu}

    async def _on_disconnected(self, handle: int, reason: str):
        if handle not in self.connections:
            return
        log.info(f"Déconnexion inattendue handle={handle} reason={reason}")
        self.connections.pop(handle, None)
        self.last_write_char.pop(handle, None)
        self.last_subscribe_char.pop(handle, None)
        await self.send_event("disconnected", {"connection_handle": handle, "reason": reason})

    async def cmd_disconnect(self, args: dict):
        handle = args["connection_handle"]
        client = self._get_client(handle)
        await client.disconnect()
        self.connections.pop(handle, None)
        self.last_write_char.pop(handle, None)
        self.last_subscribe_char.pop(handle, None)
        log.info(f"Déconnecté handle={handle}")
        return {}

    def _get_client(self, handle: int) -> BleakClient:
        client = self.connections.get(handle)
        if client is None:
            raise CommandError("not_connected", f"Pas de connexion active pour handle={handle}")
        return client

    # --- Discovery ------------------------------------------------------
    async def cmd_discover_services(self, args: dict):
        handle = args["connection_handle"]
        client = self._get_client(handle)
        services = []
        for service in client.services:
            services.append({"uuid": service.uuid.upper()})
        log.info(f"Services découverts (handle={handle}): {services}")
        return {"services": services}

    async def cmd_discover_characteristics(self, args: dict):
        handle = args["connection_handle"]
        service_uuid = normalize_uuid(args["service_uuid"])
        client = self._get_client(handle)

        service = client.services.get_service(service_uuid)
        if service is None:
            raise CommandError("service_not_found", f"Service {args['service_uuid']} non trouvé")

        characteristics = []
        for char in service.characteristics:
            characteristics.append({
                "uuid": char.uuid.upper(),
                "properties": list(char.properties),
            })
        log.info(f"Caractéristiques découvertes (service={service_uuid}): {characteristics}")
        return {"characteristics": characteristics}

    # --- Read / Write -----------------------------------------------------
    async def cmd_read_characteristic(self, args: dict):
        handle = args["connection_handle"]
        char_uuid = normalize_uuid(args["characteristic_uuid"])
        client = self._get_client(handle)
        try:
            value = await client.read_gatt_char(char_uuid)
        except Exception as e:
            raise CommandError("read_failed", str(e))
        log.info(f"Lecture {char_uuid} -> {len(value)} bytes")
        return {"value": base64.b64encode(value).decode()}

    async def cmd_write_characteristic(self, args: dict):
        handle = args["connection_handle"]
        char_uuid = normalize_uuid(args["characteristic_uuid"])
        value = base64.b64decode(args["value"])
        response = args.get("response", False)
        client = self._get_client(handle)

        try:
            await client.write_gatt_char(char_uuid, value, response=response)
        except Exception as e:
            raise CommandError("write_failed", str(e))

        self.last_write_char[handle] = char_uuid
        log.info(f"Écriture {char_uuid} ({len(value)} bytes, response={response})")
        return {}

    # --- Subscribe ----------------------------------------------------
    async def cmd_subscribe_characteristic(self, args: dict):
        handle = args["connection_handle"]
        char_uuid = normalize_uuid(args["characteristic_uuid"])
        client = self._get_client(handle)

        async def callback(_sender, data: bytearray):
            await self._on_notification(handle, char_uuid, bytes(data))

        try:
            await client.start_notify(char_uuid, callback)
        except Exception as e:
            raise CommandError("subscribe_failed", str(e))

        self.last_subscribe_char[handle] = char_uuid
        log.info(f"Abonnement notifications {char_uuid}")
        return {}

    async def cmd_unsubscribe_characteristic(self, args: dict):
        handle = args["connection_handle"]
        char_uuid = normalize_uuid(args["characteristic_uuid"])
        client = self._get_client(handle)

        try:
            await client.stop_notify(char_uuid)
        except Exception as e:
            raise CommandError("not_subscribed", str(e))

        if self.last_subscribe_char.get(handle) == char_uuid:
            self.last_subscribe_char.pop(handle, None)
        log.info(f"Désabonnement {char_uuid}")
        return {}

    # --- write_and_subscribe (BTP handshake atomique) ------------------
    async def cmd_write_and_subscribe(self, args: dict):
        handle = args["connection_handle"]
        write_uuid = normalize_uuid(args["write_uuid"])
        write_value = base64.b64decode(args["write_value"])
        write_response = args.get("write_response", False)
        subscribe_uuid = normalize_uuid(args["subscribe_uuid"])
        client = self._get_client(handle)

        # 1. Écriture (avec réponse GATT attendue)
        try:
            await client.write_gatt_char(write_uuid, write_value, response=write_response)
        except Exception as e:
            raise CommandError("write_failed", str(e))
        self.last_write_char[handle] = write_uuid
        log.info(f"write_and_subscribe: écriture {write_uuid} OK ({len(write_value)} bytes)")

        # 2. Abonnement immédiat (CCCD enable) sur l'autre caractéristique
        async def callback(_sender, data: bytearray):
            await self._on_notification(handle, subscribe_uuid, bytes(data))

        try:
            await client.start_notify(subscribe_uuid, callback)
        except Exception as e:
            raise CommandError("subscribe_failed", str(e))

        self.last_subscribe_char[handle] = subscribe_uuid
        log.info(f"write_and_subscribe: abonnement {subscribe_uuid} OK")
        return {}

    # --- MTU ------------------------------------------------------------
    async def cmd_request_mtu(self, args: dict):
        handle = args["connection_handle"]
        requested_mtu = args["mtu"]
        client = self._get_client(handle)
        # Bleak/Windows (WinRT) ne permet généralement pas de renégocier le MTU après connexion.
        mtu = getattr(client, "mtu_size", requested_mtu) or requested_mtu
        log.info(f"request_mtu: demandé={requested_mtu}, négocié(constaté)={mtu}")
        return {"mtu": mtu}

    # --- Notifications --------------------------------------------------
    async def _on_notification(self, handle: int, char_uuid: str, data: bytes):
        # Préférence binaire si c'est la caractéristique C2 (notify BTP)
        if char_uuid == C2_UUID or self.last_subscribe_char.get(handle) == char_uuid:
            await self.send_binary(OP_NOTIFICATION, handle, data)
        else:
            await self.send_event("characteristic_notification", {
                "connection_handle": handle,
                "characteristic_uuid": char_uuid.upper(),
                "value": base64.b64encode(data).decode(),
            })
        log.info(f"Notification reçue handle={handle} char={char_uuid} ({len(data)} bytes)")

    # ------------------------------------------------------------------
    # Frames binaires
    # ------------------------------------------------------------------
    async def send_binary(self, opcode: int, handle: int, payload: bytes):
        frame = struct.pack(">BH", opcode, handle) + payload
        await self.ws.send(frame)

    async def handle_binary(self, raw: bytes):
        if len(raw) < 3:
            log.warning(f"Frame binaire trop courte: {len(raw)} bytes")
            return
        opcode, handle = struct.unpack(">BH", raw[:3])
        payload = raw[3:]
        log.info(f"Frame binaire reçue: opcode=0x{opcode:02x} handle={handle} payload={len(payload)} bytes")

        if opcode == OP_WRITE_DATA:
            char_uuid = self.last_write_char.get(handle, C1_UUID)
            client = self.connections.get(handle)
            if client is None:
                log.warning(f"WRITE_DATA pour handle inconnu {handle}")
                return
            try:
                await client.write_gatt_char(char_uuid, payload, response=True)
            except Exception:
                log.exception("Échec écriture binaire (WRITE_DATA)")
        else:
            log.warning(f"Opcode binaire inattendu côté client: 0x{opcode:02x}")


class CommandError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


async def main():
    if len(sys.argv) < 2:
        print("Usage: python ble_proxy_client.py ws://<ip>:5580/ble")
        sys.exit(1)

    url = sys.argv[1]
    client = BleProxyClient(url)
    await client.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Arrêt demandé (Ctrl+C)")
