#!/usr/bin/env python3
"""Private management API behind Tailscale Serve's verified identity headers."""
import argparse
from email.header import decode_header, make_header
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
from urllib.parse import urlsplit

SOURCE = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SOURCE if SOURCE.is_dir() else Path('/opt/wireless-wire/wireless-wire.pyz')))
from wireless_wire.host_status import collect, tailnet_status, command_output

STATIC = Path(__file__).parent / 'static'
ROUTES = {'/api/v1/display/rotation': 'rotation', '/api/v1/service/restart': 'restart',
          '/api/v1/wifi': 'wifi-save', '/api/v1/wifi/connect': 'wifi-connect',
          '/api/v1/client-config': 'client-config'}


def privileged(action, data):
    process = subprocess.run(['sudo', '-n', '/usr/local/libexec/wireless-wire-admin'],
                             input=json.dumps(dict(data, action=action)), text=True,
                             capture_output=True, timeout=35)
    if process.returncode:
        raise ValueError('Operation failed. Check the request and host configuration.')
    return json.loads(process.stdout)


def status():
    state = collect(Path('/run/wireless-wire-status/status.json'), *tailnet_status(),
                    excluded_usb_ids=frozenset({('1a86', '5722')}))
    state['services'] = {name: (command_output(['systemctl', 'is-active', name]) or 'inactive').strip()
                         for name in ('wireless-wire', 'wireless-wire-display')}
    command = command_output(['systemctl', 'show', 'wireless-wire-display', '-p', 'ExecStart', '--value']) or ''
    rotation = re.search(r'--rotation\s+(0|90|180|270)\b', command)
    state['rotation'] = int(rotation[1]) if rotation else 90
    return state


def wifi_connections():
    return privileged('wifi-list', {})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'WirelessWire'

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_):
        pass  # No URLs, identities, request bodies, credentials or device identifiers in access logs.

    def send(self, code, value, content_type='application/json', location=None):
        body = json.dumps(value).encode() if content_type == 'application/json' else value
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if location:
            self.send_header('Location', location)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def authorized(self):
        values = self.headers.get_all('Tailscale-User-Login', [])
        if len(values) != 1:
            return False
        try:
            identity = str(make_header(decode_header(values[0])))
        except (LookupError, ValueError):
            return False
        return ipaddress.ip_address(self.client_address[0]).is_loopback and identity in self.server.config['allowed_logins']

    def route(self):
        canonical = 'https://' + self.server.config['hostname']
        if self.server.redirect:
            path = urlsplit(self.path).path
            # A fixed authority, even for //evil.example and absolute-form requests.
            self.send(308, {'redirect': canonical + path}, location=canonical + path)
            return
        if self.headers.get('Host') not in (self.server.config['hostname'], self.server.config['hostname'] + ':443'):
            self.send(421, {'error': 'Use the configured HTTPS hostname'})
            return
        if not self.authorized():
            self.send(403, {'error': 'Access requires an allowed Tailscale user device'})
            return
        path = urlsplit(self.path).path
        if self.command in ('GET', 'HEAD'):
            if path == '/api/v1/status':
                self.send(200, status())
            elif path == '/api/v1/wifi':
                self.send(200, wifi_connections())
            elif path in ('/', '/app.js', '/style.css'):
                name, kind = {'/': ('index.html', 'text/html; charset=utf-8'),
                              '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                              '/style.css': ('style.css', 'text/css; charset=utf-8')}[path]
                self.send(200, (STATIC / name).read_bytes(), kind)
            else:
                self.send(404, {'error': 'Not found'})
            return
        if self.command != 'POST' or path not in ROUTES:
            self.send(404, {'error': 'Not found'})
            return
        if (self.headers.get('X-Wireless-Wire-Request') != '1'
                or self.headers.get('Origin', canonical) != canonical
                or self.headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none')):
            self.send(403, {'error': 'Same-origin JSON request required'})
            return
        if (self.headers.get_content_type() != 'application/json' or self.headers.get('Transfer-Encoding')
                or len(self.headers.get_all('Content-Length', [])) != 1):
            self.send(400, {'error': 'JSON with Content-Length required'})
            return
        try:
            length = int(self.headers['Content-Length'])
            if not 0 < length <= 8192:
                raise ValueError()
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            self.send(400, {'error': 'Invalid JSON request'})
            return
        if not self.server.mutation_lock.acquire(blocking=False):
            self.send(409, {'error': 'Another operation is in progress'})
            return
        try:
            self.send(200, privileged(ROUTES[path], data))
        except (ValueError, subprocess.SubprocessError):
            self.send(400, {'error': 'Operation failed. Check the request and host configuration.'})
        finally:
            self.server.mutation_lock.release()

    def dispatch(self):
        try:
            self.route()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            self.send(500, {'error': 'Host operation unavailable'})

    do_GET = do_HEAD = do_POST = dispatch


def make_server(config, port, redirect=False):
    server = Server(('127.0.0.1', port), Handler)
    server.config, server.redirect = config, redirect
    server.mutation_lock = threading.Lock()
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=Path('/etc/wireless-wire-api/config.json'))
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if not re.fullmatch(r'[a-z0-9-]+\.[a-z0-9-]+\.ts\.net', config['hostname']) or not config['allowed_logins']:
        raise SystemExit('A canonical ts.net hostname and allowed_logins are required')
    redirect = make_server(config, 8081, True)
    threading.Thread(target=redirect.serve_forever, daemon=True).start()
    make_server(config, 8080).serve_forever()


if __name__ == '__main__':
    main()
