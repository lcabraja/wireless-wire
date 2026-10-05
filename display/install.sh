#!/usr/bin/env bash
# Run from the source checkout on the Linux USB host, after building the zipapp.
set -euo pipefail
umask 022
root="$(cd "$(dirname "$0")/.." && pwd)"
[[ $EUID == 0 && "$(uname -s)" == Linux ]] || { echo 'Run as root on Linux.' >&2; exit 1; }
[[ -f "$root/dist/wireless-wire.pyz" ]] || { echo 'Run python3 scripts/build.py first.' >&2; exit 1; }
systemctl cat wireless-wire.service >/dev/null
id wireless-wire >/dev/null
export DEBIAN_FRONTEND=noninteractive
apt-get install -y python3-pil fonts-dejavu-core
if ! id wireless-wire-display >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin wireless-wire-display
fi
install -d -m 0755 /opt/wireless-wire-display
install -m 0644 "$root/display/status_display.py" "$root/display/data.py" "$root/display/common.py" /opt/wireless-wire-display/
while IFS= read -r source; do
  target="/opt/wireless-wire-display/${source#"$root/display/"}"
  install -D -m 0644 "$source" "$target"
done < <(find "$root/display/draw" "$root/display/driver" -type f -name '*.py')
install -m 0755 "$root/display/control.py" /usr/local/bin/wireless-wire-display
if [[ ! -f /opt/wireless-wire/wireless-wire.before-display.pyz ]]; then
  cp -p /opt/wireless-wire/wireless-wire.pyz /opt/wireless-wire/wireless-wire.before-display.pyz
fi
install -m 0644 "$root/dist/wireless-wire.pyz" /opt/wireless-wire/wireless-wire.pyz
install -d -m 0755 /etc/systemd/system/wireless-wire.service.d
cat > /etc/systemd/system/wireless-wire.service.d/display-status.conf <<'EOF'
[Service]
Environment=WIRELESS_WIRE_STATUS_FILE=/run/wireless-wire-status/status.json
RuntimeDirectory=wireless-wire-status
RuntimeDirectoryMode=0750
EOF
cat > /etc/udev/rules.d/70-wireless-wire-display.rules <<'EOF'
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="5722", GROUP="dialout", MODE="0660", ENV{ID_MM_DEVICE_IGNORE}="1"
EOF
cat > /etc/systemd/system/wireless-wire-display.service <<'EOF'
[Unit]
Description=Wireless Wire TURZX USB status display
After=wireless-wire.service NetworkManager.service tailscaled.service
Wants=wireless-wire.service

[Service]
Type=simple
User=wireless-wire-display
SupplementaryGroups=dialout wireless-wire
ExecStart=/usr/bin/python3 /opt/wireless-wire-display/status_display.py --preview /run/wireless-wire-display/current.png
Restart=on-failure
RestartSec=5
RuntimeDirectory=wireless-wire-display
RuntimeDirectoryMode=0750
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
udevadm control --reload-rules
udevadm trigger --subsystem-match=tty
systemctl daemon-reload
systemctl restart wireless-wire.service
systemctl enable wireless-wire-display.service
systemctl restart wireless-wire-display.service
systemctl is-active wireless-wire.service wireless-wire-display.service
