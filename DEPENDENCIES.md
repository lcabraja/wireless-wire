# Separately installed dependencies

The repository and release archives contain our Python implementation, C launcher,
installation scripts, tests and skill. No upstream source archives, adapters,
third-party executables or Python runtime are bundled.

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
