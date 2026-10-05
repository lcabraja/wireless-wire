# TURZX status display

Optional Linux status screen for the 3.5-inch Turing/TURZX revision A USB
monitor (`1a86:5722`, `USB35INCHIPSV2`). Portrait at 320 × 480 or landscape at
480 × 320, with a layout that adapts to either shape.
Uses the custom userspace driver recovered from the earlier display project;
no vendor executable or firmware is installed.

## Layout

```text
display/
  draw/status.py                 Pillow layout and image rendering
  driver/turing_35_rev_a/         Turing/TURZX 3.5-inch revision A adapter
  driver/__init__.py             Adapter registry
  data.py                       Import shared host status from the core package
  common.py                     Text sanitization
  status_display.py             Polling and changed-rectangle updates
  control.py                    Installed rotation command
  install.sh                    Optional Pi installation
```

The core bridge does not import this component or depend on Pillow. Install the
screen separately using the source checkout instructions below. The existing v1
release archives do not include the optional screen component.
Status collection lives in `src/wireless_wire/host_status.py` and is shared with
the optional management API, so both interfaces report the same state.

`draw.render(state, size)` returns an RGB image without opening USB or querying
the network. It currently lays out 320 × 480 and 480 × 320 screens.
The selected adapter supplies `Screen(port, rotation)`, its `width` and `height`,
`initialize(brightness)`, `display(image, x, y)`, and context-manager cleanup.
It also supplies `DEVICE` and `USB_IDS`, so the collector can exclude the screen
itself. Add another adapter under `driver/<device_name>/`, register it in
`driver/__init__.py`, and select it with `--driver`. The current driver name is
`turing-35-rev-a`. Each adapter owns its protocol, pixel encoding and orientation.

Run the screen tests on Linux with Pillow and DejaVu installed:

```sh
python3 -m unittest discover -s display -v
```

## Status and installation

Shows attached USB devices (excluding hubs and this display), active Wi-Fi
SSID, LAN and Tailscale IPv4 addresses, USB port and negotiated link speed,
and authenticated Wireless Wire clients by Tailscale hostname and IP. USB speed
is the negotiated bus rate, not measured forwarding throughput. A client
session means an open usbmux connection, including device discovery/listening;
it does not prove an app is transferring data. An idle client daemon may have
no connection. The last client remains labelled separately when disconnected.
Other USB devices can appear here but Wireless Wire still only bridges iPhone
usbmux services.

On the Pi, from a source checkout with Wireless Wire already installed:

```sh
python3 scripts/build.py
sudo bash display/install.sh
```

The installer updates the bridge zipapp and briefly restarts the bridge.
It preserves the token and saves the preceding zipapp as
`/opt/wireless-wire/wireless-wire.before-display.pyz`. Both services start at
boot. NetworkManager and Tailscale must already be installed.

Status polls every second; Tailscale names refresh every 15 seconds. Only
changed rectangles are sent. A full frame takes roughly 2–3 seconds on this
screen. USB reconnects are retried automatically. A mid-frame USB failure can
require physically reconnecting the screen to reset its parser.

`systemctl status wireless-wire-display` and
`journalctl -u wireless-wire-display` show counts and errors, never credentials.
The local preview is `/run/wireless-wire-display/current.png` (private).
Wi-Fi and Tailscale appear side by side above the USB and bridge client rows.

Set the absolute orientation on the Pi, immediately and across reboots:

```sh
sudo wireless-wire-display rotation 0
```

Use `0` or `180` for vertical portrait, `90` or `270` for horizontal landscape.
Angles are absolute, not relative to the current screen. The command restarts
only the display service. The Python renderer also accepts `--rotation` with
any of these four values.

Telemetry in `/run/wireless-wire-status/status.json` contains only timestamps,
authenticated peer IPs/session counts and the last peer. No token, pairing
record, device serial or service payload is inspected or copied. It is readable
only by the bridge account, its group and root. Stale telemetry is displayed
as unavailable. The display service runs as a separate unprivileged account.

Transport protocol reference:
[Turing revision A](https://github.com/mathoudebine/turing-smart-screen-python/blob/main/library/lcd/lcd_comm_rev_a.py).
Pillow and DejaVu fonts come from distribution packages and are not bundled.
The protocol has no framebuffer readback: successful USB writes do not by
themselves confirm the screen's physical appearance.

To disable: `sudo systemctl disable --now wireless-wire-display.service`.
