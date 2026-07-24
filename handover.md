# Handover Raspberry Pi — Manual RC + Model Monitoring

## Branch dan baseline

- Repository: `https://github.com/Darelrk/KKI2026.git`
- Branch: `feat/manual-rc-dashboard-frontend`
- Baseline `main` saat handover: `1416008`
- Jalur `--manual-rc` menjalankan YOLO dan publisher saja.

## Sinkronisasi di Pi

```bash
cd /home/pi/KKI2026
git status --short
# Jika working tree bersih:
git fetch origin
git switch feat/manual-rc-dashboard-frontend
git pull --ff-only origin feat/manual-rc-dashboard-frontend
```

Jangan memakai `reset --hard`, `clean`, stash otomatis, atau pull di atas
working tree dirty. Laporkan perubahan vision lokal jika masih ada.

## Backend bridge

```bash
sudo systemctl start asv-stack.target
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/api/status
curl -fsS http://127.0.0.1:8080/api/telemetry
```

`ASV_PIXHAWK_ENABLED=false` adalah pilihan aman jika Pixhawk sedang digunakan
oleh transmitter/QGroundControl/Mission Planner melalui port yang sama.
Aktifkan hanya jika jalur telemetry terpisah dan tetap read-only.

## Menjalankan model manual RC

```bash
cd /home/pi/KKI2026
python3 vision_test.py \
  --manual-rc \
  --model /home/pi/KKI2026/model/best.pt \
  --camera 0 \
  --bridge-url http://127.0.0.1:8080 \
  --bridge-asv-id default
```

Konfigurasikan `ASV_STREAM_URL` di `/etc/asv-dashboard.env` jika dashboard
memerlukan URL raw surface. Jangan tambahkan `--endpoint` untuk mode manual RC;
mode ini tidak boleh membuka Pixhawk. Transmitter RC tetap satu-satunya sumber
steering/throttle.

## Safety contract

Mode `--manual-rc` tidak boleh:

- mengimpor atau membuka koneksi serial/TCP/UDP Pixhawk;
- menjalankan `ARMING_CHECK`;
- mengirim `MAV_CMD_COMPONENT_ARM_DISARM`;
- mengirim `RC_CHANNELS_OVERRIDE`;
- mengubah mode, throttle, atau steering kapal.

Mode ini tetap boleh menjalankan kamera, YOLO, overlay lokal, log JSONL,
`POST /api/vision/metadata`, dan `POST /api/frame/surface`.

## Verifikasi tanpa hardware

```bash
bash deploy/raspberry-pi/test-backend.sh
python3 -m compileall -q vision_test.py vision_route.py asv_dashboard_backend tests
python3 vision_test.py --help
```

Expected: flag `--manual-rc` terlihat; semua test pass; compileall tidak
mengeluarkan error; tidak diperlukan Pixhawk, kamera, atau model untuk command
verifikasi di atas.

## Laporan agent Raspi

Laporkan:

1. commit sebelum dan sesudah pull;
2. `git status --short`;
3. hasil test dan compileall;
4. response `/healthz`, `/api/status`, `/api/telemetry`;
5. status `asv-stack.target`;
6. apakah model publish metadata/frame;
7. masalah hardware tanpa mencetak secret.
