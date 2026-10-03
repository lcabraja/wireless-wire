#!/usr/bin/env bash
# Linux host for the physically attached iPhone. Existing pairing stays in usbmuxd.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
listen=""
app="$root/dist/wireless-wire.pyz"
[[ -f "$root/wireless-wire.pyz" ]] && app="$root/wireless-wire.pyz"
skip_deps=0
while (($#)); do
  case "$1" in
    --listen) listen="${2:?Provide the host Tailscale IP}"; shift 2 ;;
    --app) app="${2:?Provide the built zipapp}"; shift 2 ;;
    --skip-deps) skip_deps=1; shift ;;
    *) echo 'Usage: sudo scripts/install-server.sh --listen TAILSCALE_IP [--app FILE] [--skip-deps]' >&2; exit 2 ;;
  esac
done
[[ "$(uname -s)" == Linux && $EUID == 0 ]] || { echo 'Run as root on the Linux USB host.' >&2; exit 1; }
[[ -f "$app" && -n "$listen" ]] || { echo 'Build the app and provide --listen.' >&2; exit 2; }
python3 - "$app" "$listen" <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit('Python 3.11 or newer is required.')
sys.path.insert(0, sys.argv[1])
from wireless_wire.transport import allowed_address
allowed_address(sys.argv[2])
PY
if (( ! skip_deps )); then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y python3 usbmuxd libimobiledevice-utils
fi
if ! id wireless-wire >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/wireless-wire --shell /usr/sbin/nologin wireless-wire
fi
install -d -m 0755 /opt/wireless-wire
install -m 0644 "$app" /opt/wireless-wire/wireless-wire.pyz
install -d -m 0700 -o wireless-wire -g wireless-wire /etc/wireless-wire
if [[ ! -e /etc/wireless-wire/token ]]; then
  python3 /opt/wireless-wire/wireless-wire.pyz init --token-file /etc/wireless-wire/token
fi
chown wireless-wire:wireless-wire /etc/wireless-wire/token
python3 - /opt/wireless-wire/wireless-wire.pyz /etc/wireless-wire/token <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from wireless_wire.transport import read_token
read_token(Path(sys.argv[2]))
PY
cat > /etc/systemd/system/wireless-wire.service <<EOF
[Unit]
Description=Wireless Wire iPhone service bridge
After=network-online.target tailscaled.service usbmuxd.service
Wants=network-online.target usbmuxd.service

[Service]
Type=simple
User=wireless-wire
Group=wireless-wire
ExecStart=/usr/bin/python3 /opt/wireless-wire/wireless-wire.pyz serve --listen $listen --token-file /etc/wireless-wire/token
Restart=on-failure
RestartSec=3
TimeoutStopSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now wireless-wire.service
systemctl restart wireless-wire.service
systemctl is-active --quiet wireless-wire.service
echo 'Installed wireless-wire.service. Transfer /etc/wireless-wire/token privately to the client.'
