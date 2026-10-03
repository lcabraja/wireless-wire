"""Authenticated stream forwarding over loopback or an encrypted Tailscale link.

Each usbmux connection gets its own network connection. USB service bytes,
including pairing records and end-to-end TLS, pass through without inspection.
"""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
import os
import secrets
import socket
import stat
import struct
from pathlib import Path

LOG = logging.getLogger("wireless-wire")
MAGIC = b"PIPHONE1"
MAX_HANDSHAKE = 4096
DEFAULT_CHUNK = 65536
NETWORKS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fd7a:115c:a1e0::/48"),
)


class BridgeError(Exception):
    """An expected, user-readable bridge failure."""


def allowed_address(address: str) -> str:
    """Require a literal loopback/Tailscale IP; no public plaintext transport."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise BridgeError("Use a literal loopback or Tailscale IP address") from exc
    if not (ip.is_loopback or any(ip in net for net in NETWORKS)):
        raise BridgeError("Use a Tailscale IP or a loopback SSH tunnel")
    return str(ip)


def endpoint(value: str) -> tuple[str, int]:
    """Parse IPv4:port or [IPv6]:port."""
    if value.startswith("["):
        close = value.find("]:")
        if close < 0:
            raise BridgeError("Expected [IPv6]:port")
        host, port = value[1:close], value[close + 2:]
    else:
        host, sep, port = value.rpartition(":")
        if not sep or ":" in host:
            raise BridgeError("Expected IP:port or [IPv6]:port")
    try:
        number = int(port)
    except ValueError as exc:
        raise BridgeError("Port must be a number") from exc
    if not 1 <= number <= 65535:
        raise BridgeError("Port must be between 1 and 65535")
    return allowed_address(host), number


def create_token(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL and O_NOFOLLOW avoid replacing an existing secret or a symlink.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        read_token(path)
        return
    with os.fdopen(fd, "w") as handle:
        handle.write(secrets.token_hex(32) + "\n")


def read_token(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise BridgeError(f"Cannot open token file: {path}") from exc
    with os.fdopen(fd, "r") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise BridgeError("Token must be a regular file with mode 0600")
        try:
            raw = handle.read(258)
        except UnicodeError as exc:
            raise BridgeError("Token must contain ASCII characters") from exc
    token = raw.removesuffix("\n")
    if not 32 <= len(token) <= 256 or any(not 33 <= ord(c) <= 126 for c in token):
        raise BridgeError("Token must contain 32 to 256 printable non-space ASCII characters")
    return token


def tune_tcp(writer: asyncio.StreamWriter) -> None:
    sock = writer.get_extra_info("socket")
    if sock is None or sock.family not in (socket.AF_INET, socket.AF_INET6):
        return
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    # Detect dead links without imposing a short idle timeout on debugging.
    for option, value in (("TCP_KEEPIDLE", 60), ("TCP_KEEPALIVE", 60),
                          ("TCP_KEEPINTVL", 15), ("TCP_KEEPCNT", 4)):
        key = getattr(socket, option, None)
        if key is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, key, value)
            except OSError:
                pass


async def close_writer(writer: asyncio.StreamWriter | None) -> None:
    if writer is None:
        return
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), 2)
    except (OSError, asyncio.TimeoutError):
        writer.transport.abort()


async def read_json(reader: asyncio.StreamReader) -> dict:
    length = struct.unpack("!I", await reader.readexactly(4))[0]
    if not 1 <= length <= MAX_HANDSHAKE:
        raise BridgeError("Invalid handshake length")
    try:
        value = json.loads(await reader.readexactly(length))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise BridgeError("Invalid handshake JSON") from exc
    if not isinstance(value, dict):
        raise BridgeError("Invalid handshake object")
    return value


async def write_json(writer: asyncio.StreamWriter, value: dict) -> None:
    data = json.dumps(value, separators=(",", ":")).encode()
    if len(data) > MAX_HANDSHAKE:
        raise BridgeError("Handshake is too large")
    writer.write(struct.pack("!I", len(data)) + data)
    await writer.drain()


async def open_remote(host: str, port: int, token: str, timeout: float = 30):
    writer = None
    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(host, port)
            tune_tcp(writer)
            writer.write(MAGIC)
            await write_json(writer, {"token": token})
            response = await read_json(reader)
            if response.get("status") != "ok":
                reason = response.get("error")
                if reason not in ("Authentication failed", "Pi usbmuxd socket unavailable"):
                    reason = "Remote bridge rejected connection"
                raise BridgeError(reason)
        return reader, writer
    except BaseException:
        await close_writer(writer)
        raise


async def pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
               chunk_size: int = DEFAULT_CHUNK) -> int:
    count = 0
    while data := await reader.read(chunk_size):
        writer.write(data)
        await writer.drain()  # Bounded buffering when the network is slow.
        count += len(data)
    if writer.can_write_eof():
        writer.write_eof()
        await writer.drain()
    return count


async def duplex(a_reader, a_writer, b_reader, b_writer,
                 chunk_size: int = DEFAULT_CHUNK) -> tuple[int, int]:
    """Preserve half-close: a peer may finish sending before receiving a reply."""
    tasks = [asyncio.create_task(pump(a_reader, b_writer, chunk_size)),
             asyncio.create_task(pump(b_reader, a_writer, chunk_size))]
    try:
        # FIRST_EXCEPTION allows an orderly half-close to drain its response,
        # but a broken direction immediately cancels the other direction.
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            if task.exception() is not None:
                raise task.exception()
        return tasks[0].result(), tasks[1].result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class ManagedServer:
    def __init__(self, host: str, port: int, max_connections: int = 128):
        self.host = allowed_address(host)
        self.port = port
        self.max_connections = max_connections
        self.server = None
        self.tasks: set[asyncio.Task] = set()
        self.closing = False

    async def start(self):
        self.server = await asyncio.start_server(self._accepted, self.host, self.port)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def _accepted(self, reader, writer):
        task = asyncio.current_task()
        if self.closing or len(self.tasks) >= self.max_connections:
            await close_writer(writer)
            return
        self.tasks.add(task)
        try:
            tune_tcp(writer)
            await self.handle(reader, writer)
        except (BridgeError, OSError, asyncio.IncompleteReadError, asyncio.TimeoutError) as exc:
            # Exception class only: never log pairing/service data or tokens.
            LOG.warning("Connection ended: %s", type(exc).__name__)
        finally:
            self.tasks.discard(task)
            await close_writer(writer)

    async def close(self):
        self.closing = True
        if self.server:
            self.server.close()
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Python 3.13+ waits for active transports too; drain them first.
        if self.server:
            await self.server.wait_closed()


class PiServer(ManagedServer):
    def __init__(self, host, port, token, usbmux_socket, timeout=30, **kwargs):
        super().__init__(host, port, **kwargs)
        self.token = token
        self.usbmux_socket = str(usbmux_socket)
        self.timeout = timeout

    async def handle(self, reader, writer):
        backend_writer = None
        try:
            async with asyncio.timeout(self.timeout):
                if await reader.readexactly(len(MAGIC)) != MAGIC:
                    raise BridgeError("Invalid protocol")
                request = await read_json(reader)
                supplied = request.get("token")
                if (not isinstance(supplied, str) or not supplied.isascii()
                        or not hmac.compare_digest(supplied, self.token)):
                    await write_json(writer, {"status": "error", "error": "Authentication failed"})
                    return
                try:
                    backend_reader, backend_writer = await asyncio.open_unix_connection(self.usbmux_socket)
                except OSError:
                    await write_json(writer, {"status": "error", "error": "Pi usbmuxd socket unavailable"})
                    return
                await write_json(writer, {"status": "ok"})
            sent, received = await duplex(reader, writer, backend_reader, backend_writer)
            LOG.info("Session closed: sent=%d received=%d", sent, received)
        finally:
            await close_writer(backend_writer)


class MacBridge(ManagedServer):
    def __init__(self, port, remote_host, remote_port, token, timeout=30, **kwargs):
        # Raw usbmux access remains on localhost even when the Pi is remote.
        super().__init__("127.0.0.1", port, **kwargs)
        self.remote_host = allowed_address(remote_host)
        self.remote_port = remote_port
        self.token = token
        self.timeout = timeout

    async def handle(self, reader, writer):
        remote_writer = None
        try:
            remote_reader, remote_writer = await open_remote(
                self.remote_host, self.remote_port, self.token, self.timeout)
            await duplex(reader, writer, remote_reader, remote_writer)
        finally:
            await close_writer(remote_writer)
