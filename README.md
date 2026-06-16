# BLE Proxy Client

Client BLE Proxy WebSocket pour `matterjs-server`, développé en Python avec **Bleak** et **WebSockets**.

Ce client permet d'utiliser un adaptateur Bluetooth présent sur une machine distante (Windows, Linux, etc.) comme proxy BLE pour un serveur Matter exécuté ailleurs. Il implémente le protocole **BLE Proxy WebSocket v1** utilisé par `matterjs-server`.

## Fonctionnalités

- Handshake BLE Proxy v1 (`hello` / `hello_response`)
- Scan BLE avec filtrage sur les UUIDs de service
- Détection des appareils Matter (`FFF6`)
- Connexion / déconnexion BLE
- Découverte des services et caractéristiques GATT
- Lecture et écriture de caractéristiques
- Notifications BLE
- Gestion du protocole BTP Matter
- Transmission binaire optimisée pour les échanges Matter
- Compatible Windows (Bleak / WinRT)
- Compatible Linux

## Dépendances

- Python 3.10+
- bleak
- websockets

Installation :

```bash
pip install bleak websockets
```

ou :

```bash
pip install -r requirements.txt
```

## Utilisation

Lancer le client en indiquant l'URL WebSocket du serveur Matter :

```bash
python ble_proxy_client.py ws://IP_DU_SERVEUR:5580/ble
```

Exemple :

```bash
python ble_proxy_client.py ws://192.168.1.139:5580/ble
```

## Fonctionnement

1. Le client se connecte au serveur Matter via WebSocket.
2. Un handshake est effectué pour vérifier la compatibilité du protocole.
3. Le serveur envoie les commandes BLE au client.
4. Le client exécute les opérations via Bleak :
   - scan
   - connexion
   - découverte GATT
   - lecture/écriture
   - notifications
5. Les résultats sont renvoyés au serveur via WebSocket.

## UUID Matter utilisés

Service Matter :

```text
FFF6
```

Caractéristiques principales :

```text
18EE2EF5-263D-4559-959F-4F9C429F9D11
18EE2EF5-263D-4559-959F-4F9C429F9D12
18EE2EF5-263D-4559-959F-4F9C429F9D13
```

## Exemple d'utilisation

Machine A :

```text
Matter Server
192.168.1.139
Port WebSocket : 5580
```

Machine B :

```text
Windows avec Bluetooth
BLE Proxy Client
```

Connexion :

```bash
python ble_proxy_client.py ws://192.168.1.139:5580/ble
```

Le serveur Matter utilisera alors automatiquement l'adaptateur Bluetooth de la machine B pour le commissionnement Matter.

## Logs

Le client affiche les événements importants :

```text
Connexion WebSocket
Handshake
Détection des périphériques
Connexion BLE
Notifications
Déconnexions
Erreurs
```

## Cas d'usage

- Machine virtuelle sans accès Bluetooth
- Serveur distant sans adaptateur BLE
- Commissionnement Matter depuis Windows
- Tests et développement Matter
- Débogage BLE à distance

## Licence

MIT