#!/usr/bin/env python3
"""Optional Wireless Wire screen: collect state, draw frames, send changed rectangles."""
import argparse
import logging
from pathlib import Path
import time

from PIL import ImageChops
from data import collect, tailnet_status
from draw import render
from driver import ADAPTERS, load

LOG = logging.getLogger("wireless-wire-display")


def run(args):
    previous = None
    next_tailnet = 0
    online, names, tailnet_ip = False, {}, None
    adapter = load(args.driver)
    with adapter.Screen(args.port or adapter.DEVICE, rotation=args.rotation) as screen:
        screen.initialize(args.brightness)
        LOG.info("Display initialized (%d x %d, rotation=%d)", screen.width, screen.height, args.rotation)
        while True:
            if time.monotonic() >= next_tailnet:
                online, names, tailnet_ip = tailnet_status()
                next_tailnet = time.monotonic() + 15
            state = collect(args.status_file, online, names, tailnet_ip, adapter.USB_IDS)
            frame = render(state, (screen.width, screen.height))
            box = ImageChops.difference(previous, frame).getbbox() if previous else (0, 0, *frame.size)
            if box:
                screen.display(frame.crop(box), box[0], box[1])
                previous = frame
                if args.preview:
                    frame.save(args.preview)
                # Counts only; do not log SSIDs, client names, or phone identifiers.
                LOG.info("Screen updated: usb=%d clients=%d bridge=%s", len(state["usb"]),
                         len(state["clients"]), state["bridge"])
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver", choices=tuple(ADAPTERS), default="turing-35-rev-a")
    parser.add_argument("--port", help="Override the selected adapter's default device path")
    parser.add_argument("--rotation", type=int, choices=(0, 90, 180, 270), default=90,
                        help="Absolute orientation: 0/180 portrait, 90/270 landscape")
    parser.add_argument("--brightness", type=int, choices=range(0, 101), default=70, metavar="0..100")
    parser.add_argument("--status-file", type=Path, default=Path("/run/wireless-wire-status/status.json"))
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    while True:
        try:
            run(args)
        except (OSError, RuntimeError) as exc:
            LOG.warning("Display disconnected or unavailable (%s); retrying in 5 seconds", type(exc).__name__)
            time.sleep(5)


if __name__ == "__main__":
    main()
