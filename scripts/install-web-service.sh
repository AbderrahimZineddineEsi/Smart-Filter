#!/usr/bin/env bash
# Installs and starts the Smart-Filter web console as a systemd *user* service
# (no sudo required, binds to 127.0.0.1:8000).
#
# Usage:  bash scripts/install-web-service.sh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/smart-filter-web.service"

mkdir -p "$UNIT_DIR"
sed "s|@PROJECT_ROOT@|$PROJECT_ROOT|g" \
    "$PROJECT_ROOT/scripts/smart-filter-web.service.in" > "$UNIT"

systemctl --user daemon-reload
systemctl --user enable --now smart-filter-web.service

echo
echo "Installed unit: $UNIT"
echo
systemctl --user --no-pager status smart-filter-web.service || true
echo
echo "Open: http://127.0.0.1:8000"
echo "Useful commands:"
echo "  systemctl --user status smart-filter-web.service"
echo "  systemctl --user restart smart-filter-web.service"
echo "  journalctl --user -u smart-filter-web.service -f"
