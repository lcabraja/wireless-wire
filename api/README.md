# Private management API

Control an installed Pi from a browser or HTTP client on Tailscale. No SSH key
is required for everyday status, display rotation, saved Wi-Fi networks, bridge
restart or Mac client enrollment. Initial installation and recovery still need
local administration or SSH. USB data continues over the existing bridge port
48200; the management API does not change its usbmux transport.

## Install

On the Linux USB host, after the core server is installed:

```sh
python3 scripts/build.py
sudo bash api/install.sh
```

The installer enables the API at boot, updates/restarts the bridge, and sets up
Tailscale Serve. It requires NetworkManager, sudo, Tailscale with HTTPS enabled,
and Python 3.11+. It refuses to replace another application on ports 80/443.
The screen component is optional and installed separately with `display/install.sh`.

- `http://PI_TAILSCALE_IP/` redirects to `https://PI_NAME.TAILNET.ts.net/`.
- HTTPS terminates at Tailscale Serve, which manages the certificate.
- Both ports bind only to Tailscale addresses. The API and redirect backends
  listen only on `127.0.0.1:8080` and `127.0.0.1:8081`.
- Port 80 uses Tailscale's TCP proxy because HTTP Serve routes by DNS Host header
  and would return 404 when addressed by IP. The redirect destination is fixed.
- No Funnel or public listener is enabled. Tailnet ACLs still apply.

The page shows live state, display orientation, Wi-Fi controls and client setup.
Wi-Fi save supports WPA2-Personal, keeps the current connection and does not
activate the new profile. Connect explicitly switches to a saved profile after
a short delay; expect temporary loss of connectivity. Bad Wi-Fi credentials or
a network without internet can require local recovery. Enterprise/WPA3-only and
captive-portal configuration are not implemented.

## Authentication

Tailscale Serve verifies the connecting device and supplies `Tailscale-User-Login`.
The API permits only identities in `/etc/wireless-wire-api/config.json`; the
installer initially allows the Pi's owner and preserves subsequent configuration.
An arbitrary tailnet member or shared-device guest does not gain access. Tagged
clients have no user identity header and are denied. A tagged server needs an
explicit allowed-login configuration before installation.

Do not expose the loopback backend directly. Root/local processes on the Pi
are trusted and could impersonate a proxy identity. Tailscale Serve strips client
identity headers before injecting its own. Browser mutations require a custom
header, JSON and a same-origin request. No cross-origin API access is enabled.
Responses are never cached; credential enrollment is POST-only.

The HTTP process runs as `wireless-wire-api`. A sudo rule permits only the
root-owned `wireless-wire-admin` helper without arguments. Its bounded JSON
interface permits listed actions, never shell commands, arbitrary services or
file paths. Passwords are sent on stdin, not process arguments; Wi-Fi profiles
store derived WPA2 keys in root-only files. No HTTP bodies, credentials, pairing
records or phone identifiers are logged. Client configuration contains the
existing shared bridge token, so allowed management users have full bridge access.

## Endpoints

All endpoints require the allowed Tailscale identity. POST requests need
`Content-Type: application/json` and `X-Wireless-Wire-Request: 1`.

| Method | Path | Body / result |
| --- | --- | --- |
| GET | `/api/v1/status` | USB, network, bridge peers, service state, orientation |
| GET | `/api/v1/wifi` | Saved network names and UUIDs; never passwords |
| POST | `/api/v1/display/rotation` | `{"degrees":0}`; accepts 0, 90, 180, 270 |
| POST | `/api/v1/service/restart` | `{"service":"wireless-wire"}` or `wireless-wire-display` |
| POST | `/api/v1/wifi` | `{"ssid":"Example","password":"..."}`; saves without activating |
| POST | `/api/v1/wifi/connect` | `{"uuid":"saved-network-uuid"}`; schedules activation |
| POST | `/api/v1/client-config` | `{}`; returns private `remote` and `token` |

Example without SSH or an API password, from an allowed Tailscale user device:

```sh
curl https://PI_NAME.TAILNET.ts.net/api/v1/status
curl -X POST https://PI_NAME.TAILNET.ts.net/api/v1/display/rotation \
  -H 'Content-Type: application/json' -H 'X-Wireless-Wire-Request: 1' \
  --data '{"degrees":0}'
```

Enroll a Mac from the current source checkout after `python3 scripts/build.py`:

```sh
python3 scripts/install-client.py --api-url https://PI_NAME.TAILNET.ts.net
python3 dist/wireless-wire.pyz doctor --side mac --require-device
```

The installer retrieves and stores the token privately without printing it.
Existing v1 release archives predate the management API; use current source.

## Maintain

`systemctl status wireless-wire-api` checks the service. To disable network
management, stop/disable that unit and disable only its Serve endpoints with
`tailscale serve --https=443 off` and `tailscale serve --tcp=80 off`. Do not reset
all Serve configuration when other services share the host.

Tests: `python3 -m unittest discover -s tests -v`. The screen and API share
`wireless_wire.host_status`; neither adds dependencies to the core transport.

Protocol/security references:
[Tailscale Serve identity headers](https://tailscale.com/docs/features/tailscale-serve#identity-headers),
[NetworkManager keyfiles](https://networkmanager.dev/docs/api/latest/nm-settings-keyfile.html).
