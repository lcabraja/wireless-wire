import asyncio
import hashlib
import os
import socket
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wireless_wire.demo import FakeMux
from wireless_wire.transport import (BridgeError, MAGIC, MacBridge, PiServer, allowed_address,
                               close_writer, create_token, endpoint, open_remote,
                               read_json, read_token, write_json)
from wireless_wire.usbmux import (HEADER, DeviceForwarder, connect_device, list_devices,
                           read_message, request, send_message)


class ConfigurationTests(unittest.TestCase):
    def test_private_token_and_idempotent_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "token"
            create_token(path)
            token = read_token(path)
            create_token(path)
            self.assertEqual(token, read_token(path))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            path.chmod(0o644)
            with self.assertRaises(BridgeError):
                read_token(path)

    def test_token_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "token"
            create_token(path)
            linked = Path(tmp) / "link"
            linked.symlink_to(path)
            with self.assertRaises(BridgeError):
                read_token(linked)

    def test_token_fifo_is_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fifo"
            os.mkfifo(path, 0o600)
            with self.assertRaises(BridgeError):
                read_token(path)

    def test_tokens_reject_truncation_controls_and_non_ascii(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "token"
            for content in (b"x" * 257, b"x" * 256 + b"\nextra", b"x" * 32 + b"\x00",
                            b"x" * 32 + b"\xff", b" " + b"x" * 32):
                path.write_bytes(content)
                path.chmod(0o600)
                with self.subTest(length=len(content)), self.assertRaises(BridgeError):
                    read_token(path)
            path.write_bytes(b"x" * 256 + b"\n")
            self.assertEqual(read_token(path), "x" * 256)

    def test_only_loopback_or_tailnet_transport(self):
        for address in ("127.0.0.1", "::1", "100.101.102.103", "fd7a:115c:a1e0::1"):
            self.assertEqual(allowed_address(address), address)
        for address in ("0.0.0.0", "192.168.1.2", "8.8.8.8", "example.com"):
            with self.assertRaises(BridgeError):
                allowed_address(address)
        self.assertEqual(endpoint("[::1]:48200"), ("::1", 48200))
        for value in ("127.0.0.1:0", "127.0.0.1:99999", "[::1]", "localhost:42"):
            with self.assertRaises(BridgeError):
                endpoint(value)


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="piph-test-", dir="/tmp")
        self.path = Path(self.tmp.name) / "mux"
        self.backend = await FakeMux(self.path).start()
        self.pi = await PiServer("127.0.0.1", 0, "test-token", self.path).start()
        self.mac = await MacBridge(0, "127.0.0.1", self.pi.port, "test-token").start()

    async def asyncTearDown(self):
        await self.mac.close()
        await self.pi.close()
        await self.backend.close()
        self.tmp.cleanup()

    async def test_devices_cross_entire_bridge(self):
        found = await list_devices(port=self.mac.port)
        self.assertEqual(found[0]["DeviceID"], 7)
        self.assertEqual(found[0]["Properties"]["ConnectionType"], "USB")

    async def test_authentication_never_opens_backend_for_wrong_token(self):
        with self.assertRaisesRegex(BridgeError, "Authentication"):
            await open_remote("127.0.0.1", self.pi.port, "wrong-token")
        self.assertEqual(self.backend.connection_count, 0)

    async def test_missing_backend_gives_useful_error(self):
        pi = await PiServer("127.0.0.1", 0, "test-token", self.path.parent / "missing").start()
        try:
            with self.assertRaisesRegex(BridgeError, "socket unavailable"):
                await open_remote("127.0.0.1", pi.port, "test-token")
        finally:
            await pi.close()

    async def test_oversized_handshake_is_rejected_before_payload_read(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.pi.port)
        try:
            writer.write(MAGIC + struct.pack("!I", 0xFFFFFFFF))
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")
            self.assertEqual(self.backend.connection_count, 0)
        finally:
            await close_writer(writer)

    async def test_malformed_authentication_does_not_crash_server(self):
        for supplied in (None, 42, {}, "\u2603"):
            reader, writer = await asyncio.open_connection("127.0.0.1", self.pi.port)
            try:
                writer.write(MAGIC)
                await write_json(writer, {"token": supplied})
                self.assertEqual((await read_json(reader))["status"], "error")
            finally:
                await close_writer(writer)
        self.assertEqual(len(await list_devices(port=self.mac.port)), 1)

    async def test_deeply_nested_json_closes_only_its_connection(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.pi.port)
        data = b"[" * 1500 + b"0" + b"]" * 1500
        try:
            writer.write(MAGIC + struct.pack("!I", len(data)) + data)
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")
        finally:
            await close_writer(writer)
        self.assertEqual(self.backend.connection_count, 0)
        self.assertEqual(len(await list_devices(port=self.mac.port)), 1)

    async def test_invalid_xml_is_a_bounded_protocol_error(self):
        reader = asyncio.StreamReader()
        body = b"<?xml version='1.0'?><plist><dict></plist>"
        reader.feed_data(HEADER.pack(len(body) + 16, 1, 8, 1) + body)
        reader.feed_eof()
        with self.assertRaises(BridgeError):
            await read_message(reader)

    async def test_binary_transfer_is_exact_and_parallel(self):
        async def echo(size):
            reader, writer = await connect_device(7, 62078, port=self.mac.port)
            data = os.urandom(size)
            try:
                writer.write(data)
                await writer.drain()
                self.assertEqual(await asyncio.wait_for(reader.readexactly(size), 5), data)
            finally:
                await close_writer(writer)
        await asyncio.gather(*(echo(50000 + i) for i in range(8)))

    async def test_half_close_keeps_response_direction_alive(self):
        reader, writer = await connect_device(7, 65001, port=self.mac.port)
        data = os.urandom(1024 * 1024)
        try:
            writer.write(data)
            await writer.drain()
            writer.write_eof()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(32), 5), hashlib.sha256(data).digest())
            self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
        finally:
            await close_writer(writer)

    async def test_plist_fragmentation_and_pair_record_bytes_are_preserved(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.mac.port)
        record = b"bplist00" + os.urandom(512)
        try:
            await send_message(writer, request("SavePairRecord", PairRecordID="fake", PairRecordData=record), 91)
            tag, result = await read_message(reader)
            self.assertEqual((tag, result["Number"]), (91, 0))
            import plistlib
            body = plistlib.dumps(request("ReadPairRecord", PairRecordID="fake"))
            packet = HEADER.pack(len(body) + 16, 1, 8, 92) + body
            for start in range(0, len(packet), 3):
                writer.write(packet[start:start + 3])
                await writer.drain()
                await asyncio.sleep(0)
            tag, result = await read_message(reader)
            self.assertEqual(tag, 92)
            self.assertEqual(result["PairRecordData"], record)
        finally:
            await close_writer(writer)

    async def test_attach_detach_notifications_and_replug(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.mac.port)
        try:
            await send_message(writer, request("Listen"))
            self.assertEqual((await read_message(reader))[1]["Number"], 0)
            self.assertEqual((await read_message(reader))[1]["MessageType"], "Attached")
            await self.backend.set_attached(False)
            self.assertEqual((await read_message(reader))[1]["MessageType"], "Detached")
            self.assertEqual(await list_devices(port=self.mac.port), [])
            await self.backend.set_attached(True)
            self.assertEqual((await read_message(reader))[1]["MessageType"], "Attached")
            self.assertEqual(len(await list_devices(port=self.mac.port)), 1)
        finally:
            await close_writer(writer)

    async def test_unplug_closes_existing_device_stream(self):
        reader, writer = await connect_device(7, 62078, port=self.mac.port)
        try:
            await self.backend.set_attached(False)
            self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
        finally:
            await close_writer(writer)

    async def test_reconnect_after_pi_restart_without_replaying_session(self):
        reader, writer = await connect_device(7, 62078, port=self.mac.port)
        old_port = self.pi.port
        await self.pi.close()
        try:
            self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
        finally:
            await close_writer(writer)
        self.pi = await PiServer("127.0.0.1", old_port, "test-token", self.path).start()
        self.assertEqual(len(await list_devices(port=self.mac.port)), 1)

    async def test_slow_backend_does_not_corrupt_service_stream(self):
        self.backend.delay = 0.05
        self.backend.bytes_per_second = 65536
        data = os.urandom(32768)
        reader, writer = await connect_device(7, 62078, port=self.mac.port)
        try:
            writer.write(data)
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(len(data)), 4), data)
        finally:
            await close_writer(writer)

    async def test_idle_connection_survives_then_transfers(self):
        reader, writer = await connect_device(7, 62078, port=self.mac.port)
        try:
            await asyncio.sleep(0.2)
            writer.write(b"still-alive")
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(11), 2), b"still-alive")
        finally:
            await close_writer(writer)

    async def test_service_forwarder_and_shutdown_with_active_client(self):
        forward = await DeviceForwarder(0, 62078, self.mac.port).start()
        reader, writer = await asyncio.open_connection("127.0.0.1", forward.port)
        try:
            writer.write(b"forward-test")
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(12), 2), b"forward-test")
            await asyncio.wait_for(forward.close(), 3)
            self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
        finally:
            await close_writer(writer)
            await forward.close()

    async def test_forwarder_refuses_wrong_device_selection(self):
        forward = await DeviceForwarder(0, 62078, self.mac.port, "wrong-udid").start()
        reader, writer = await asyncio.open_connection("127.0.0.1", forward.port)
        try:
            self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
        finally:
            await close_writer(writer)
            await forward.close()

    async def test_partial_handshake_has_a_deadline(self):
        pi = await PiServer("127.0.0.1", 0, "test-token", self.path, timeout=0.05).start()
        reader, writer = await asyncio.open_connection("127.0.0.1", pi.port)
        try:
            writer.write(MAGIC[:2])
            await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.read(), 1), b"")
        finally:
            await close_writer(writer)
            await pi.close()

    async def test_connection_limit_rejects_extra_idle_handshakes(self):
        pi = await PiServer("127.0.0.1", 0, "test-token", self.path, max_connections=1).start()
        r1, w1 = await asyncio.open_connection("127.0.0.1", pi.port)
        r2, w2 = await asyncio.open_connection("127.0.0.1", pi.port)
        try:
            self.assertEqual(await asyncio.wait_for(r2.read(), 1), b"")
            self.assertEqual(self.backend.connection_count, 0)
        finally:
            await close_writer(w1)
            await close_writer(w2)
            await pi.close()


if __name__ == "__main__":
    unittest.main()
