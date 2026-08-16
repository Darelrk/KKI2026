# Paket Simulasi Webots & Logika Navigasi Vision ASV KKI 2026

Folder ini berisi seluruh komponen mandiri (*self-contained*) untuk menjalankan, mengembangkan, dan menyetel algoritma navigasi vision kapal ASV di simulator Webots.

---

## 1. Struktur Folder

```text
simulation/
├── model/
│   ├── best.pt                # Bobot model YOLO deteksi buoy (Red/Green Buoy)
│   └── data.yaml              # Metadata kelas deteksi objek
├── webots/
│   ├── worlds/
│   │   └── kki_pool_arena.wbt # Arena kolam KKI lengkap dengan 10 Gate (20 Buoy) & Dinding
├── start_webots.bat           # 1-Click launcher untuk membuka arena kolam Webots
├── run_simulation.bat         # 1-Click launcher untuk menjalankan bridge & navigasi
├── run_evaluation.bat         # 1-Click launcher untuk menjalankan evaluasi skoring
├── README.md                  # Panduan teknis ini
├── vision_route.py            # Kalkulator heading target, visual servoing & helper kemudi
├── sim_pixhawk_bridge.py      # Simulator MAVLink Pixhawk (menerjemahkan telemetri Webots)
├── evaluate_batch.py          # Script penguji otomatis 10-Gate (skoring, wall hits, buoy hits)
├── run_simulation.bat         # 1-Click launcher untuk menjalankan bridge & navigasi
├── run_evaluation.bat         # 1-Click launcher untuk menjalankan evaluasi skoring
└── README.md                  # Panduan teknis ini
```

---

## 2. Cara Menjalankan Simulasi

### Prasyarat:
1. **Buka Arena Webots**:
   Cukup klik ganda pada:
   ```text
   start_webots.bat
   ```
   *(Atau buka langsung file `simulation/webots/worlds/kki_pool_arena.wbt` di Webots)*.
   Pastikan simulasi dalam mode **Real-Time** (tombol Play).

### Langkah-langkah:

1. **Buka Webots**:
   Buka file arena di Webots:
   ```text
   simulation/webots/worlds/kki_pool_arena.wbt
   ```
   Pastikan simulasi dalam mode **Real-Time** (tombol Play).

2. **Jalankan Navigasi Otomatis**:
   Cukup klik ganda pada:
   ```text
   run_simulation.bat
   ```
   *Atau via terminal*:
   ```bash
   python sim_pixhawk_bridge.py
   python vision_test.py --source http://127.0.0.1:8889/stream.mjpg --model model/best.pt --mavlink tcp:127.0.0.1:5762 --sim-mode
   ```

3. **Jalankan Evaluasi Otomatis 10 Gerbang**:
   Klik ganda pada `run_evaluation.bat` atau jalankan:
   ```bash
   python evaluate_batch.py
   ```
   Script ini akan melacak apakah kapal berhasil melewati masing-masing dari 10 gerbang secara valid (*PASSED_VALID*), mendeteksi tabrakan dinding (*Wall Hit*), dan tabrakan buoy (*Buoy Hit*).

---

## 3. Lokasi Penyetelan Parameter di `vision_test.py`

Untuk menyetel belokan, kecepatan, dan sensitivitas kemudi, buka `simulation/vision_test.py`:

* **Transisi Belokan Gate 3 $\to$ Gate 4 (Belok Barat)**:
  Cari blok `is_turn_sector_3_to_4`:
  * `max_pwm_delta`: Batas sudut rudder belokan.
  * `throttle_pwm`: Kecepatan putar (default: `1555`). Turunkan ke `1530`–`1540` jika kapal melebar ke dinding atas.
* **Transisi Gate 7 $\to$ Gate 8 (Belok Selatan)**:
  Cari blok `is_turn_sector_7_to_8`:
  * Target heading: `195.0°` (arah Barat Daya).
* **Sensitivitas Visual Servoing (YOLO Centering)**:
  Cari pemanggilan `compute_steering_pwm(target_x, frame.shape[1], gain=0.90, max_delta=75)`:
  * `gain`: Pengali koreksi kemudi visual (naikkan jika respon kurang cepat).
  * `max_delta`: Batas koreksi deviasi PWM kemudi visual dari titik tengah (1500).

---

## 4. Format Laporan Evaluasi
Hasil pengujian otomatis disimpan di folder `simulation/logs/run_<timestamp>/` yang berisi:
* `summary_report.md`: Ringkasan skor persentase kelulusan gerbang, jumlah benturan dinding, dan buoy.
* `gate_scoring.json`: Detail koordinat persilangan kapal di setiap gate ($X, Y$) dan status kelulusannya.
