#!/usr/bin/env bash
# Shortcut untuk menjalankan Backend & Vision Pipeline sekaligus
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo " Starting ASV Backend & Vision Pipeline"
echo "=========================================="

python3 -m uvicorn asv_dashboard_backend.main:app --host 0.0.0.0 --port 8080 &
BACKEND_PID=$!

cleanup() {
  echo "Stopping processes..."
  kill "$BACKEND_PID" 2>/dev/null || true
  exit 0
}

trap cleanup INT TERM EXIT

sleep 2

python3 vision_test.py --model model/best.pt "$@"
