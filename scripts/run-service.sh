#!/usr/bin/env bash
# Runs the Smart-Filter service in the foreground (for development / testing).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec python3 -m smart_filter.service
