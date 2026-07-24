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

`ASV_PIXHAWK_ENABLED=true` membaca telemetry MAVLink secara otomatis tanpa perlu membuka
QGroundControl. Backend secara otomatis:
1. Mendeteksi `/dev/serial/by-id/*ArduPilot*` atau `/dev/ttyACM0`.
2. Mengirim `request_data_stream_send` (`MAV_DATA_STREAM_ALL`) agar Pixhawk terus mengirimkan
   data GPS (`GLOBAL_POSITION_INT`), kompas (`VFR_HUD`), dan heartbeat.
3. Melakukan reconnect otomatis jika kabel USB Pixhawk dicopot/dipasang kembali atau koneksi terputus,
   tanpa mengganggu fungsi kamera dan backend.

Transmitter RC tetap langsung terhubung ke receiver/Pixhawk untuk mengendalikan servo dan throttle.
Backend tidak pernah mengirimkan perintah arming, disarm, mode change, atau RC override.

## Dashboard live direct via tunnel

Set the Vercel environment to:

```text
VITE_ASV_DATA_MODE=direct
VITE_ASV_BRIDGE_URL=https://monitor-kapal-pora-pora.web.id
VITE_ASV_SURFACE_STREAM_URL=https://monitor-kapal-pora-pora.web.id/stream/atas
VITE_ASV_UNDERWATER_STREAM_URL=https://monitor-kapal-pora-pora.web.id/stream/bawah
VITE_ASV_VISION_WS_URL=wss://monitor-kapal-pora-pora.web.id
```

Set `ASV_CORS_ORIGINS` in `/etc/asv-dashboard.env` to the exact Vercel
origin plus `http://localhost:3000` when local testing is needed. The
browser reads `/api/status` and `/api/telemetry` directly through the tunnel,
opens the raw camera URLs directly, and receives vision metadata from
`/ws/vision/default`. Supabase is not part of this live path; leave both
server-side Supabase variables empty unless rollback publishing is explicitly
needed.

Verify from a browser origin and from the Pi:

```bash
curl -fsS http://127.0.0.1:8080/api/status
curl -fsS http://127.0.0.1:8080/api/telemetry
curl -fsS https://monitor-kapal-pora-pora.web.id/api/status
curl -fsS https://monitor-kapal-pora-pora.web.id/api/telemetry
```

Keep exactly one process attached to the Pixhawk serial endpoint. Mission
Planner and QGroundControl must not open the same `/dev/ttyACM0` endpoint while
`ASV_PIXHAWK_ENABLED=true`.
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
