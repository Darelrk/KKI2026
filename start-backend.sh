#!/usr/bin/env bash
# Shortcut untuk menjalankan FastAPI ASV Dashboard Backend Bridge
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"

echo "=========================================="
echo " Starting ASV Dashboard Backend Bridge"
echo " Host: http://${HOST}:${PORT}"
echo "=========================================="

exec python3 -m uvicorn asv_dashboard_backend.main:app --host "$HOST" --port "$PORT" "$@"
