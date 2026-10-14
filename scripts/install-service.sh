#!/usr/bin/env bash
# Installs and starts the Smart-Filter service as a systemd *user* service
# (no sudo required, runs only for your account, binds to 127.0.0.1).
#
# Usage:  bash scripts/install-service.sh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/smart-filter.service"

mkdir -p "$UNIT_DIR"
sed "s|@PROJECT_ROOT@|$PROJECT_ROOT|g" \
    "$PROJECT_ROOT/scripts/smart-filter.service.in" > "$UNIT"

systemctl --user daemon-reload
systemctl --user enable --now smart-filter.service

echo
echo "Installed unit: $UNIT"
echo
systemctl --user --no-pager status smart-filter.service || true
echo
echo "Smoke test: curl http://127.0.0.1:8765/health"
echo "Useful commands:"
echo "  systemctl --user status smart-filter.service"
echo "  systemctl --user restart smart-filter.service"
echo "  journalctl --user -u smart-filter.service -f"
