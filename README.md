# Wireless Wire

Use an iPhone plugged into a Linux board from a remote Mac over Tailscale.
One ordinary USB data cable goes from the board's USB host port to the iPhone.

This forwards **iPhone usbmux services**. It works with `libimobiledevice` tools;
it does not create a generic USB controller or integrate with Finder/Xcode.
Android, storage devices, DFU/recovery restore and USB tethering are outside v1.

## Requirements

- Linux USB host with Python 3.11+, `usbmuxd`, and Tailscale.
- Client Mac with Python 3.11+ and Tailscale. Linux clients can run `bridge` directly.
- An unlocked iPhone that trusts the Linux host.

Release archives contain native launchers and our Python zipapp. Python and the
USB tools are installed separately. Download the matching archive from
[Releases](https://github.com/lcabraja/wireless-wire/releases), verify `SHA256SUMS`,
and keep `wireless-wire` and `wireless-wire.pyz` together.

## Setup

For browser/API control without SSH, install the optional [management API](api/README.md)
on the Pi. It provides private HTTPS, Wi-Fi and display controls, and Mac enrollment
with `python3 scripts/install-client.py --api-url https://PI_NAME.TAILNET.ts.net`.
The USB bridge still uses port 48200. Initial host installation uses the steps below.

From source, build with `python3 scripts/build.py`. Release archives are already built.

On the Linux USB host:

```sh
sudo bash scripts/install-server.sh --listen YOUR_PI_TAILSCALE_IP
```

Privately copy `/etc/wireless-wire/token` to the Mac over SSH. Keep it mode `0600`.
Then install the client:

```sh
python3 scripts/install-client.py --remote YOUR_PI_TAILSCALE_IP:48200 --token-file /private/path/token
```

For a foreground client on either OS:

```sh
python3 wireless-wire.pyz bridge --remote YOUR_PI_TAILSCALE_IP:48200 --token-file /private/path/token
```

Plug in the iPhone, unlock it and accept **Trust**. With `libimobiledevice`
installed on the client, test the connection:

```sh
python3 wireless-wire.pyz doctor --side mac --require-device
python3 wireless-wire.pyz run -- idevicepair validate
python3 wireless-wire.pyz run -- ideviceinfo -k ProductVersion
```

From a source checkout, use `dist/wireless-wire.pyz` in those commands.
The Mac client starts at login; the Linux service starts at boot. Stop the Mac
client with `launchctl bootout gui/$(id -u)/org.wireless-wire.client`.

## Limits and security

Tailscale provides encryption. The bridge adds a random shared token and accepts
only loopback or Tailscale-range addresses. Those address ranges alone do not
prove a connection uses Tailscale. Keep the VPN active and restrict access with
tailnet policy. The client socket is local to the machine, and any local process
can use it, including accessing pairing records.

Slow links use backpressure and TCP keepalives. A broken connection ends its
active sessions; new connections can reconnect. Apps may time out on slow or
unstable cellular links. Pairing and device queries were tested on real hardware;
5G performance and Finder/Xcode were not.

Tests: `python3 -m unittest discover -s tests -v`. Simulation: `python3 bin/wireless-wire demo`.
See [AUDIT.md](AUDIT.md) and [DEPENDENCIES.md](DEPENDENCIES.md). MIT licensed.

Optional [TURZX USB status display](display/README.md): live USB, Wi-Fi and
authenticated client status on the Linux host.
