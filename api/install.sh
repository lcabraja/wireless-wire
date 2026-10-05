#!/usr/bin/env bash
set -euo pipefail
umask 022
root="$(cd "$(dirname "$0")/.." && pwd)"
[[ $EUID == 0 && "$(uname -s)" == Linux ]] || { echo 'Run as root on the Linux USB host.' >&2; exit 1; }
[[ -f "$root/dist/wireless-wire.pyz" ]] || { echo 'Build the zipapp first.' >&2; exit 1; }
id wireless-wire >/dev/null
command -v tailscale >/dev/null
command -v nmcli >/dev/null
command -v visudo >/dev/null
python3 - <<'PY'
import json, subprocess
config = json.loads(subprocess.check_output(['tailscale', 'serve', 'status', '--json']) or '{}')
tcp = config.get('TCP', {})
if '80' in tcp and tcp['80'] != {'TCPForward': '127.0.0.1:8081'}:
    raise SystemExit('Tailscale port 80 already serves another application; preserve it and choose a dedicated host.')
if '443' in tcp:
    proxies = [entry.get('Handlers', {}).get('/', {}).get('Proxy') for host, entry in config.get('Web', {}).items() if host.endswith(':443')]
    if tcp['443'] != {'HTTPS': True} or not proxies or any(p != 'http://127.0.0.1:8080' for p in proxies):
        raise SystemExit('Tailscale port 443 already serves another application; refusing to replace it.')
PY
if ! id wireless-wire-api >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin wireless-wire-api
fi
install -d -m 0755 /opt/wireless-wire-api/static /usr/local/libexec
install -m 0644 "$root/api/server.py" /opt/wireless-wire-api/server.py
install -m 0644 "$root/api/static/"* /opt/wireless-wire-api/static/
install -m 0755 "$root/api/admin.py" /usr/local/libexec/wireless-wire-admin
install -m 0644 "$root/dist/wireless-wire.pyz" /opt/wireless-wire/wireless-wire.pyz
install -d -m 0750 -o root -g wireless-wire-api /etc/wireless-wire-api
python3 - <<'PY'
import json, os, re, subprocess
from pathlib import Path
state = json.loads(subprocess.check_output(['tailscale', 'status', '--json']))
hostname = state['Self']['DNSName'].rstrip('.')
owner = state.get('User', {}).get(str(state['Self'].get('UserID')), {}).get('LoginName')
if not re.fullmatch(r'[a-z0-9-]+\.[a-z0-9-]+\.ts\.net', hostname):
    raise SystemExit('A Tailscale DNS hostname is required.')
path = Path('/etc/wireless-wire-api/config.json')
config = json.loads(path.read_text()) if path.exists() else {'allowed_logins': [owner] if owner else []}
if not config['allowed_logins']:
    raise SystemExit('Tagged server: configure allowed_logins in /etc/wireless-wire-api/config.json first.')
config['hostname'] = hostname
path.write_text(json.dumps(config) + '\n')
os.chmod(path, 0o640)
PY
chown root:wireless-wire-api /etc/wireless-wire-api/config.json
policy="$(mktemp)"
trap 'rm -f "$policy"' EXIT
echo 'wireless-wire-api ALL=(root) NOPASSWD: /usr/local/libexec/wireless-wire-admin ""' > "$policy"
visudo -cf "$policy"
install -m 0440 "$policy" /etc/sudoers.d/wireless-wire-api
install -d -m 0755 /etc/systemd/system/wireless-wire.service.d /etc/systemd/system/wireless-wire-display.service.d
cat > /etc/systemd/system/wireless-wire.service.d/management-status.conf <<'EOF'
[Service]
Environment=WIRELESS_WIRE_STATUS_FILE=/run/wireless-wire-status/status.json
RuntimeDirectory=wireless-wire-status
RuntimeDirectoryMode=0750
EOF
cat > /etc/systemd/system/wireless-wire-api.service <<'EOF'
[Unit]
Description=Wireless Wire private management API
After=network-online.target tailscaled.service wireless-wire.service
Wants=network-online.target wireless-wire.service

[Service]
User=wireless-wire-api
SupplementaryGroups=wireless-wire
ExecStart=/usr/bin/python3 /opt/wireless-wire-api/server.py
Restart=on-failure
RestartSec=3
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/etc/NetworkManager/system-connections /etc/systemd/system/wireless-wire-display.service.d
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl restart wireless-wire.service
systemctl enable wireless-wire-api.service
systemctl restart wireless-wire-api.service
tailscale serve --bg --yes --https=443 http://127.0.0.1:8080
# Raw TCP on 80 accepts an IP Host header too; Serve HTTP routing requires DNS.
tailscale serve --bg --yes --tcp=80 tcp://127.0.0.1:8081
systemctl is-active wireless-wire-api.service
