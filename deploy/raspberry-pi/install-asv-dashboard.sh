#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/asv-dashboard}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

sudo mkdir -p "$APP_DIR"
sudo cp -R "$REPO_DIR/asv_dashboard_backend" "$APP_DIR/"
sudo cp "$REPO_DIR/requirements-dashboard.txt" "$APP_DIR/"
sudo python3 -m venv "$APP_DIR/.venv"
sudo "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
sudo "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements-dashboard.txt"
sudo chown -R pi:pi "$APP_DIR"

sudo install -m 0644 "$REPO_DIR/deploy/raspberry-pi/asv-dashboard.service" \
  /etc/systemd/system/asv-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now asv-dashboard.service
sudo systemctl --no-pager --full status asv-dashboard.service
