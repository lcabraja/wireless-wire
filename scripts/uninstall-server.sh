#!/usr/bin/env bash
set -euo pipefail
[[ "$(uname -s)" == Linux && $EUID == 0 ]] || { echo 'Run as root on the Linux USB host.' >&2; exit 1; }
systemctl disable --now wireless-wire.service
rm -f /etc/systemd/system/wireless-wire.service
systemctl daemon-reload
echo 'Service removed. App, token and iPhone pairing records were preserved.'
