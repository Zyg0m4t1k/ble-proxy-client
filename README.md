# BLE Proxy Client

Client Bluetooth pour le plugin Matter de Jeedom.

Ce programme permet d'utiliser un adaptateur Bluetooth situe sur une autre machine (ou sur l'hote d'un conteneur Docker) pour ajouter des appareils Matter via Bluetooth (commissioning BLE).

## Quand l'utiliser ?

- Jeedom tourne dans un **conteneur Docker** sans acces direct au Bluetooth
- Jeedom est sur une **machine virtuelle** sans Bluetooth
- Le serveur Jeedom n'a **pas d'adaptateur Bluetooth** et vous voulez utiliser celui d'un autre PC (Windows, Linux...)

Une fois l'appareil ajoute (commissionne), le Bluetooth n'est plus necessaire : le plugin communique ensuite en IP.

## Installation

Prerequis : Python 3.10 ou superieur.

```bash
pip install bleak websockets
```

## Utilisation

Lancer le client en indiquant l'adresse de votre Jeedom :

```bash
python ble_proxy_client.py ws://IP_JEEDOM:5580/ble
```

Exemple :

```bash
python ble_proxy_client.py ws://192.168.1.139:5580/ble
```

### Choisir un adaptateur Bluetooth specifique

Si votre machine possede plusieurs adaptateurs Bluetooth (par exemple un Bluetooth interne et un dongle USB), vous pouvez forcer l'utilisation d'un adaptateur precis avec son adresse MAC :

```bash
python ble_proxy_client.py ws://192.168.1.139:5580/ble --adapter A0:AD:9F:78:93:09
```

Pour connaitre les adaptateurs disponibles :

```bash
bluetoothctl list
```

Sans l'option `--adapter`, le client utilise l'adaptateur par defaut du systeme.

## Configuration cote Jeedom

Dans la configuration du plugin Matter, cochez **BLE Proxy (distant)** puis redemarrez le demon. Le serveur Matter attend alors qu'un client BLE Proxy se connecte pour le commissioning.

## Fonctionnement

1. Le client se connecte au serveur Matter de Jeedom via WebSocket
2. Quand vous lancez un commissioning dans Jeedom, le serveur envoie les commandes Bluetooth au client
3. Le client effectue les operations BLE (scan, connexion, echange de cles) via l'adaptateur local
4. Une fois le commissioning termine, le Bluetooth n'est plus utilise

## Cas d'usage

- **Docker** : Jeedom en conteneur, Bluetooth sur l'hote ou un autre PC
- **Machine virtuelle** : VM sans acces Bluetooth
- **Serveur deporte** : serveur Jeedom sans Bluetooth, dongle BLE sur un PC du reseau
- **Windows** : utiliser le Bluetooth d'un PC Windows pour ajouter des appareils Matter

## Licence

MIT
