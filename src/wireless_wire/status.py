"""Optional local telemetry: authenticated peers only, never USB payloads."""
import asyncio
from collections import Counter
import json
import logging
import os
from pathlib import Path
import tempfile
import time


class ConnectionStatus:
    def __init__(self, path):
        self.path = Path(path)
        self.peers = Counter()
        self.last_peer = None
        self.task = None
        self.failed = False

    def publish(self, running=True):
        data = {"schema": 1, "running": running, "updated": time.monotonic(),
                "peers": dict(self.peers), "last_peer": self.last_peer}
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".status-", dir=self.path.parent)
            with os.fdopen(fd, "w") as output:
                os.fchmod(output.fileno(), 0o640)
                json.dump(data, output)
            os.replace(temporary, self.path)
            self.failed = False
        except OSError:
            if not self.failed:
                logging.getLogger("wireless-wire").warning("Local status file unavailable")
            self.failed = True
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass  # Optional telemetry must not interrupt the USB bridge.

    def connected(self, peer):
        self.peers[peer] += 1
        self.last_peer = peer
        self.publish()

    def disconnected(self, peer):
        self.peers[peer] -= 1
        if self.peers[peer] <= 0:
            del self.peers[peer]
        self.publish()

    async def heartbeat(self):
        while True:
            self.publish()
            await asyncio.sleep(2)

    def start(self):
        self.publish()
        self.task = asyncio.create_task(self.heartbeat())

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.peers.clear()
        self.publish(running=False)
