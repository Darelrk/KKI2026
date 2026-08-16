# Handover Simulasi & Navigasi Otonom ASV KKI 2026

Dokumen ini ditujukan untuk developer / AI Agent yang melanjutkan pengembangan modul simulasi dan logika navigasi otonom kapal ASV di Webots.

---

## 1. Objektif

Menyempurnakan algoritma navigasi otonom berbasis **Computer Vision (YOLOv8) + Kompas IMU** agar kapal berhasil melewati **10 Gerbang** secara berurutan tanpa menabrak buoy atau dinding arena.

### Acceptance Criteria
1. `evaluate_batch.py` mencatat **10/10 Gate** berstatus `PASSED_VALID`.
2. `wall_touches = 0` (tidak menabrak dinding arena).
3. `buoy_touches = 0` (tidak menabrak tiang buoy).
4. Total waktu tempuh < 60 detik.

### Baseline Saat Ini
- **Gate 1 & 2**: Konsisten `PASSED_VALID` (kecepatan 2.2 m/s).
- **Gate 3**: Kadang `PASSED_VALID`, kadang `MISSED_OUTSIDE` tergantung timing belokan.
- **Gate 4–10**: Belum pernah tercapai secara konsisten; kapal menabrak dinding utara setelah Gate 3.

---

## 2. Struktur File

```text
simulation/
├── model/
│   ├── best.pt                  # Bobot YOLO deteksi buoy (kelas: red_buoy, green_buoy)
│   └── data.yaml                # Metadata kelas deteksi
├── webots/
│   ├── worlds/
│   │   ├── kki_pool_arena.wbt   # Arena kolam 30m x 30m (10 Gate, 20 Buoy, 4 Dinding)
│   │   └── .kki_pool_arena.wbproj
│   ├── protos/
│   │   ├── KKIBoat.proto        # Model fisika kapal (kamera, GPS, kompas, rudder, thruster)
│   │   ├── BuoyRed.proto        # Model buoy merah
│   │   ├── BuoyGreen.proto      # Model buoy hijau
│   │   ├── BuoyBlue.proto       # Model buoy biru (penanda dok)
│   │   └── TargetDock.proto     # Model dermaga start/finish
│   └── controllers/
│       └── asv_sim_agent/
│           └── asv_sim_agent.py # Controller Webots: fisika kapal + MJPEG stream + gate scoring
├── vision_test.py               # >>> FILE UTAMA: Loop navigasi Vision YOLO + State Machine <<<
├── vision_route.py              # Modul pembantu: steering PWM, heading calc, target tracker
├── sim_pixhawk_bridge.py        # MAVLink bridge: Webots telemetry → format Pixhawk standar
├── evaluate_batch.py            # Evaluator otomatis: polling /status, skor 10 gate
├── start_webots.bat             # Launcher: buka arena di Webots
├── run_simulation.bat           # Launcher: jalankan bridge + navigasi
├── run_evaluation.bat           # Launcher: jalankan evaluasi skoring
└── logs/                        # Output evaluasi per run (auto-generated)
```

---

## 3. Arsitektur & Aliran Data

```text
┌──────────────────────────────────────────────────────────────────┐
│                         WEBOTS SIMULATOR                        │
│                                                                  │
│  kki_pool_arena.wbt                                              │
│  ┌────────────────┐    ┌────────────────────────────────────┐   │
│  │   KKIBoat      │    │  asv_sim_agent.py (Controller)     │   │
│  │ - surface_cam  │───>│  - Fisika gerak (rudder + thrust)  │   │
│  │ - GPS          │    │  - MJPEG stream :8889              │   │
│  │ - Compass      │    │  - Gate crossing detection         │   │
│  │ - Rudder motor │    │  - Buoy/Wall collision sensor      │   │
│  │ - Thruster     │    │  - Telemetry UDP :14550            │   │
│  └────────────────┘    │  - Actuator UDP :9090 (listen)     │   │
│                         └──────┬───────────────┬─────────────┘   │
└────────────────────────────────┼───────────────┼─────────────────┘
                                  │               │
                    MJPEG :8889   │   UDP :14550  │  UDP :9090
                                  │               │
                    ┌─────────────┴───────────────┴──────────────┐
                    │      sim_pixhawk_bridge.py                  │
                    │  - Terima telemetry UDP dari Webots          │
                    │  - Broadcast MAVLink TCP :5762               │
                    │  - Forward RC_OVERRIDE → Webots UDP :9090   │
                    └─────────────────┬──────────────────────────-─┘
                                      │
                         MAVLink TCP :5762
                                      │
                    ┌─────────────────┴──────────────────────────-─┐
                    │          vision_test.py                       │
                    │  - Baca MJPEG stream dari :8889               │
                    │  - Inferensi YOLO (model/best.pt)             │
                    │  - State machine navigasi per sektor          │
                    │  - Kirim RC_OVERRIDE (steering + throttle)    │
                    │  - Baca telemetry (px, py, heading)           │
                    └──────────────────────────────────────────────-┘

                    ┌──────────────────────────────────────────────-┐
                    │          evaluate_batch.py                    │
                    │  - Poll HTTP :8889/status setiap 0.5 detik    │
                    │  - Baca gate_tracking dari asv_sim_agent      │
                    │  - Cetak skor dan hentikan saat wall hit      │
                    └──────────────────────────────────────────────-┘
```

### Port & Protokol
| Port  | Protokol | Arah                   | Fungsi                                  |
|-------|----------|------------------------|-----------------------------------------|
| 8889  | HTTP     | Webots → vision_test   | MJPEG stream kamera + REST API /status  |
| 9090  | UDP      | bridge → Webots        | Perintah aktuator (steering, throttle)  |
| 14550 | UDP      | Webots → bridge        | Telemetry mentah (pos, heading, speed)  |
| 5762  | TCP      | bridge → vision_test   | MAVLink standar (multi-client)          |

---

## 4. Peta Arena & Koordinat 10 Gate

Arena kolam: 30m × 30m. Koordinat pusat = (0, 0). Dinding di ±15.0m. Sensor dinding aktif di ±13.8m.

```text
              DINDING UTARA (Y = +15.0m)
    ┌─────────────────────────────────────────────┐
    │                                              │
    │    G7         G6         G5         G4       │  Y=10.0m (koridor)
    │   [-6,10]   [-2,10]   [+2,10]   [+6,10]     │  (gate vertikal, lebar 2m)
    │                                              │
    │                                              │
    │  G8                                   G3     │  Y=+6.0m
    │ [-11,6]                             [11,6]   │
    │                                              │
    │  G9                                   G2     │  Y=0.0m
    │ [-9,0]                              [9,0]    │
    │                                              │
    │  G10                                  G1     │  Y=-6.0m
    │ [-11,-6]                            [11,-6]  │
    │                                              │
    │                              START [10,-11.5]│
    │                              (heading North) │
    └─────────────────────────────────────────────┘
              DINDING SELATAN (Y = -15.0m)
```

### Tabel Gate Lengkap

| Gate | Nama              | Tipe       | Koordinat Buoy Merah | Koordinat Buoy Hijau | Validasi Crossing             |
|------|--------------------|------------|----------------------|----------------------|-------------------------------|
| 1    | Slalom Kanan 1     | horizontal | [10.0, -6.0]         | [12.0, -6.0]         | Y cross -6.0, X ∈ [9.75, 12.25] |
| 2    | Slalom Kanan 2     | horizontal | [8.0, 0.0]           | [10.0, 0.0]          | Y cross 0.0, X ∈ [7.75, 10.25]  |
| 3    | Slalom Kanan 3     | horizontal | [10.0, 6.0]          | [12.0, 6.0]          | Y cross 6.0, X ∈ [9.75, 12.25]  |
| 4    | Koridor Atas 1     | vertical   | [6.0, 9.0]           | [6.0, 11.0]          | X cross 6.0, Y ∈ [8.75, 11.25]  |
| 5    | Koridor Atas 2     | vertical   | [2.0, 9.0]           | [2.0, 11.0]          | X cross 2.0, Y ∈ [8.75, 11.25]  |
| 6    | Koridor Atas 3     | vertical   | [-2.0, 9.0]          | [-2.0, 11.0]         | X cross -2.0, Y ∈ [8.75, 11.25] |
| 7    | Koridor Atas 4     | vertical   | [-6.0, 9.0]          | [-6.0, 11.0]         | X cross -6.0, Y ∈ [8.75, 11.25] |
| 8    | Slalom Kiri 1      | horizontal | [-10.0, 6.0]         | [-12.0, 6.0]         | Y cross 6.0, X ∈ [-12.25, -9.75]|
| 9    | Slalom Kiri 2      | horizontal | [-8.0, 0.0]          | [-10.0, 0.0]         | Y cross 0.0, X ∈ [-10.25, -7.75]|
| 10   | Slalom Kiri 3      | horizontal | [-10.0, -6.0]        | [-12.0, -6.0]        | Y cross -6.0, X ∈ [-12.25, -9.75]|

> Toleransi validasi: ±0.25m dari tepi tiang buoy (lihat `asv_sim_agent.py` baris 428/449).

---

## 5. State Machine Navigasi (`vision_test.py`)

### 5.1 Alur Urutan State

```text
START [10.0, -11.5] heading 0° (North)
  │
  ▼
┌─────────────────────┐
│  Default Vision     │  Deteksi YOLO aktif: cari red/green buoy
│  (target_x based)   │  steering = visual servoing ke titik tengah gate
│                      │  throttle = 1565 (cruise)
└──────┬──────────────┘
       │  Masuk zona py ∈ [0, 6) & px ≥ 5.0
       ▼
┌─────────────────────┐
│  RIGHT_SLALOM_      │  Heading kompas → 30° NNE
│  2_TO_3_BLEND       │  max_pwm_delta = 140
│                      │  throttle = 1565
└──────┬──────────────┘
       │  Masuk zona py ≥ 6.0 & px ≥ 9.8 & hdg < 260 or > 320
       ▼
┌─────────────────────┐
│  SECTOR_TURN_       │  >>> BELOKAN KRITIS 90° <<<
│  3_TO_4             │  Heading kompas → 270° (West)
│                      │  max_pwm_delta = 250 (rudder penuh)
│                      │  throttle = 1555
└──────┬──────────────┘
       │  Masuk zona py ≥ 7.0 & -6.0 < px < 9.5
       ▼
┌─────────────────────┐
│  TOP_CORRIDOR_      │  PD line hold: Y = 10.0m + heading 270°
│  BLEND              │  Blend 60% vision + 40% kompas
│                      │  max_pwm_delta = 120
│                      │  throttle = 1565
└──────┬──────────────┘
       │  Masuk zona px ≤ -6.0 & py ≥ 5.0 & hdg < 170 or > 240
       ▼
┌─────────────────────┐
│  SECTOR_TURN_       │  >>> BELOKAN KRITIS 90° <<<
│  7_TO_8             │  Heading kompas → 195° (SSW)
│                      │  max_pwm_delta = 250
│                      │  throttle = 1555
└──────┬──────────────┘
       │  Masuk zona px ≤ -5.0 & py ∈ [0, 5) atau py < 0
       ▼
┌─────────────────────┐
│  LEFT_SLALOM_       │  Heading waypoint: 150° (gate 8→9) atau 205° (gate 9→10)
│  BLEND              │  Blend 55% vision + 45% kompas
│                      │  max_pwm_delta = 120
│                      │  throttle = 1560
└──────┴──────────────┘
```

### 5.2 Fallback States

| State               | Kondisi Trigger                        | Aksi                                          |
|----------------------|----------------------------------------|-----------------------------------------------|
| `SEARCH_SCANNING`    | Tidak ada buoy terdeteksi              | Sweep steering ±40 PWM, throttle 1545         |
| `VISION_TARGET_HOLD` | Buoy terakhir hilang < hold_s detik    | Pertahankan target_x terakhir                 |
| `UNSTUCK_REVERSE`    | speed < 0.10 m/s selama > 4 detik     | Mundur (throttle 1420, steer 1200) selama 1.5s|
| `E-STOP`             | abs(px) atau abs(py) ≥ 13.80m         | Script berhenti total (break loop)            |

### 5.3 Penentuan Sektor (Baris 948–952 di `vision_test.py`)

```python
is_right_slalom_gate2_3 = (py ∈ [0, 6) and px ≥ 5.0)
is_turn_sector_3_to_4   = (py ≥ 6.0 and px ≥ 9.8 and hdg ∉ [260, 320])
is_top_corridor          = (py ≥ 7.0 and px ∈ (-6.0, 9.5))
is_turn_sector_7_to_8   = (px ≤ -6.0 and py ≥ 5.0 and hdg ∉ [170, 240])
is_left_slalom_gate8_9   = (px ≤ -5.0 and py ∈ [0, 5))
is_left_slalom_gate9_10  = (px ≤ -5.0 and py < 0)
```

> **Prioritas**: `if-elif` berurutan. `is_turn_sector_3_to_4` dicek sebelum `is_right_slalom_gate2_3` karena zona overlap di Y=6.0.

---

## 6. Masalah Kritis & Root Cause

### Masalah 1: Inersia Belokan Gate 3 → Gate 4

**Situasi**: Setelah melewati Gate 3 (Y=6.0m), kapal harus berbelok 90° ke Barat. Dinding utara di Y=13.8m. Jarak tersisa = 7.8m.

**Root Cause**: Pada kecepatan 2.2 m/s, kapal membutuhkan ~3.5 detik untuk memutar haluan 90°. Selama waktu itu, momentum membawa kapal ~7.7m ke utara → menabrak dinding.

**Rekomendasi Solusi**:
1. **Turunkan throttle saat belokan**: Ubah `throttle_pwm` dari `1555` ke `1530` di blok `SECTOR_TURN_3_TO_4`. Ini menurunkan kecepatan dari 2.2 ke ~1.0 m/s, memberi ruang belok.
2. **Mulai belok lebih awal**: Ubah threshold `py ≥ 6.0` ke `py ≥ 5.5` agar rudder mulai memutar sebelum melewati tiang Gate 3. Risiko: bisa menyebabkan `MISSED_OUTSIDE` jika terlalu dini.
3. **Aktifkan rudder + reverse brake**: Saat sudut error > 60°, tambahkan `throttle_pwm = 1470` (reverse ringan) untuk membantu pivot.

### Masalah 2: Blindspot Kamera saat Memutar Haluan

**Situasi**: Kamera depan (FOV ~60°) kehilangan visual buoy selama 1–2 detik saat kapal memutar 90°.

**Root Cause**: Saat `SECTOR_TURN_3_TO_4` aktif, state machine sudah benar menggunakan `compute_pd_heading_pwm` (kompas murni, tanpa visual). Namun saat belokan selesai dan kapal masuk `TOP_CORRIDOR_BLEND`, buoy belum terdeteksi → fallback ke `SEARCH_SCANNING` yang terlalu lambat.

**Rekomendasi**: Tambahkan transisi delay: setelah `SECTOR_TURN` selesai (heading error < 15°), berikan 2 detik grace period dengan heading hold murni sebelum mengaktifkan visual blend.

### Masalah 3: Kapal Stuck / Speed 0 setelah Tabrak Buoy

**Situasi**: Jika kapal menyerempet buoy, fisika Webots memperlambat hingga 0 m/s. Anti-stuck timer baru aktif setelah 4 detik delay.

**Rekomendasi**: Turunkan `stuck_timer` threshold dari 4.0s ke 2.5s (baris ~1057).

---

## 7. Parameter Kunci untuk Tuning

### 7.1 File `vision_test.py` — Kontrol Kemudi

| Parameter | Lokasi | Default | Fungsi |
|-----------|--------|---------|--------|
| `compute_pd_heading_pwm(target, current, last_err, dt, max_pwm_delta)` | baris 623 | — | PD controller heading kompas. `kp=1.5, kd=0.15` hardcoded. |
| `max_pwm_delta` (turn sectors) | baris 949, 967 | 250 | Batas rudder saat belokan tajam. Naikkan = belok lebih agresif. |
| `max_pwm_delta` (corridor/slalom) | baris 979, 995 | 120 | Batas rudder saat jalur lurus/slalom. Terlalu tinggi = overshoot. |
| `throttle_pwm` (cruise) | baris 989, 962 | 1565 | Kecepatan jalur lurus (~2.2 m/s). |
| `throttle_pwm` (turn) | baris 951, 969 | 1555 | Kecepatan saat belokan 90°. **Turunkan ke 1530 untuk mengurangi inersia.** |
| `search_controller` | baris 760 | center=1500, delta=40, period=5s, throttle=1545 | Sweep pola saat kehilangan visual. |

### 7.2 File `vision_test.py` — Visual Servoing

| Parameter | Default | Fungsi |
|-----------|---------|--------|
| `gain` di `compute_steering_pwm()` | 0.90 | Pengali koreksi visual (naikkan = respons cepat, risiko oscillation). |
| `max_delta` di `compute_steering_pwm()` | 75 | Batas deviasi PWM visual dari netral. |
| Blend ratio koridor | 0.60 vis / 0.40 kompas | Bobot campuran visual vs kompas di koridor atas. |
| Blend ratio slalom kiri | 0.55 vis / 0.45 kompas | Bobot campuran visual vs kompas di slalom kiri. |

### 7.3 File `vision_route.py` — Konstanta

| Konstanta | Nilai | Fungsi |
|-----------|-------|--------|
| `NEUTRAL_PWM` | 1500 | Titik tengah servo (lurus / diam). |
| `PWM_MIN` | 1000 | Batas bawah PWM (kiri penuh / mundur penuh). |
| `PWM_MAX` | 2000 | Batas atas PWM (kanan penuh / maju penuh). |
| `STEERING_MAX_DELTA` | 400 | Deviasi absolut maksimum dari netral. |

### 7.4 File `asv_sim_agent.py` — Sensor & Fisika

| Parameter | Nilai | Fungsi |
|-----------|-------|--------|
| `BUOY_TOUCH_RADIUS` | 0.40m | Jarak sentuh buoy (kapal 0.15m + buoy 0.22m + margin). |
| `WALL_LIMIT_X/Y` | 13.80m | Jarak dari pusat kolam saat sensor dinding aktif. |
| `basicTimeStep` | 16ms | Resolusi simulasi Webots (~62.5 Hz). |
| Gate crossing tolerance | ±0.25m | Margin kelulusan di luar batas tiang buoy. |

### 7.5 Range PWM & Efek Fisik

| PWM Range | Steering (Ch 1) | Throttle (Ch 3) |
|-----------|------------------|------------------|
| 1000 | Kiri penuh (rudder max kiri) | Mundur penuh |
| 1200 | Kiri sedang | Mundur ringan |
| 1420 | Kiri ringan | Mundur darurat (unstuck) |
| 1500 | Lurus (netral) | Diam (netral) |
| 1530 | — | Maju lambat (~1.0 m/s) |
| 1545 | — | Maju scanning (~1.3 m/s) |
| 1555 | — | Maju manuver (~1.6 m/s) |
| 1565 | — | Maju cruise (~2.2 m/s) |
| 1800 | Kanan sedang | Maju cepat |
| 2000 | Kanan penuh | Maju penuh |

---

## 8. Cara Menjalankan

### Prasyarat
```bash
pip install ultralytics opencv-python pymavlink numpy
```
Webots R2025a atau lebih baru harus terinstall.

### Langkah Eksekusi (3 Terminal)

```bash
# Terminal 1: Buka Arena Webots (atau klik start_webots.bat)
# Tekan Play (Real-Time mode)

# Terminal 2: Jalankan MAVLink Bridge
cd simulation
python sim_pixhawk_bridge.py

# Terminal 3: Jalankan Navigasi Vision
cd simulation
python vision_test.py --source http://127.0.0.1:8889/stream.mjpg --model model/best.pt --mavlink tcp:127.0.0.1:5762 --sim-mode
```

### Evaluasi Otomatis (Terminal 4)
```bash
cd simulation
python evaluate_batch.py
```

### Argumen Penting `vision_test.py`
| Flag | Default | Fungsi |
|------|---------|--------|
| `--source` | `0` (webcam lokal) | Sumber video. Pakai URL MJPEG untuk simulasi. |
| `--model` | `model/best.pt` | Path ke model YOLO. |
| `--mavlink` / `--endpoint` | `tcp:127.0.0.1:5762` | Endpoint MAVLink. |
| `--sim-mode` | off | Aktifkan mode simulasi (nonaktifkan fitur hardware). |
| `--conf` | `0.25` | Threshold confidence YOLO. |
| `--vision-fps` | `4` | Target FPS inferensi YOLO. |
| `--manual-rc` | off | Mode RC manual (hanya deteksi, tanpa kontrol). |
| `--invert-steering` | off | Balik arah steering (mirror kamera). |

---

## 9. Debugging & Monitoring

### Log Realtime dari `vision_test.py`
Setiap 0.25 detik, output ke terminal:
```
[SECTOR_TURN_3_TO_4] Pos=(9.21, 6.44) Hdg=1.9° | Belok West (270°) ke Gate 4 [Err: -91.9°] | S=1200 T=1555 | det=red_buoy
```
Format: `[STATE] Pos=(x, y) Hdg=heading° | nav_target_info | S=steering T=throttle | det=labels`

### Endpoint HTTP (dari asv_sim_agent di Webots)
| URL | Response |
|-----|----------|
| `http://127.0.0.1:8889/stream.mjpg` | MJPEG video stream |
| `http://127.0.0.1:8889/status` | JSON: pos, heading, speed, gate_tracking |
| `http://127.0.0.1:8889/gates` | JSON: detail skor per gate |

### Log File
- `simulation/logs/run_<timestamp>/summary_report.md` — Ringkasan skor.
- `simulation/logs/run_<timestamp>/gate_scoring.json` — Detail koordinat crossing per gate.
- `vision_test_log.jsonl` (di root KKI2026) — Log telemetri per-frame dari vision_test.py.

---

## 10. Strategi Pengembangan yang Disarankan

### Prioritas 1: Fix Belokan Gate 3 → 4
1. Turunkan `throttle_pwm` ke `1530` di `SECTOR_TURN_3_TO_4`.
2. Jalankan `evaluate_batch.py` dan konfirmasi Gate 3 masih `PASSED_VALID` + Gate 4 tercapai.
3. Jika masih menabrak dinding: geser threshold `py ≥ 6.0` ke `py ≥ 5.5`.

### Prioritas 2: Fix Koridor Atas (Gate 4–7)
1. Pastikan `TOP_CORRIDOR_BLEND` menjaga kapal di Y ≈ 10.0m.
2. Tune `y_err * 20.0` gain jika kapal terlalu jauh dari garis tengah.
3. Verifikasi 4 gate vertikal tercapai berurutan.

### Prioritas 3: Fix Belokan Gate 7 → 8
1. Sama seperti Gate 3→4: turunkan throttle, pastikan heading target 195° tepat.
2. Verifikasi kapal tidak menabrak dinding barat (X = -13.8m).

### Prioritas 4: Slalom Kiri (Gate 8–10)
1. Tune heading waypoint: 150° (gate 8→9) dan 205° (gate 9→10).
2. Tune blend ratio vision vs kompas.

### Cycle Iterasi yang Efektif
```
Edit vision_test.py → Restart vision_pipeline →
Tunggu evaluate_batch.py → Cek summary_report.md →
Analisis gate mana yang gagal → Edit ulang
```

---

## 11. Catatan Teknis Penting

1. **Jangan ubah `asv_sim_agent.py` atau `sim_pixhawk_bridge.py`** kecuali perlu mengubah fisika simulasi atau format telemetry. Fokus pengembangan ada di `vision_test.py`.
2. **Webots harus dalam mode Real-Time** (bukan Fast). Mode Fast menyebabkan timing navigasi kacau.
3. **`evaluate_batch.py` bersifat read-only**: hanya membaca `/status` dari Webots, tidak mengontrol kapal.
4. **Gate crossing hanya dicek sekali per gate** (status `PENDING` → `PASSED_VALID` atau `MISSED_OUTSIDE`). Tidak ada retry.
5. **Sensor dinding di ±13.8m** berbeda dari dinding fisik di ±15.0m. Kapal punya ~1.2m margin sebelum benar-benar menabrak dinding fisik Webots.
6. **`vision_test.py` di folder `simulation/` adalah COPY** dari `KKI2026/vision_test.py`. Setelah selesai tuning, salin balik ke root project.
