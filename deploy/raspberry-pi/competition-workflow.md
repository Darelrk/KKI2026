# Competition Raspberry Pi Workflow

## Persistent runtime

- Source yang dijalankan: `/home/pi/KKI2026`
- Satu venv backend production: `/opt/asv-dashboard/.venv`
- Environment secret: `/etc/asv-dashboard.env`
- Vision/model tetap berada pada service dan environment terpisah.

Installer tidak menyalin source ke `/opt` dan tidak membuat ulang venv yang sudah ada.
Dependency hanya diperbarui secara manual dengan:

```bash
sudo UPDATE_DEPS=1 APP_DIR=/opt/asv-dashboard \
  bash /home/pi/KKI2026/deploy/raspberry-pi/install-asv-dashboard.sh
```

## Start/stop stack

Stack tidak aktif otomatis setelah boot. Backend dan dua kamera dikendalikan bersama:

```bash
sudo systemctl start asv-stack.target
sudo systemctl status asv-stack.target
sudo systemctl stop asv-stack.target
```

`asv-vision.service` tidak termasuk stack dan harus diaktifkan manual setelah safety check.

## Testing perubahan

Dari checkout repository:

```bash
bash deploy/raspberry-pi/test-backend.sh
python3 -m compileall -q asv_dashboard_backend tests
```

Test script membuat venv sementara, menjalankan test telemetry, lalu menghapus venv tersebut.
Venv production tidak diubah saat testing.

Sebelum restart stack, periksa perubahan dengan `git status --short` dan simpan kandidat sebagai
commit lokal. Jangan memakai `git reset --hard`, `git clean`, stash otomatis, atau pull di atas
working tree yang dirty. Rollback kandidat commit dilakukan dengan `git revert`.

## Smoke test setelah start

```bash
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/api/status
curl -fsS http://127.0.0.1:8080/api/telemetry
```

Telemetry tetap read-only: tidak ada arm/disarm, perubahan mode, navigasi, RC override, atau
perintah MAVLink.
