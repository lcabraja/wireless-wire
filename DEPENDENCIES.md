# Separately installed dependencies

The repository and release archives contain our Python implementation, C launcher,
installation scripts, tests and skill. No third-party source archives, drivers,
executables or Python runtime are bundled.

The optional source-only `display/` component uses separately installed Pillow
and DejaVu fonts, plus Linux NetworkManager (`nmcli`) and iproute2 (`ip`) for
local status. The installer uses distribution packages. None is bundled in the
bridge zipapp, and the bridge runs without them. The display adapter in this
repository is our custom userspace implementation.

The optional `api/` management service uses the Python standard library, existing
Tailscale Serve for HTTPS/identity, and a narrow sudo helper for host changes.
Its browser interface has no downloaded scripts, fonts or package dependencies.

- Python 3.11+ supplies the standard library and interpreter.
- Linux `usbmuxd` handles the actual USB connection and pairing records.
- `libimobiledevice` tools provide optional pairing and device diagnostics.
- Tailscale supplies the encrypted network transport.

Install these from their distributors. They retain their own licenses:
[Python](https://www.python.org/psf/license/),
[usbmuxd](https://github.com/libimobiledevice/usbmuxd),
[libimobiledevice](https://github.com/libimobiledevice/libimobiledevice),
[Tailscale](https://github.com/tailscale/tailscale).

Native launchers dynamically use the operating system's C library and execute
an installed Python. Set `WIRELESS_WIRE_PYTHON` if `python3` is not the desired
interpreter. macOS launchers are not notarized. The `.pyz` also runs directly
with Python on either supported operating system.
