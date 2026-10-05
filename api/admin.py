#!/usr/bin/python3
"""Narrow root helper. One bounded JSON request on stdin, no shell commands."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

NETWORKS = Path('/etc/NetworkManager/system-connections')
ROTATION = Path('/etc/systemd/system/wireless-wire-display.service.d/rotation.conf')


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=25).stdout


def atomic(path, content, mode=0o600):
    fd, temporary = tempfile.mkstemp(prefix='.wireless-wire-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            os.fchmod(output.fileno(), mode)
            output.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def wifi_profile(ssid, password):
    if (not isinstance(ssid, str) or not 1 <= len(ssid.encode('utf-8')) <= 32
            or any(ord(c) < 32 or ord(c) == 127 for c in ssid)):
        raise ValueError('SSID must contain 1–32 UTF-8 bytes without control characters')
    if not isinstance(password, str) or not 8 <= len(password) <= 63 or not password.isascii() or any(ord(c) < 32 or ord(c) > 126 for c in password):
        raise ValueError('WPA2 password must contain 8–63 printable ASCII characters')
    identity = str(uuid.uuid5(uuid.NAMESPACE_URL, 'wireless-wire:wifi:' + ssid))
    psk = hashlib.pbkdf2_hmac('sha1', password.encode(), ssid.encode(), 4096, 32).hex()
    # Byte-list SSID avoids keyfile escaping and preserves non-ASCII names.
    encoded = ''.join(str(byte) + ';' for byte in ssid.encode())
    content = (f'[connection]\nid=Wireless Wire {identity[:8]}\nuuid={identity}\ntype=wifi\nautoconnect=true\n'
               f'\n[wifi]\nmode=infrastructure\nssid={encoded}\n'
               f'\n[wifi-security]\nkey-mgmt=wpa-psk\npsk={psk}\n'
               '\n[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n')
    return identity, content


def execute(request):
    if not isinstance(request, dict):
        raise ValueError('JSON object required')
    action = request.get('action')
    if action == 'rotation':
        degrees = request.get('degrees')
        if type(degrees) is not int or degrees not in (0, 90, 180, 270):
            raise ValueError('Rotation must be 0, 90, 180 or 270')
        if not Path('/opt/wireless-wire-display/status_display.py').is_file():
            raise ValueError('Optional display component is not installed')
        atomic(ROTATION, '[Service]\nExecStart=\nExecStart=/usr/bin/python3 '
               '/opt/wireless-wire-display/status_display.py --preview '
               f'/run/wireless-wire-display/current.png --rotation {degrees}\n', 0o644)
        run('systemctl', 'daemon-reload')
        run('systemctl', 'restart', 'wireless-wire-display.service')
        return {'rotation': degrees}
    if action == 'restart':
        service = request.get('service')
        if service not in ('wireless-wire', 'wireless-wire-display'):
            raise ValueError('Unsupported service')
        run('systemctl', 'restart', service + '.service')
        return {'restarted': service}
    if action == 'client-config':
        token = Path('/etc/wireless-wire/token').read_text().strip()
        status = json.loads(run('tailscale', 'status', '--json'))
        ip = next(ip for ip in status['Self']['TailscaleIPs'] if ':' not in ip)
        return {'remote': ip + ':48200', 'token': token}
    if action == 'wifi-save':
        identity, content = wifi_profile(request.get('ssid'), request.get('password'))
        path = NETWORKS / ('wireless-wire-' + identity + '.nmconnection')
        old = path.read_text() if path.exists() else None
        atomic(path, content)
        try:
            run('nmcli', 'connection', 'load', str(path))
        except subprocess.SubprocessError:
            if old is None:
                path.unlink(missing_ok=True)
            else:
                atomic(path, old)
            raise
        return {'saved': True, 'uuid': identity, 'activated': False}
    if action == 'wifi-list':
        rows = []
        for line in run('nmcli', '-t', '-f', 'UUID,TYPE,NAME', 'connection', 'show').splitlines():
            fields = line.split(':', 2)
            if len(fields) == 3 and fields[1] == '802-11-wireless':
                name = run('nmcli', '--escape', 'no', '-g', '802-11-wireless.ssid',
                           'connection', 'show', 'uuid', fields[0]).strip()
                rows.append({'uuid': fields[0], 'name': name or fields[2]})
        return {'connections': rows}
    if action == 'wifi-connect':
        identity = str(uuid.UUID(request.get('uuid', '')))
        kind = run('nmcli', '-g', 'connection.type', 'connection', 'show', 'uuid', identity).strip()
        if kind != '802-11-wireless':
            raise ValueError('Only saved Wi-Fi connections can be activated')
        run('systemd-run', '--quiet', '--on-active=2s', '--collect',
            '/usr/bin/nmcli', '--wait', '20', 'connection', 'up', 'uuid', identity)
        return {'scheduled': True, 'uuid': identity}
    raise ValueError('Unsupported action')


def main():
    try:
        if os.geteuid() != 0:
            raise ValueError('Root helper requires sudo')
        data = sys.stdin.buffer.read(8193)
        if len(data) > 8192:
            raise ValueError('Request too large')
        result = execute(json.loads(data))
        print(json.dumps(result))
    except (ValueError, TypeError, KeyError, OSError, StopIteration, subprocess.SubprocessError):
        # Do not include commands, passwords or subprocess output in errors/logs.
        print(json.dumps({'error': 'Operation failed. Check the request and host configuration.'}))
        sys.exit(1)


if __name__ == '__main__':
    main()
