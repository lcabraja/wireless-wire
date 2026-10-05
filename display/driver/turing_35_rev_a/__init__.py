#!/usr/bin/env python3
"""Small Linux userspace driver for the Turing 3.5-inch revision A screen.

Protocol reference (no vendor code or binaries required):
https://github.com/mathoudebine/turing-smart-screen-python
The transport uses only Python's standard library; image rendering uses Pillow.
"""

import array
import fcntl
import os
import select
import struct
import sys
import termios
import time


DEVICE = "/dev/serial/by-id/usb-Turing_UsbMonitor_USB35INCHIPSV2-if00"
USB_IDS = frozenset({("1a86", "5722")})
ROTATIONS = {0: (100, 320, 480), 90: (102, 480, 320),
             180: (101, 320, 480), 270: (103, 480, 320)}


def command(opcode, x=0, y=0, right=0, bottom=0):
    """Pack four 10-bit coordinates followed by one opcode byte."""
    if any(not 0 <= n <= 1023 for n in (x, y, right, bottom)):
        raise ValueError("Coordinates must fit in 10 bits")
    coordinates = (x << 30) | (y << 20) | (right << 10) | bottom
    return coordinates.to_bytes(5, "big") + bytes([opcode])


def rgb565(image):
    raw = image.convert("RGB").tobytes()
    pixels = array.array("H", (((r & 248) << 8) | ((g & 252) << 3) | (b >> 3)
                              for r, g, b in zip(raw[0::3], raw[1::3], raw[2::3])))
    if sys.byteorder != "little":
        pixels.byteswap()
    return pixels.tobytes()


class Screen:
    def __init__(self, port=DEVICE, rotation=90, timeout=10):
        self.rotation = rotation
        self.orientation, self.width, self.height = ROTATIONS[rotation]
        self.timeout = timeout
        self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            # Cooperating driver instances cannot interleave commands and pixels.
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            settings = termios.tcgetattr(self.fd)
            settings[0] = settings[1] = settings[3] = 0
            settings[2] = termios.CS8 | termios.CLOCAL | termios.CREAD | termios.CRTSCTS
            settings[4] = settings[5] = termios.B115200
            settings[6][termios.VMIN] = 0
            settings[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, settings)
            termios.tcflush(self.fd, termios.TCIFLUSH)
        except BaseException:
            os.close(self.fd)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        os.close(self.fd)

    def write(self, data):
        pending = memoryview(data)
        deadline = time.monotonic() + self.timeout
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.fd], [], remaining)[1]:
                raise TimeoutError("Screen stopped accepting data; reconnect USB before retrying")
            try:
                count = os.write(self.fd, pending)
            except BlockingIOError:
                continue
            if count == 0:
                raise OSError("USB write returned zero bytes")
            pending = pending[count:]

    def hello(self):
        self.write(b"\x45" * 6)
        response = bytearray()
        deadline = time.monotonic() + 1
        while len(response) < 6:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.fd], [], [], remaining)[0]:
                break
            try:
                part = os.read(self.fd, 6 - len(response))
            except BlockingIOError:
                continue
            if not part:
                break
            response.extend(part)
        return bytes(response)

    def drain(self):
        deadline = time.monotonic() + self.timeout
        while struct.unpack("I", fcntl.ioctl(self.fd, termios.TIOCOUTQ, bytes(4)))[0]:
            if time.monotonic() >= deadline:
                raise TimeoutError("Timed out waiting for the USB output queue")
            time.sleep(0.01)

    def initialize(self, brightness=70):
        if not 0 <= brightness <= 100:
            raise ValueError("Brightness must be between 0 and 100")
        response = self.hello()
        # Original 3.5-inch firmware may not answer HELLO.
        if response not in (b"", b"\x01" * 6):
            raise RuntimeError(f"Unexpected model response {response.hex()}; refusing 3.5-inch pixels")
        packet = command(121) + struct.pack(">BHH", self.orientation, self.width, self.height) + bytes(5)
        self.write(packet)
        self.write(command(109))
        self.write(command(110, x=int(255 * (1 - brightness / 100))))
        time.sleep(0.1)
        return response

    def display(self, image, x=0, y=0):
        w, h = image.size
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > self.width or y + h > self.height:
            raise ValueError("Image rectangle lies outside the display")
        data = rgb565(image)
        self.write(command(197, x, y, x + w - 1, y + h - 1))
        for start in range(0, len(data), self.width * 8):
            self.write(data[start:start + self.width * 8])
        self.drain()
        return len(data)
