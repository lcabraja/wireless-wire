"""A simulated usbmuxd backend. This does not emulate Apple's real firmware."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import tempfile
import time
from pathlib import Path

from .transport import MacBridge, PiServer, close_writer
from .usbmux import connect_device, list_devices, read_message, send_message

FAKE_DEVICE = {"DeviceID": 7, "Properties": {"DeviceID": 7,
    "SerialNumber": "SIMULATED-IPHONE-NO-HARDWARE", "ConnectionType": "USB", "ProductID": 0x12A8}}


class FakeMux:
    """Plist listing/events, pairing records and binary test service streams."""
    def __init__(self, path, delay=0.0, bytes_per_second=None):
        self.path = str(path)
        self.delay = delay
        self.bytes_per_second = bytes_per_second
        self.attached = True
        self.server = None
        self.tasks = set()
        self.listeners = set()
        self.services = set()
        self.pair_records = {}
        self.connection_count = 0

    async def start(self):
        self.server = await asyncio.start_unix_server(self.handle, self.path)
        return self

    async def respond(self, writer, payload, tag=1):
        if self.delay:
            await asyncio.sleep(self.delay)
        await send_message(writer, payload, tag)

    async def set_attached(self, value):
        self.attached = value
        event = ({"MessageType": "Attached", **FAKE_DEVICE} if value
                 else {"MessageType": "Detached", "DeviceID": 7})
        for writer in list(self.listeners):
            try:
                await send_message(writer, event, 0)
            except OSError:
                self.listeners.discard(writer)
        if not value:
            for writer in list(self.services):
                await close_writer(writer)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.connection_count += 1
        try:
            while True:
                tag, req = await read_message(reader)
                kind = req.get("MessageType")
                if kind == "ListDevices":
                    await self.respond(writer, {"DeviceList": [FAKE_DEVICE] if self.attached else []}, tag)
                elif kind == "Listen":
                    self.listeners.add(writer)
                    await self.respond(writer, {"MessageType": "Result", "Number": 0}, tag)
                    if self.attached:
                        await self.respond(writer, {"MessageType": "Attached", **FAKE_DEVICE}, 0)
                    await reader.read()
                    break
                elif kind == "ReadBUID":
                    await self.respond(writer, {"BUID": "SIMULATED-BUID"}, tag)
                elif kind == "SavePairRecord":
                    self.pair_records[req["PairRecordID"]] = req["PairRecordData"]
                    await self.respond(writer, {"MessageType": "Result", "Number": 0}, tag)
                elif kind == "ReadPairRecord":
                    record = self.pair_records.get(req["PairRecordID"])
                    await self.respond(writer, {"PairRecordData": record} if record is not None
                                       else {"MessageType": "Result", "Number": 2}, tag)
                elif kind == "Connect":
                    number = 0 if self.attached and req.get("DeviceID") == 7 else 2
                    await self.respond(writer, {"MessageType": "Result", "Number": number}, tag)
                    if number:
                        continue
                    self.services.add(writer)
                    port = socket.ntohs(req["PortNumber"])
                    if port == 65001:
                        digest = hashlib.sha256()
                        while data := await reader.read(16384):
                            digest.update(data)
                        writer.write(digest.digest())
                        await writer.drain()
                    else:
                        while data := await reader.read(16384):
                            if self.delay:
                                await asyncio.sleep(self.delay)
                            if self.bytes_per_second:
                                await asyncio.sleep(len(data) / self.bytes_per_second)
                            writer.write(data)
                            await writer.drain()
                    break
                else:
                    await self.respond(writer, {"MessageType": "Result", "Number": 1}, tag)
        except (asyncio.IncompleteReadError, ConnectionError, BrokenPipeError):
            pass
        finally:
            self.listeners.discard(writer)
            self.services.discard(writer)
            self.tasks.discard(task)
            await close_writer(writer)

    async def close(self):
        if self.server:
            self.server.close()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.server:
            await self.server.wait_closed()


async def demo():
    results = []
    with tempfile.TemporaryDirectory(prefix="wireless_wire-") as tmp:
        # Keep the socket path short enough for macOS's UNIX path limit.
        path = Path(tmp) / "mux"
        if len(str(path).encode()) > 100:
            raise RuntimeError("Use a shorter TMPDIR for the demo's UNIX socket")
        backend = await FakeMux(path, delay=0.075, bytes_per_second=125000).start()
        pi = await PiServer("127.0.0.1", 0, "demo-token", path).start()
        mac = await MacBridge(0, "127.0.0.1", pi.port, "demo-token").start()
        try:
            devices = await list_devices(port=mac.port)
            assert devices[0]["DeviceID"] == 7
            results.append({"check": "device enumeration", "status": "passed"})

            data = os.urandom(128 * 1024)
            started = time.monotonic()
            reader, writer = await connect_device(7, 62078, port=mac.port)
            try:
                writer.write(data)
                await writer.drain()
                received = await asyncio.wait_for(reader.readexactly(len(data)), 15)
                assert received == data
            finally:
                await close_writer(writer)
            results.append({"check": "binary echo with 75ms per backend chunk and 1Mbps pacing",
                            "status": "passed", "bytes": len(data),
                            "seconds": round(time.monotonic() - started, 3)})

            await backend.set_attached(False)
            assert await list_devices(port=mac.port) == []
            await backend.set_attached(True)
            assert len(await list_devices(port=mac.port)) == 1
            results.append({"check": "unplug and replug", "status": "passed"})
        finally:
            await mac.close()
            await pi.close()
            await backend.close()
    print(json.dumps({"hardware": "simulated", "checks": results,
                      "unverified": ["real iPhone USB", "pairing with iOS", "Finder/Xcode", "real cellular network"]}, indent=2))
