# 10-Gate Navigation Reliability Implementation Plan

> **For agentic workers:** Implement task-by-task with tests and verification checkpoints.

**Goal:** Ganti kontrol rute berbasis sektor koordinat dengan kontrol waypoint berurutan yang stabil, aman saat belokan, dan dapat dievaluasi dari kondisi Webots yang bersih.

**Architecture:** `CourseRouteController` menjadi policy murni di `simulation/vision_route.py`. `vision_test.py` hanya mengumpulkan telemetry/deteksi, memberi keputusan progress dan aktuator ke controller, lalu mengirim override. Webots menyediakan progress/reset simulator; bridge meneruskan progress opsional tanpa mengubah jalur hardware nyata.

**Tech Stack:** Python 3, Webots R2025a, pymavlink, OpenCV/Ultralytics, pytest.

---

### Task 1: Tambah failing tests untuk course controller

**Files:**
- Modify: `tests/test_vision_route.py`

- [ ] Tambahkan test waypoint berurutan untuk gate 1–10, memastikan `gate_count=0` menargetkan `(11,-6)`, `gate_count=2` menargetkan `(11,6)`, `gate_count=3` menargetkan `(6,10)`, dan `gate_count=9` menargetkan `(-11,-6)`.
- [ ] Tambahkan test signed heading wrap: target `0`, current `359` menghasilkan steering kecil ke arah positif; target `270`, current `0` menghasilkan koreksi belok kiri/barat.
- [ ] Tambahkan test pre-turn throttle: error heading besar atau phase transition menghasilkan throttle lebih rendah daripada cruise.
- [ ] Tambahkan test progress clamp: `gate_count < 0` menjadi 0 dan `gate_count > 10` menjadi finish/neutral.
- [ ] Jalankan `pytest tests/test_vision_route.py -q`; expected: test baru gagal karena `CourseRouteController` belum ada.

### Task 2: Implementasikan pure waypoint course controller

**Files:**
- Modify: `simulation/vision_route.py`

- [ ] Tambahkan konstanta waypoint tuple:

```python
COURSE_WAYPOINTS = (
    (11.0, -6.0), (9.0, 0.0), (11.0, 6.0),
    (6.0, 10.0), (2.0, 10.0), (-2.0, 10.0), (-6.0, 10.0),
    (-11.0, 6.0), (-9.0, 0.0), (-11.0, -6.0),
)
```

- [ ] Tambahkan `CoursePhase` (`APPROACH`, `TURN`, `CORRIDOR`, `FINISH`) dan immutable `CourseDecision` yang memuat `steering_pwm`, `throttle_pwm`, `target_heading_deg`, `target_waypoint`, `gate_count`, `finished`.
- [ ] Tambahkan `CourseRouteConfig` dengan nilai validasi: `cruise_pwm=1555`, `approach_pwm=1545`, `turn_pwm=1525`, `corridor_pwm=1540`, `finish_pwm=1500`, `heading_tolerance_deg=4`, `turn_error_deg=35`, `max_steering_delta=180`.
- [ ] Tambahkan `CourseRouteController.step(gate_count, x, y, heading_deg)`. Clamp progress; pilih waypoint `gate_count`; hitung heading kompas menggunakan `atan2(target_x - x, target_y - y)`; hitung signed error; pilih throttle lebih rendah saat `abs(error) >= turn_error_deg`, jarak dekat waypoint, atau transisi Gate 3/Gate 7; hitung steering dengan bounded PD/heading helper.
- [ ] Untuk `gate_count == 10`, keluarkan neutral/finish dan jangan kembali ke waypoint terakhir.
- [ ] Jalankan test Task 1 sampai green.

### Task 3: Integrasikan controller ke vision_test.py

**Files:**
- Modify: `simulation/vision_test.py`

- [ ] Import `CourseRouteController`, `CourseRouteConfig`, dan `CourseDecision`.
- [ ] Inisialisasi controller sekali sebelum loop inference.
- [ ] Di setiap siklus navigasi, ambil `gate_count` dari telemetry bila tersedia; jika `None`, gunakan tracker visual monotonic, tanpa pernah menurunkan progress.
- [ ] Gantikan blok `is_turn_sector_3_to_4`, `is_right_slalom_gate2_3`, `is_turn_sector_7_to_8`, `is_top_corridor`, dan `is_left_slalom...` dengan satu pemanggilan `course_controller.step(...)` ketika mode simulasi/progress aktif.
- [ ] Pertahankan visual target hanya sebagai koreksi kecil (`max_delta` terbatas) setelah keputusan waypoint, bukan sebagai pengganti waypoint.
- [ ] Pertahankan E-stop, anti-stuck, MAVLink retry, metadata publisher, dan JSONL logging.
- [ ] Tambahkan log `course_phase`, `gate_count`, `target_waypoint`, `target_heading` agar kegagalan dapat dilacak.
- [ ] Jalankan `pytest tests/test_vision_route.py -q` dan `python -m compileall -q simulation`.

### Task 4: Tambah progress dan reset pada Webots controller

**Files:**
- Modify: `simulation/webots/controllers/asv_sim_agent/asv_sim_agent.py`

- [ ] Tambahkan `reset_requested` pada `SharedSimState` dan endpoint `POST /reset` yang hanya mengatur flag.
- [ ] Pada loop Supervisor, konsumsi flag lalu set translation kapal ke `(10.0, -11.5, 0.04)`, rotation Z ke `pi/2`, aktuator netral, dan reset `gate_tracker` melalui method `reset()` baru.
- [ ] Pastikan reset membuat run directory/logger baru dan status awal gate kembali `PENDING`.
- [ ] Tambahkan `gate_count` dan `finished` ke status JSON `/status` dari `gate_tracker.snapshot()`.
- [ ] Jalankan compile controller dan smoke test endpoint setelah Webots hidup.

### Task 5: Teruskan progress simulator melalui MAVLink opsional

**Files:**
- Modify: `simulation/webots/controllers/asv_sim_agent/asv_sim_agent.py`
- Modify: `simulation/sim_pixhawk_bridge.py`
- Modify: `simulation/vision_test.py`

- [ ] Kirim `NAMED_VALUE_INT` bernama `gate_count` dari Webots MAVLink publisher, 10Hz bersama telemetry.
- [ ] Di `sim_pixhawk_bridge.py`, teruskan message MAVLink secara transparan ke client; jangan mengubah RC override.
- [ ] Di `PixhawkLink.telemetry()`, baca `NAMED_VALUE_INT` dan simpan `gate_count` hanya jika nama cocok; hardware nyata tanpa message tetap menghasilkan `None`.
- [ ] Tambahkan tes parser metadata yang menerima nilai valid dan mengabaikan nama lain.

### Task 6: Buat evaluasi deterministik

**Files:**
- Modify: `simulation/evaluate_batch.py`
- Modify: `tests/test_vision_route.py` atau buat `tests/test_simulation_evaluation.py`

- [ ] Tambahkan `reset_simulation()` yang mengirim `POST http://127.0.0.1:8889/reset` dan gagal jelas jika HTTP bukan 2xx.
- [ ] Panggil reset sebelum timer batch dimulai.
- [ ] Tunggu status awal dengan `x≈10`, `y≈-11.5`, `passed_valid=0`, `missed=0`, `wall_touches=0`; timeout 10 detik dengan pesan diagnosa.
- [ ] Pertahankan penghentian cepat pada wall hit dan sukses Gate 10.
- [ ] Tambahkan tes parsing/validasi status awal tanpa membuka Webots.

### Task 7: Perbarui launcher dan handover

**Files:**
- Modify: `simulation/run_simulation.bat`
- Modify: `simulation/run_evaluation.bat`
- Modify: `simulation/HANDOVER.md`

- [ ] Pastikan launcher memakai working directory `simulation/`, path `model/best.pt`, dan endpoint `tcp:127.0.0.1:5762` yang konsisten.
- [ ] Dokumentasikan urutan startup: Webots → bridge → vision → reset/evaluation.
- [ ] Dokumentasikan sumber progress simulator, fallback hardware, parameter throttle, dan contoh output diagnostik.

### Task 8: Verifikasi end-to-end

**Files:**
- No source changes unless verification finds a defect.

- [ ] Jalankan `python -m compileall -q simulation tests`.
- [ ] Jalankan `pytest -q`; expected semua test pass.
- [ ] Buka Webots pada posisi awal bersih, jalankan bridge + vision, kemudian `python simulation/evaluate_batch.py`.
- [ ] Verifikasi output akhir: `passed_valid=10`, `missed=0`, `buoy_touches=0`, `wall_touches=0`, Gate 10 `PASSED_VALID`.
- [ ] Jika simulasi gagal, simpan `summary_report.md` dan `gate_scoring.json`, diagnosis satu hipotesis per iterasi; jangan menumpuk perubahan tanpa bukti.
- [ ] Commit implementasi dan push `main` setelah verification pass.
