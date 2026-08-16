# Handover Simulasi & Navigasi Otonom ASV KKI 2026

Dokumen ini ditujukan untuk developer / AI Agent yang melanjutkan pengembangan modul simulasi dan logika navigasi otonom kapal ASV di Webots.

---

## 1. Objektif dan status terakhir

Menguji navigasi otonom 10 gate di Webots dengan waypoint berurutan,
heading kompas, throttle aman saat belok, dan reset evaluasi yang
deterministik.

### Status verifikasi terakhir
- Run: `logs/run_20260816_021150/`
- Gate valid: **10/10**
- Buoy touch: **1** (`gate_3_red`, jarak 0.3976 m)
- Wall collision: **0**
- Durasi: **86.1 detik**
- Kesimpulan: rute selesai penuh, tetapi belum clean run; jangan klaim
  `buoy_touches=0`.

Run logger sekarang membuat folder baru saat `POST /reset`; jangan memakai
summary log lama untuk menyimpulkan hasil run baru.

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
                    ┌──────────────────────────────────────────────-─┐
                    │          vision_test.py                        │
                    │  - Baca MJPEG stream dari :8889                │
                    │  - Inferensi YOLO (model/best.pt)               │
                    │  - CourseRouteController untuk mode simulasi    │
                    │  - Kirim RC_OVERRIDE via bridge                 │
                    │  - Baca telemetry + gate_count                  │
                    └──────────────────────────────────────────────-─┘

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

## 5. Navigasi (`vision_test.py`)

### 5.1 Jalur simulasi utama

Jika telemetry Webots membawa `NAMED_VALUE_INT("gate_count")`, loop navigasi
memakai `CourseRouteController` dari `vision_route.py`. Controller ini policy
pure dengan waypoint berurutan:

```text
(11,-6) → (9,0) → (11,6) → (6,10) → (2,10) → (-2,10)
→ (-6,10) → (-11,6) → (-9,0) → (-11,-6) → FINISH
```

Phase controller:

- `APPROACH`: menuju waypoint berikutnya;
- `TURN`: throttle `1525` saat belokan besar;
- `CORRIDOR`: throttle `1540` pada koridor atas;
- `FINISH`: steering dan throttle netral setelah gate 10.

Heading dihitung dengan kompas dari posisi kapal ke waypoint. Steering
dibatasi agar tidak overshoot. Gate 10 juga memakai throttle turn saat
berada dalam 3 m dari garis gate.

### 5.2 Sumber progress dan fallback

`asv_sim_agent.py` menerbitkan `gate_count` melalui `NAMED_VALUE_INT`.
`sim_pixhawk_bridge.py` meneruskan MAVLink tanpa mengubah RC override.
`PixhawkLink.telemetry()` membaca nilai tersebut hanya jika nama field tepat.

Jika `gate_count` tidak tersedia—misalnya perangkat keras nyata—kode lama
berbasis visual/kompas tetap menjadi fallback. Hardware nyata tidak boleh
menganggap telemetry simulator sebagai progress valid.

Fallback umum tetap tersedia:

| Kondisi | Aksi |
|---|---|
| Buoy hilang sementara | tahan target terakhir lalu scan |
| Tidak ada target | sweep visual dengan throttle rendah |
| Kapal stuck | jalankan recovery yang sudah ada |
| Keluar batas arena | E-stop / hentikan loop |

### 5.3 Kontrak reset evaluasi

`POST http://127.0.0.1:8889/reset` hanya mengatur flag reset pada HTTP handler.
Loop Supervisor kemudian mengembalikan posisi ke `(10.0, -11.5, 0.04)`,
heading utara, PWM netral, gate tracker kosong, dan membuat folder log baru.
Evaluator menunggu status awal bersih sebelum memulai timer.

---

## 6. Tuning dan risiko yang masih terbuka

### 6.1 Kontrol waypoint

`CourseRouteController` adalah jalur utama ketika `gate_count` simulator
valid. Konfigurasi default:

| Parameter | Nilai | Fungsi |
|---|---:|---|
| `cruise_pwm` | 1555 | Kecepatan lintasan normal |
| `approach_pwm` | 1545 | Mendekati waypoint |
| `turn_pwm` | 1525 | Belokan besar dan gate 10 |
| `corridor_pwm` | 1540 | Koridor atas |
| `finish_pwm` | 1500 | Netral setelah gate 10 |
| `turn_error_deg` | 35° | Ambang throttle turn |
| `max_steering_delta` | 180 PWM | Batas koreksi heading |

### 6.2 Risiko terakhir

Run terakhir menyelesaikan semua gate, tetapi menyentuh `gate_3_red` pada
jarak 0.3976 m. Penyebab belum dipastikan; jangan mengubah beberapa
parameter sekaligus. Ulangi satu hipotesis per run setelah observasi
berikutnya.

Sensor tetap:

| Parameter | Nilai |
|---|---:|
| `BUOY_TOUCH_RADIUS` | 0.40 m |
| `WALL_LIMIT_X/Y` | 13.80 m |
| `basicTimeStep` | 16 ms |
| Gate crossing tolerance | ±0.25 m |

---

## 7. Cara Menjalankan

### Prasyarat

```bash
pip install ultralytics opencv-python pymavlink numpy
```

Webots R2025a atau lebih baru harus terinstall.

### Langkah Eksekusi

```bash
# Terminal 1: Buka arena Webots
cd simulation
start_webots.bat
# Tekan Play (Real-Time mode)

# Terminal 2: Jalankan MAVLink bridge
cd simulation
python sim_pixhawk_bridge.py

# Terminal 3: Jalankan navigasi vision
cd simulation
python vision_test.py --camera http://127.0.0.1:8889/stream.mjpg \
  --model ..\model\best.pt --endpoint tcp:127.0.0.1:5762

# Terminal 4: Reset + evaluasi deterministik
cd simulation
python evaluate_batch.py
```

Evaluator mengirim `POST /reset`, menunggu status awal bersih, lalu
menghentikan polling saat wall hit atau Gate 10 valid.

### Argumen penting

| Flag | Default | Fungsi |
|---|---|---|
| `--camera` | `0` | Webcam index atau URL MJPEG |
| `--model` | `D:\KKI2\model\best.pt` | Model YOLO |
| `--endpoint` | `tcp:127.0.0.1:5762` | Endpoint MAVLink |
| `--conf` | `0.35` | Confidence minimum |
| `--vision-fps` | `4.0` | Batas inferensi per detik |
| `--manual-rc` | off | Monitoring saja tanpa MAVLink |
| `--invert-steering` | off | Balik arah steering |

---

## 9. Debugging & Monitoring

### Log Realtime dari `vision_test.py`
Setiap 0.25 detik, output ke terminal:
```
[COURSE_TURN] Pos=(8.44, 1.06) Hdg=345° | Gate 2/10
hdg 350° err +5° target=(11.0,6.0) | S=1510 T=1525 | det=green_buoy
```
Format: `[COURSE_*] Pos=(x, y) Hdg=heading° | Gate n/10 ... | S=steering T=throttle`.

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

## 10. Strategi Pengembangan Berikutnya

Run terakhir masih memiliki satu sentuhan di `gate_3_red`. Lanjutkan
dengan satu hipotesis per iterasi:

1. bandingkan telemetry dan `vision_test` log di sekitar Gate 3;
2. ubah hanya satu parameter heading/throttle;
3. reset Webots sebelum setiap evaluasi;
4. baca `summary_report.md` dan `buoy_collisions.jsonl`;
5. pertahankan perubahan hanya jika gate tetap 10/10 dan touch berkurang.

Evaluator bukan read-only: evaluator mengirim `POST /reset`, tetapi tidak
mengendalikan aktuator.

### Catatan teknis penting

1. Webots sebaiknya mode Real-Time; mode Fast mengubah timing fisika.
2. Sensor dinding aktif pada ±13.8 m, sedangkan dinding fisik berada pada
   ±15.0 m.
3. Root dan `simulation/` memiliki `vision_route.py` yang sama. `simulation/vision_test.py`
   menambahkan jalur simulator `gate_count`; jangan menyalin seluruh file ke
   runtime hardware tanpa meninjau kontrak Pixhawk.
4. `POST /reset` membuat sesi logger baru; gunakan `run_id` dari endpoint
   `/gates` untuk menemukan log yang benar.
