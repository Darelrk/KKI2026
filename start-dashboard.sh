#!/usr/bin/env bash
# Shortcut untuk menjalankan Frontend Dashboard
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo " Starting Frontend Dashboard"
echo "=========================================="

exec npm run dev --workspace dashboard "$@"
