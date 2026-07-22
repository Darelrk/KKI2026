#!/usr/bin/env bash
# Shortcut untuk menjalankan Vision Pipeline (YOLO + MAVLink + Bridge Publisher)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODEL_PATH="${MODEL_PATH:-model/best.pt}"
BRIDGE_URL="${BRIDGE_URL:-http://127.0.0.1:8080}"
ENDPOINT="${ENDPOINT:-/dev/ttyACM0}"

echo "=========================================="
echo " Starting ASV Vision Pipeline"
echo " Model   : $MODEL_PATH"
echo " Bridge  : $BRIDGE_URL"
echo " Pixhawk : $ENDPOINT"
echo "=========================================="

python3 vision_test.py \
  --model "$MODEL_PATH" \
  --bridge-url "$BRIDGE_URL" \
  --endpoint "$ENDPOINT" \
  "$@"
