"""Read Linux USB, network and authenticated bridge state without device payloads."""
import json
from pathlib import Path
import subprocess
import time

from common import clean


def command_output(args):
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True,
                              timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def usb_details(root=Path("/sys/bus/usb/devices"), excluded_usb_ids=frozenset()):
    devices = []
    for entry in sorted(root.iterdir()):
        try:
            vendor = (entry / "idVendor").read_text().strip()
            product = (entry / "idProduct").read_text().strip()
            kind = (entry / "bDeviceClass").read_text().strip()
            if kind == "09" or (vendor, product) in excluded_usb_ids:
                continue  # Hubs and the status display are not attached payload devices.
            label = clean((entry / "product").read_text().strip()) if (entry / "product").exists() else "USB device"
            try:
                rate = float((entry / "speed").read_text())
                speed = f"{rate / 1000:g} Gbit/s" if rate >= 1000 else f"{rate:g} Mbit/s"
                if rate <= 0:
                    speed = "Speed unknown"
            except (OSError, ValueError):
                speed = "Speed unknown"
            devices.append({"name": label or "USB device", "port": clean(entry.name), "speed": speed})
        except OSError:
            continue  # Device disappeared between sysfs reads, or interface rather than device.
    return devices


def usb_devices(root=Path("/sys/bus/usb/devices"), excluded_usb_ids=frozenset()):
    return [device["name"] for device in usb_details(root, excluded_usb_ids)]


def lan_addresses():
    output = command_output(["ip", "-j", "-4", "address", "show", "scope", "global"])
    try:
        return [address["local"] for interface in json.loads(output or "[]")
                if interface.get("ifname") != "tailscale0" and "UP" in interface.get("flags", [])
                for address in interface.get("addr_info", []) if address.get("family") == "inet"]
    except (TypeError, ValueError, KeyError):
        return []


def wifi_network():
    value = command_output(["nmcli", "-t", "--escape", "no", "-f", "IN-USE,SSID",
                            "device", "wifi", "list", "--rescan", "no"])
    if value is None:
        return "Status unavailable"
    active = sorted(set(clean(line[2:]) or "Hidden network" for line in value.splitlines()
                        if line.startswith("*:")))
    return ", ".join(active) if active else "Disconnected"


def tailnet_status():
    output = command_output(["tailscale", "status", "--json"])
    try:
        state = json.loads(output) if output is not None else {}
        names = {ip: clean(peer.get("HostName") or peer.get("DNSName", "").split(".")[0]) or ip
                 for peer in (state.get("Peer") or {}).values()
                 for ip in peer.get("TailscaleIPs", [])}
        addresses = state.get("Self", {}).get("TailscaleIPs", [])
        return state.get("BackendState") == "Running", names, next((ip for ip in addresses if ":" not in ip), None)
    except (TypeError, ValueError):
        return False, {}, None


def bridge_status(path, now=None):
    now = time.monotonic() if now is None else now
    try:
        state = json.loads(path.read_text())
        age = now - state["updated"]
        if state.get("schema") != 1 or not state.get("running") or not 0 <= age < 8:
            return None
        peers = state["peers"]
        if not isinstance(peers, dict) or any(not isinstance(v, int) or v < 1 for v in peers.values()):
            return None
        return state
    except (OSError, ValueError, TypeError, KeyError):
        return None


def collect(path, online, names, tailnet_ip=None, excluded_usb_ids=frozenset()):
    bridge = bridge_status(path)
    peers = bridge["peers"] if bridge else {}
    devices = usb_details(excluded_usb_ids=excluded_usb_ids)
    peer_ips = sorted(peers)
    last_ip = bridge.get("last_peer") if bridge else None
    return {"usb": [device["name"] for device in devices], "usb_details": devices,
            "wifi": wifi_network(), "tailnet": online, "lan_ips": lan_addresses(), "tailnet_ip": tailnet_ip,
            "bridge": bridge is not None,
            "clients": [names.get(ip, ip) for ip in peer_ips], "client_ips": peer_ips,
            "sessions": sum(peers.values()),
            "last_client": names.get(last_ip, last_ip), "last_ip": last_ip}
