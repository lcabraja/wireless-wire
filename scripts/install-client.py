#!/usr/bin/env python3
"""Install the macOS localhost client as a per-user LaunchAgent."""
import argparse
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import tempfile

LABEL = 'org.wireless-wire.client'


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
    parser.add_argument('--remote', required=True, help='Tailscale IP:48200')
    parser.add_argument('--token-file', required=True, type=Path)
    parser.add_argument('--app', type=Path, default=default)
    args = parser.parse_args()
    app = args.app.resolve(strict=True)
    sys.path.insert(0, str(app))
    from wireless_wire.transport import endpoint, read_token
    endpoint(args.remote)
    token = read_token(args.token_file.expanduser())
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
    subprocess.run(['launchctl', 'bootstrap', domain, str(path)], check=True)
    print('Installed ' + LABEL + '. Run doctor to verify the connection.')


if __name__ == '__main__':
    main()
