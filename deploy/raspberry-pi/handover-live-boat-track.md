# Handover: Live Boat Track Dashboard

Tanggal: 2026-07-20  
Repository: `https://github.com/Darelk/KKI2026.git`  
Target branch: `main`

## Tujuan

Dashboard web sekarang menampilkan jalur GPS boat yang diterima dari `telemetry.track`, posisi boat terbaru, dan arah berdasarkan `heading_deg`. Marker tidak lagi memakai koordinat venue, buoy, docking ball, atau rute lomba hard-coded.

## Kontrak backend yang harus dipertahankan

Backend Raspberry Pi sudah menyediakan kontrak read-only berikut dari `asv_dashboard_backend/telemetry.py`:

```json
{
  "connected": true,
  "position": {
    "latitude": -6.1224,
    "longitude": 106.8226,
    "captured_at": "2026-07-20T09:32:00+00:00"
  },
  "heading_deg": 144.0,
  "speed_mps": 0.6,
  "captured_at": "2026-07-20T09:32:00+00:00",
  "heartbeat_at": "2026-07-20T09:31:59+00:00",
  "track": [
    {
      "latitude": -6.1234,
      "longitude": 106.821,
      "captured_at": "2026-07-20T09:30:00+00:00"
    }
  ]
}
```

- `position`: GPS position terbaru, atau `null` jika belum ada fix.
- `heading_deg`: arah 0–360 derajat, atau `null`.
- `speed_mps`: kecepatan non-negatif dalam m/s, atau `null`.
- `track`: urutan titik GPS aktif yang dibatasi oleh `ASV_PIXHAWK_TRACK_MAX_POINTS`.
- `track` hanya in-memory untuk sesi backend aktif; bukan histori perjalanan permanen.
- Jangan menambah RC override, arm/disarm, perubahan mode, atau perintah MAVLink untuk pekerjaan ini.

## Langkah Codex di Raspberry Pi

Jalankan dari checkout repository di Pi:

```bash
cd /home/pi/KKI2026
git status --short
git pull --ff-only origin main
```

Jika checkout memiliki perubahan lokal, jangan reset atau menghapusnya. Laporkan konflik sebelum melakukan perubahan.

## Verifikasi backend

```bash
cd /home/pi/KKI2026
python3 -m pytest -q tests/test_telemetry.py
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/api/status
curl -fsS http://127.0.0.1:8080/api/telemetry
sudo systemctl --no-pager status asv-dashboard.service
```

Expected:

- `healthz` mengembalikan `{"ok": true}`.
- `/api/telemetry` memiliki key `connected`, `position`, `heading_deg`, `speed_mps`, `captured_at`, `heartbeat_at`, dan `track`.
- Sebelum GPS fix, `position` dan `track` boleh `null`/`[]`; jangan membuat koordinat palsu.
- Setelah GPS fix, `position` terisi dan `track` bertambah dengan titik valid.
- Service tetap read-only terhadap Pixhawk dan tidak restart-loop.

## Catatan deployment frontend

Frontend berada di `dashboard/` dan dideploy dari branch `main` oleh Vercel. Perubahan frontend tidak perlu dipasang sebagai service di Raspberry Pi. Pi hanya perlu menjaga publisher/backend telemetry tetap mengirim kontrak di atas.

Jika URL raw camera sudah dikonfigurasi, jangan menggantinya dengan placeholder. Jangan mencetak secret Supabase atau service-role key saat laporan.

## Prompt copy-paste untuk Codex Raspberry Pi

```text
Kamu bekerja di /home/pi/KKI2026. Sinkronkan repository dan verifikasi backend ASV tanpa mengubah kontrol keselamatan Pixhawk.

1. Jalankan `git status --short`. Jika ada perubahan lokal, jangan reset, stash, checkout paksa, atau menghapusnya; laporkan dan berhenti.
2. Jika bersih, jalankan `git pull --ff-only origin main`.
3. Baca `deploy/raspberry-pi/handover-live-boat-track.md`.
4. Jalankan:
   `python3 -m pytest -q tests/test_telemetry.py`
   `curl -fsS http://127.0.0.1:8080/healthz`
   `curl -fsS http://127.0.0.1:8080/api/status`
   `curl -fsS http://127.0.0.1:8080/api/telemetry`
   `sudo systemctl --no-pager status asv-dashboard.service`
5. Pastikan `/api/telemetry` mempertahankan `connected`, `position`, `heading_deg`, `speed_mps`, `captured_at`, `heartbeat_at`, dan `track`.
6. Jangan mengirim MAVLink command, RC override, arm/disarm, perubahan mode, koordinat palsu, atau secret ke output.
7. Laporkan commit sebelum/sesudah pull, status working tree, hasil test, response endpoint, status systemd, dan masalah yang ditemukan.
```
