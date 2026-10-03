"""Small diagnostic client for the public usbmuxd plist socket protocol."""
from __future__ import annotations

import asyncio
import plistlib
import socket
import struct
from xml.parsers.expat import ExpatError

from .transport import BridgeError, ManagedServer, close_writer, duplex, tune_tcp

HEADER = struct.Struct("<IIII")
MAX_MESSAGE = 4 * 1024 * 1024


async def send_message(writer, payload: dict, tag: int = 1):
    body = plistlib.dumps(payload, fmt=plistlib.FMT_XML)
    writer.write(HEADER.pack(HEADER.size + len(body), 1, 8, tag) + body)
    await writer.drain()


async def read_message(reader) -> tuple[int, dict]:
    length, version, message, tag = HEADER.unpack(await reader.readexactly(HEADER.size))
    if not HEADER.size <= length <= MAX_MESSAGE or version != 1 or message != 8:
        raise BridgeError("Unsupported usbmuxd message")
    try:
        payload = plistlib.loads(await reader.readexactly(length - HEADER.size))
    except (ValueError, plistlib.InvalidFileException, ExpatError, RecursionError, OverflowError) as exc:
        raise BridgeError("Invalid usbmuxd plist") from exc
    if not isinstance(payload, dict):
        raise BridgeError("Expected usbmuxd dictionary")
    return tag, payload


def request(kind: str, **fields) -> dict:
    return {"MessageType": kind, "ClientVersionString": "wireless-wire-1.0.0",
            "ProgName": "wireless-wire", "kLibUSBMuxVersion": 3, **fields}


async def list_devices(host="127.0.0.1", port=27015, timeout=30) -> list[dict]:
    writer = None
    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(host, port)
            tune_tcp(writer)
            await send_message(writer, request("ListDevices"))
            tag, payload = await read_message(reader)
            if tag != 1 or not isinstance(payload.get("DeviceList"), list):
                raise BridgeError("usbmuxd did not return a device list")
            return payload["DeviceList"]
    finally:
        await close_writer(writer)


async def list_local_devices(path="/var/run/usbmuxd", timeout=10) -> list[dict]:
    writer = None
    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_unix_connection(path)
            await send_message(writer, request("ListDevices"))
            tag, payload = await read_message(reader)
            if tag != 1 or not isinstance(payload.get("DeviceList"), list):
                raise BridgeError("usbmuxd did not return a device list")
            return payload["DeviceList"]
    finally:
        await close_writer(writer)


async def connect_device(device_id: int, device_port: int,
                         host="127.0.0.1", port=27015, timeout=30):
    writer = None
    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(host, port)
            tune_tcp(writer)
            await send_message(writer, request("Connect", DeviceID=device_id,
                                               PortNumber=socket.htons(device_port)))
            tag, payload = await read_message(reader)
            if tag != 1 or payload.get("MessageType") != "Result" or payload.get("Number") != 0:
                raise BridgeError(f"iPhone connection rejected, result={payload.get('Number')}")
        # On success the socket becomes the device service's raw byte stream.
        return reader, writer
    except BaseException:
        await close_writer(writer)
        raise


class DeviceForwarder(ManagedServer):
    def __init__(self, local_port, device_port, bridge_port=27015, udid=None):
        super().__init__("127.0.0.1", local_port)
        self.device_port = device_port
        self.bridge_port = bridge_port
        self.udid = udid

    async def handle(self, reader, writer):
        device_writer = None
        try:
            devices = await list_devices(port=self.bridge_port)
            matches = [d for d in devices if not self.udid or
                       d.get("Properties", {}).get("SerialNumber") == self.udid]
            if len(matches) != 1:
                raise BridgeError("Expected one matching iPhone; select it with --udid")
            device_reader, device_writer = await connect_device(
                matches[0]["DeviceID"], self.device_port, port=self.bridge_port)
            await duplex(reader, writer, device_reader, device_writer)
        finally:
            await close_writer(device_writer)
