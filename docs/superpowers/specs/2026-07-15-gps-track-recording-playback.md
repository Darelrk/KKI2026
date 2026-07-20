# GPS Track Recording and Playback

**Tanggal:** 2026-07-15  
**Status:** Desain disetujui; belum diimplementasikan.

## Tujuan

Menyediakan metode navigasi utama berbasis GPS track yang direkam oleh operator manual, lalu diputar ulang secara otomatis oleh kapal pada percobaan berikutnya. Metode ini mencakup blind corner, area survey, dan docking tanpa bergantung pada kamera sebagai sumber navigasi utama.

## Alur utama

```
Remote MANUAL
    ↓
Rekam GPS track + waypoint
    ↓
gps_track_raw.jsonl
    ↓
Pembersihan waypoint (dedup, filter noise)
    ↓
gps_route.json  ───→ Info/target GPS buat operator
    │
    ├──→ Mission AUTO Pixhawk (upload waypoint)
    └──→ Replay GUIDED script (lookahead + target GPS)
```

## Mode rekaman (`RECORD_MANUAL`)

- Kapal dikendalikan manual dari START sampai FINISH.
- Script hanya membaca telemetry; tidak mengirim override atau arm.
- Waypoint dicatat otomatis saat kedua syarat terpenuhi:
  - interval waktu minimum telah berlalu;
  - kapal sudah berpindah minimal jarak tertentu.
- Belokan dipertahankan: jika heading berubah signifikan, waypoint disimpan walaupun interval belum tercapai.
- Checkpoint khusus dapat ditandai oleh operator atau dideteksi otomatis:
  - `BLIND_CORNER` (belokan patah setelah pola 3×3);
  - `SURVEY_AREA` (area surface/underwater imaging);
  - `FINISH` (area docking).

Parameter rekaman:

| Parameter | Default | Deskripsi |
|-----------|---------|-----------|
| `--record-interval-s` | 1.0 | Interval waktu antar sampel GPS |
| `--record-min-distance-m` | 2.0 | Jarak minimal antar waypoint |
| `--record-heading-change-deg` | 20.0 | Perubahan heading yang memicu waypoint di luar interval |

Data yang dicatat per sampel:

- `timestamp_utc`, `lat`, `lon`, `heading_deg`, `ground_speed_m_s`
- `fix_type`, `satellites`, `hdop`
- `mode`, `armed`, `rc1`, `rc3` (Pixhawk)
- `checkpoint` (string opsional, untuk titik khusus)

## File yang dihasilkan

### `gps_track_raw.jsonl`

Semua sampel GPS mentah; tidak pernah dimodifikasi.

### `gps_route.json`

Waypoint bersih setelah deduplikasi dan filtering. Format:

```json
{
  "version": 1,
  "source": "gps_track_raw_20260715.jsonl",
  "parameters": {
    "record_interval_s": 1.0,
    "min_distance_m": 2.0,
    "heading_change_deg": 20.0
  },
  "waypoints": [
    {
      "index": 0,
      "lat": -1.234567,
      "lon": 102.345678,
      "heading_deg": 87.0,
      "distance_from_start_m": 0.0,
      "checkpoint": "START"
    },
    {
      "index": 12,
      "lat": -1.234700,
      "lon": 102.345900,
      "heading_deg": 176.0,
      "distance_from_start_m": 28.4,
      "checkpoint": "BLIND_CORNER"
    }
  ]
}
```

## Mode playback

### Mission AUTO Pixhawk

- `gps_route.json` diubah menjadi misi waypoint ArduPilot.
- Waypoint diunggah ke Pixhawk via MAVLink `MISSION_COUNT`/`MISSION_ITEM_INT`.
- Kapal bergerak dalam mode `AUTO`.
- Kecepatan target diatur parameter `WP_SPEED` ArduRover.

Parameter:

| Parameter | Default | Deskripsi |
|-----------|---------|-----------|
| `--replay-speed-mps` | 0.7 | Target kecepatan playback |

### Replay GUIDED script

- Script membaca `gps_route.json`.
- Script memilih target lookahead di depan kapal.
- Script mengirim target GPS ke Pixhawk via MAVLink `SET_POSITION_TARGET_GLOBAL_INT`.
- Pixhawk mengatur steering dan throttle dalam mode `GUIDED`.

Parameter:

| Parameter | Default | Deskripsi |
|-----------|---------|-----------|
| `--guided-interval-s` | 0.5 | Interval update target GUIDED |
| `--lookahead-m` | 10.0 | Jarak target di depan kapal di sepanjang track |
| `--replay-speed-mps` | 0.7 | Target kecepatan GUIDED |
| `--throttle-pwm` | 1500 | PWM throttle fallback jika speed control tidak dipakai (default netral untuk bench) |

Target lookahead dipilih dengan:

1. Cari waypoint terdekat dari posisi kapal sepanjang track.
2. Hitung jarak kumulatif dari waypoint tersebut.
3. Pilih waypoint yang jarak kumulatifnya = `lookahead-m`.
4. Jika lookahead melebihi waypoint terakhir, target = waypoint terakhir.

Track deviation check: jika jarak kapal ke segmen track terdekat melebihi batas, masuk failsafe.

### Perbedaan AUTO dan GUIDED

| Aspek | Mission AUTO | Replay GUIDED |
|-------|-------------|---------------|
| Controller | Pixhawk internal | Script via lookahead |
| Koreksi vision | Sulit ditambahkan | Dapat ditambahkan |
| Upload jalur ulang | Perlu upload misi | Baca file ulang |
| Ganti mode | Switch ke AUTO | Switch ke GUIDED |
| Stop darurat | RTL atau HOLD | Script stop kirim target + HOLD |

Keduanya tidak dijalankan bersamaan.

## Failsafe playback

Replay harus berhenti atau masuk `HOLD` jika:

- GPS fix hilang (`fix_type < 3`);
- data GPS tidak berubah selama timeout;
- kapal terlalu jauh dari track (`max_deviation_m`);
- heading tidak masuk akal;
- waypoint sudah habis (mencapai FINISH);
- telemetry Pixhawk terputus;
- operator memindahkan switch ke `MANUAL` atau `HOLD`;
- koneksi MAVLink timeout;
- command `Q`/`ESC` dari keyboard.

Script tidak melakukan auto-arm, auto-disarm, atau auto-RTL.

## Integrasi dengan computer vision

GPS adalah navigasi utama; vision adalah koreksi opsional:

- Selama `VISUAL_TRACK`, kamera dapat menggeser target GPS;
- Selama `BLIND_CORNER_REPLAY`, GPS tracking tetap berjalan;
- Setelah `SURVEY_AREA`, operator dapat memverifikasi hasil imaging;
- Vision failsafe tidak menghentikan GPS replay; hanya mencatat log.

## Verifikasi keselamatan

1. Uji rekaman: jalankan `--record-only`, remote kendalikan kapal, pastikan JSONL valid.
2. Pembersihan waypoint: verifikasi `gps_route.json` tidak berisi titik duplikat atau loncatan.
3. Upload misi: verifikasi waypoint benar di Mission Planner.
4. GUIDED bench: kapal di darat, replay `--throttle-pwm 1500`, log menunjukkan target GPS bergerak.
5. Verifikasi `SERVO3` sebelum replay throttle non-netral.
6. Uji air dengan throttle minimum dan jangkauan remote siap override.

## Di luar cakupan

- SLAM, peta kompleks, kamera baru, pan-tilt.
- Kontrol PID kustom; ArduPilot internal steering/throttle controller dipakai.
- Multi-sesi track merging; satu track per file.
- Auto-arm atau auto-disarm.
