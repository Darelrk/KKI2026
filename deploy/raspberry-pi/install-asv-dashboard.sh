#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/asv-dashboard}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

sudo mkdir -p "$APP_DIR"
VENV_CREATED=0
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  sudo python3 -m venv "$APP_DIR/.venv"
  VENV_CREATED=1
fi
sudo install -o pi -g pi -m 0644 \
  "$REPO_DIR/requirements-dashboard.txt" \
  "$APP_DIR/requirements-dashboard.txt"

if [[ "$VENV_CREATED" -eq 1 || "${UPDATE_DEPS:-0}" == "1" ]]; then
  sudo "$APP_DIR/.venv/bin/python" -m pip install \
    --disable-pip-version-check \
    -r "$APP_DIR/requirements-dashboard.txt"
fi

sudo chown -R pi:pi "$APP_DIR"

sudo install -m 0644 "$REPO_DIR/deploy/raspberry-pi/asv-dashboard.service" \
  /etc/systemd/system/asv-dashboard.service
sudo install -m 0644 "$REPO_DIR/deploy/raspberry-pi/asv-stack.target" \
  /etc/systemd/system/asv-stack.target
sudo install -d -m 0755 /etc/systemd/system/asv-stream.service.d
sudo install -m 0644 "$REPO_DIR/deploy/raspberry-pi/asv-stream-stack.conf" \
  /etc/systemd/system/asv-stream.service.d/10-asv-stack.conf
sudo systemctl daemon-reload
sudo systemctl disable asv-dashboard.service asv-stream.service asv-stack.target asv-vision.service \
  >/dev/null 2>&1 || true
