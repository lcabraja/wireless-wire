#!/usr/bin/env python3
"""Set the installed Wireless Wire screen's absolute orientation."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

DIRECTORY = Path("/etc/systemd/system/wireless-wire-display.service.d")


def configuration(rotation):
    if rotation not in (0, 90, 180, 270):
        raise ValueError("Rotation must be 0, 90, 180 or 270")
    return ("[Service]\nExecStart=\n"
            "ExecStart=/usr/bin/python3 /opt/wireless-wire-display/status_display.py "
            "--preview /run/wireless-wire-display/current.png "
            f"--rotation {rotation}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    rotation = commands.add_parser("rotation", help="0/180 portrait; 90/270 landscape")
    rotation.add_argument("degrees", type=int, choices=(0, 90, 180, 270))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(1, "Run with sudo to save the orientation and restart the display.\n")
    temporary = None
    try:
        subprocess.run(["systemctl", "cat", "wireless-wire-display.service"], check=True,
                       stdout=subprocess.DEVNULL)
        DIRECTORY.mkdir(mode=0o755, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".rotation-", dir=DIRECTORY)
        with os.fdopen(fd, "w") as output:
            os.fchmod(output.fileno(), 0o644)
            output.write(configuration(args.degrees))
        os.replace(temporary, DIRECTORY / "rotation.conf")
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "restart", "wireless-wire-display.service"], check=True)
        subprocess.run(["systemctl", "is-active", "--quiet", "wireless-wire-display.service"], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Could not apply display rotation: {exc}\n")
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    layout = "portrait" if args.degrees in (0, 180) else "landscape"
    print(f"Display set to {args.degrees} degrees ({layout}); saved for reboot.")


if __name__ == "__main__":
    main()
