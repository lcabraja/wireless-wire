from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import platform
import signal
import sys
from pathlib import Path

from . import __version__
from .transport import (BridgeError, MacBridge, PiServer,
                        create_token, endpoint, read_token)
from .usbmux import DeviceForwarder, list_devices, list_local_devices


def parser():
    p = argparse.ArgumentParser(description="One-Pi iPhone USB service bridge")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create a private token file without printing it")
    init.add_argument("--token-file", required=True, type=Path)
    for name in ("serve", "bridge"):
        part = sub.add_parser(name, help="Run the Pi relay" if name == "serve" else "Run the Mac localhost bridge")
        part.add_argument("--token-file", required=True, type=Path)
        part.add_argument("--port", type=int, default=48200 if name == "serve" else 27015)
        part.add_argument("--connect-timeout", type=float, default=30)
        part.add_argument("--max-connections", type=int, default=128)
        if name == "serve":
            part.add_argument("--listen", default="127.0.0.1", help="Literal loopback or Tailscale IP")
            part.add_argument("--usbmux-socket", default="/var/run/usbmuxd")
            part.add_argument("--status-file", type=Path, default=os.environ.get("WIRELESS_WIRE_STATUS_FILE"),
                              help="Private local status JSON for a display")
        else:
            part.add_argument("--remote", required=True, help="Pi Tailscale IP:48200 or SSH tunnel endpoint")
    for name in ("devices", "run", "forward"):
        part = sub.add_parser(name)
        part.add_argument("--port", type=int, default=27015, help="Mac localhost bridge port")
        if name == "devices":
            part.add_argument("--watch", action="store_true")
            part.add_argument("--interval", type=float, default=2)
            part.add_argument("--timeout", type=float, default=30)
        elif name == "run":
            part.add_argument("program", nargs=argparse.REMAINDER, help="libusbmuxd-aware command, following --")
        else:
            part.add_argument("--udid", help="Required if multiple devices are attached")
            part.add_argument("--device-port", type=int, required=True)
            part.add_argument("--local-port", type=int, required=True)
    doctor = sub.add_parser("doctor", help="Read-only Pi or Mac diagnostics")
    doctor.add_argument("--side", choices=("pi", "mac"), required=True)
    doctor.add_argument("--usbmux-socket", default="/var/run/usbmuxd")
    doctor.add_argument("--port", type=int, default=27015)
    doctor.add_argument("--require-device", action="store_true", help="Fail if no iPhone is attached")
    sub.add_parser("demo", help="Run the complete bridge against a fake iPhone, including a slow link")
    return p


async def wait_for_signal():
    event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, event.set)
    await event.wait()


def device_summary(devices):
    return [{"id": d.get("DeviceID"), "udid": d.get("Properties", {}).get("SerialNumber"),
             "connection": d.get("Properties", {}).get("ConnectionType")} for d in devices]


async def watch_devices(args):
    previous = None
    while True:
        try:
            devices = device_summary(await list_devices(port=args.port, timeout=args.timeout))
            value = {"status": "ok", "devices": devices}
        except (BridgeError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            value = {"status": "disconnected", "devices": []}
        encoded = json.dumps(value, sort_keys=True)
        if encoded != previous:
            print(encoded, flush=True)
            previous = encoded
        await asyncio.sleep(args.interval)


async def forward(args):
    server = await DeviceForwarder(args.local_port, args.device_port, args.port, args.udid).start()
    print(f"Forwarding localhost:{args.local_port} to iPhone service {args.device_port}", flush=True)
    try:
        await wait_for_signal()
    finally:
        await server.close()


async def doctor(args):
    report = {"version": __version__, "platform": platform.system(),
              "python": platform.python_version(), "side": args.side}
    try:
        found = (await list_local_devices(args.usbmux_socket) if args.side == "pi"
                 else await list_devices(port=args.port))
        report["usbmux"] = "ok"
        # Counts only: doctor reports are safe to share without device serials.
        report["device_count"] = len(found)
        report["next_step"] = ("Unlock and trust the iPhone, then run ideviceinfo" if found
                               else "Plug the unlocked iPhone into the Pi's USB-A data port")
        good = bool(found) or not args.require_device
    except (BridgeError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
        report["usbmux"] = "unavailable"
        report["failure_type"] = type(exc).__name__
        report["next_step"] = ("Check usbmuxd and the cable on the Pi" if args.side == "pi"
                               else "Start the localhost bridge and check the Pi's Tailscale address")
        good = False
    print(json.dumps(report, indent=2))
    return 0 if good else 1


async def async_main(args):
    if args.command == "init":
        create_token(args.token_file.expanduser())
        print(f"Token file ready: {args.token_file}")
    elif args.command in ("serve", "bridge"):
        token = read_token(args.token_file.expanduser())
        opts = {"timeout": args.connect_timeout, "max_connections": args.max_connections}
        if args.command == "serve":
            service = PiServer(args.listen, args.port, token, args.usbmux_socket,
                               status_file=args.status_file, **opts)
        else:
            host, port = endpoint(args.remote)
            service = MacBridge(args.port, host, port, token, **opts)
        await service.start()
        print(f"{args.command} listening on {service.host}:{service.port}", flush=True)
        if args.command == "bridge":
            print(f"USBMUXD_SOCKET_ADDRESS=127.0.0.1:{service.port}", flush=True)
        try:
            await wait_for_signal()
        finally:
            await service.close()
    elif args.command == "devices":
        if args.watch:
            await watch_devices(args)
        else:
            print(json.dumps(device_summary(await list_devices(port=args.port, timeout=args.timeout)), indent=2))
    elif args.command == "run":
        command = args.program[1:] if args.program[:1] == ["--"] else args.program
        if not command:
            raise BridgeError("Supply a command after --, for example ideviceinfo")
        env = dict(os.environ, USBMUXD_SOCKET_ADDRESS=f"127.0.0.1:{args.port}")
        process = await asyncio.create_subprocess_exec(*command, env=env)
        return await process.wait()
    elif args.command == "doctor":
        return await doctor(args)
    elif args.command == "forward":
        await forward(args)
    elif args.command == "demo":
        from .demo import demo
        await demo()
    return 0


def main():
    args = parser().parse_args()
    for key in ("port", "device_port", "local_port"):
        if hasattr(args, key) and not 1 <= getattr(args, key) <= 65535:
            parser().error(f"--{key.replace('_', '-')} must be between 1 and 65535")
    for key in ("connect_timeout", "max_connections", "interval", "timeout"):
        if hasattr(args, key) and (not math.isfinite(getattr(args, key)) or getattr(args, key) <= 0):
            parser().error(f"--{key.replace('_', '-')} must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        code = asyncio.run(async_main(args))
    except KeyboardInterrupt:
        code = 130
    except (BridgeError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
        print(f"wireless_wire: {exc}", file=sys.stderr)
        code = 1
    sys.exit(code)
