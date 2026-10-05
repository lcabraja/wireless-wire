import json
from pathlib import Path
import tempfile
import struct
import unittest
from unittest.mock import patch

from PIL import Image
from common import clean
from draw import render
from data import (bridge_status, collect, usb_devices,
                            usb_details, wifi_network, lan_addresses, tailnet_status)
from driver.turing_35_rev_a import command, rgb565, ROTATIONS, Screen, USB_IDS
from driver import load
from control import configuration


class DisplayTests(unittest.TestCase):
    def test_selected_adapter_owns_usb_identity_and_protocol(self):
        adapter = load("turing-35-rev-a")
        self.assertIs(adapter.Screen, Screen)
        self.assertIn(("1a86", "5722"), adapter.USB_IDS)

    def test_protocol_vectors(self):
        self.assertEqual(command(197, 0, 0, 479, 319), bytes.fromhex("0000077d3fc5"))
        self.assertEqual(command(109), bytes.fromhex("00000000006d"))
        self.assertEqual(rgb565(Image.new("RGB", (1, 1), "red")), b"\x00\xf8")
        with self.assertRaises(ValueError):
            command(197, 1024)

    def test_all_orientation_packets_and_control_configuration(self):
        for rotation, (orientation, width, height) in ROTATIONS.items():
            with self.subTest(rotation=rotation):
                screen = Screen.__new__(Screen)
                screen.orientation, screen.width, screen.height = orientation, width, height
                with patch.object(screen, "hello", return_value=b""), patch.object(screen, "write") as write, \
                        patch("driver.turing_35_rev_a.time.sleep"):
                    screen.initialize()
                self.assertEqual(write.call_args_list[0].args[0], command(121) +
                                 struct.pack(">BHH", orientation, width, height) + bytes(5))
                self.assertIn(f"--rotation {rotation}\n", configuration(rotation))
        with self.assertRaises(ValueError):
            configuration(45)

    def test_usb_filters_display_hubs_and_serials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, vendor, product, kind, label in [
                    ("usb1", "1d6b", "0002", "09", "Root hub"),
                    ("1-1", "1a86", "5722", "00", "Screen"),
                    ("2-1", "05ac", "12a8", "00", "iPhone")]:
                entry = root / name
                entry.mkdir()
                for key, value in dict(idVendor=vendor, idProduct=product, bDeviceClass=kind,
                                       product=label, speed="5000", serial="must-not-appear").items():
                    (entry / key).write_text(value)
            self.assertEqual(usb_devices(root, USB_IDS), ["iPhone"])
            self.assertEqual(usb_details(root, USB_IDS), [{"name": "iPhone", "speed": "5 Gbit/s", "port": "2-1"}])

    def test_lan_and_tailnet_addresses_and_hostname_resolution(self):
        interfaces = [{"ifname": "wlan0", "flags": ["UP"],
                       "addr_info": [{"family": "inet", "local": "192.168.1.10"}]},
                      {"ifname": "tailscale0", "flags": ["UP"],
                       "addr_info": [{"family": "inet", "local": "100.100.1.1"}]}]
        with patch("data.command_output", return_value=json.dumps(interfaces)):
            self.assertEqual(lan_addresses(), ["192.168.1.10"])
        tailscale = {"BackendState": "Running", "Self": {"TailscaleIPs": ["100.100.1.1"]},
                     "Peer": {"peer": {"HostName": "test-client", "TailscaleIPs": ["100.100.1.2"]}}}
        with patch("data.command_output", return_value=json.dumps(tailscale)):
            online, names, address = tailnet_status()
        self.assertEqual((online, address), (True, "100.100.1.1"))
        with patch("data.bridge_status", return_value={"peers": {"100.100.1.2": 2},
                                                                  "last_peer": "100.100.1.2"}), \
                patch("data.usb_details", return_value=[]), \
                patch("data.wifi_network", return_value="Test Wi-Fi"), \
                patch("data.lan_addresses", return_value=["192.168.1.10"]):
            state = collect(Path("unused"), online, names, address)
        self.assertEqual(state["clients"], ["test-client"])
        self.assertEqual(state["client_ips"], ["100.100.1.2"])
        self.assertEqual(state["last_ip"], "100.100.1.2")
        self.assertEqual(state["sessions"], 2)

    def test_wifi_preserves_colons_unicode_and_disconnection(self):
        with patch("data.command_output", return_value=":Nearby\n*:Café: upstairs\n"):
            self.assertEqual(wifi_network(), "Café: upstairs")
        with patch("data.command_output", return_value=":Nearby\n"):
            self.assertEqual(wifi_network(), "Disconnected")
        with patch("data.command_output", return_value=None):
            self.assertEqual(wifi_network(), "Status unavailable")

    def test_stale_corrupt_and_stopped_bridge_are_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            self.assertIsNone(bridge_status(path, now=10))
            path.write_text("{")
            self.assertIsNone(bridge_status(path, now=10))
            state = dict(schema=1, running=True, updated=10, peers={})
            path.write_text(json.dumps(state))
            self.assertIsNotNone(bridge_status(path, now=11))
            self.assertIsNone(bridge_status(path, now=19))
            self.assertIsNone(bridge_status(path, now=1))
            state["running"] = False
            path.write_text(json.dumps(state))
            self.assertIsNone(bridge_status(path, now=11))

    @unittest.skipUnless(Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf").exists(), "Linux fonts")
    def test_render_disconnected_and_many_long_names(self):
        state = dict(usb=[], wifi="Disconnected", tailnet=False, bridge=False,
                     clients=[], sessions=0, last_client=None)
        for rotation, (_, width, height) in ROTATIONS.items():
            with self.subTest(rotation=rotation):
                self.assertEqual(render(state, (width, height)).size, (width, height))
        state.update(usb=["iPhone", "Disk"], wifi="Café " * 30, clients=["client" * 30],
                     sessions=8, bridge=True, tailnet=True, lan_ips=["192.168.1.10"],
                     tailnet_ip="100.100.1.1", client_ips=["100.100.1.2"],
                     usb_details=[{"port": "2-1", "speed": "5 Gbit/s"}])
        for rotation, (_, width, height) in ROTATIONS.items():
            with self.subTest(rotation=rotation):
                self.assertEqual(render(state, (width, height)).size, (width, height))
        self.assertEqual(clean("name\x1b\n"), "name")


if __name__ == "__main__":
    unittest.main()
