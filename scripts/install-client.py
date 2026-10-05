#!/usr/bin/env python3
"""Install the macOS localhost client as a per-user LaunchAgent."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

LABEL = 'org.wireless-wire.client'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def enroll(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.ts.net')
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Use the Pi HTTPS .ts.net origin without a path')
    request = Request(url.rstrip('/') + '/api/v1/client-config', data=b'{}',
                      headers={'Content-Type': 'application/json', 'X-Wireless-Wire-Request': '1'})
    with build_opener(NoRedirect()).open(request, timeout=30) as response:
        data = response.read(8193)
    if len(data) > 8192:
        raise ValueError('Invalid client configuration')
    result = json.loads(data)
    token = result['token']
    if not isinstance(token, str) or not 32 <= len(token) <= 256 or not token.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError('Invalid bridge token')
    return result['remote'], token


def replace_private(path, data):
    """Replace only this file, without following an existing symlink."""
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.install-')
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    if sys.platform != 'darwin' or sys.version_info < (3, 11):
        raise SystemExit('Run with Python 3.11+ on the client Mac.')
    root = Path(__file__).resolve().parents[1]
    default = root / 'wireless-wire.pyz'
    if not default.exists():
        default = root / 'dist/wireless-wire.pyz'
    parser = argparse.ArgumentParser()
    parser.add_argument('--remote', help='Tailscale IP:48200')
    parser.add_argument('--token-file', type=Path)
    parser.add_argument('--api-url', help='Pi HTTPS .ts.net URL; enroll without SSH or copying a token')
    parser.add_argument('--app', type=Path, default=default)
    args = parser.parse_args()
    app = args.app.resolve(strict=True)
    sys.path.insert(0, str(app))
    from wireless_wire.transport import endpoint, read_token
    if args.api_url:
        if args.remote or args.token_file:
            parser.error('Use --api-url alone, or --remote with --token-file')
        try:
            args.remote, token = enroll(args.api_url)
        except Exception:
            raise SystemExit('Enrollment failed. Check the Pi URL and your Tailscale account access.')
    else:
        if not args.remote or not args.token_file:
            parser.error('Supply --api-url, or both --remote and --token-file')
        token = read_token(args.token_file.expanduser())
    endpoint(args.remote)
    domain = 'gui/' + str(os.getuid())
    installed = subprocess.run(['launchctl', 'print', domain + '/' + LABEL],
                               capture_output=True).returncode == 0
    if not installed:
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', 27015))
            except OSError:
                raise SystemExit('Port 27015 is already occupied. Stop the existing bridge first.')
    os.umask(0o077)
    state = Path.home() / 'Library/Application Support/wireless-wire'
    if state.is_symlink():
        raise SystemExit('Refusing a symlink at the managed state directory.')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    target = state / 'wireless-wire.pyz'
    replace_private(target, app.read_bytes())
    private_token = state / 'token'
    if private_token.is_symlink():
        raise SystemExit('Refusing a symlink at the managed token path.')
    replace_private(private_token, (token + '\n').encode('ascii'))
    job = {'Label': LABEL, 'ProgramArguments': [sys.executable, str(target), 'bridge',
           '--remote', args.remote, '--token-file', str(private_token)],
           'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
           'StandardOutPath': str(state / 'client.log'),
           'StandardErrorPath': str(state / 'client-error.log')}
    path = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    path.parent.mkdir(parents=True, exist_ok=True)
    replace_private(path, plistlib.dumps(job))
    if installed:
        subprocess.run(['launchctl', 'bootout', domain + '/' + LABEL], check=True)
    # bootout can return before launchd releases the previous job registration.
    for attempt in range(10):
        started = subprocess.run(['launchctl', 'bootstrap', domain, str(path)], capture_output=True)
        if started.returncode == 0:
            break
        if attempt == 9:
            raise SystemExit('LaunchAgent could not start. Configuration is saved; inspect launchctl and client-error.log.')
        time.sleep(0.5)
    for attempt in range(20):
        try:
            with socket.create_connection(('127.0.0.1', 27015), timeout=0.5):
                break
        except OSError:
            if attempt == 19:
                raise SystemExit('LaunchAgent loaded but the client port is unavailable; inspect client-error.log.')
            time.sleep(0.5)
    print('Installed ' + LABEL + '. Run doctor to verify the connection.')


if __name__ == '__main__':
    main()
