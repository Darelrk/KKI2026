#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR="$(mktemp -d /tmp/asv-dashboard-test.XXXXXX)"

cleanup() {
  rm -rf -- "$TEST_DIR"
}
trap cleanup EXIT

python3 -m venv "$TEST_DIR/.venv"
"$TEST_DIR/.venv/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-cache-dir \
  -r "$REPO_DIR/requirements-dashboard.txt" \
  pytest \
  httpx
"$TEST_DIR/.venv/bin/python" -m pytest -q \
  "$REPO_DIR/tests/test_manual_rc.py" \
  "$REPO_DIR/tests/test_vision_route.py" \
  "$REPO_DIR/tests/test_vision_capture.py" \
  "$REPO_DIR/tests/test_vision_publisher.py" \
  "$REPO_DIR/tests/test_telemetry.py" \
  "$REPO_DIR/tests/test_dashboard_backend.py"
