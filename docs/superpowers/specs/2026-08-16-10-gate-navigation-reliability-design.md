# Desain Reliabilitas Navigasi 10 Gate Webots

## Status
Disetujui untuk implementasi berdasarkan instruksi pengguna: perbaiki seluruh masalah yang menghambat lintasan 10 gate.

## Masalah
Navigasi saat ini memakai percabangan koordinat di `vision_test.py`. State dapat berubah berdasarkan posisi mentah, tanpa memori gate yang sudah dilewati. Akibatnya transisi Gate 3→4 dan Gate 7→8 terlambat/berubah state saat heading mencapai target. Throttle juga tidak menurunkan kecepatan sebelum belokan. Evaluasi dapat dimulai dari simulasi lama sehingga posisi dan skor tidak bersih.

## Keputusan Desain

### 1. Kontrol rute event-driven
Tambahkan controller murni di `simulation/vision_route.py` yang menerima:

- `gate_count`: jumlah gate valid yang sudah dilewati;
- posisi `(x, y)`;
- heading aktual;
- waktu monotonic;
- deteksi buoy opsional.

Controller memilih waypoint tengah gate berikutnya berdasarkan `gate_count`, bukan percabangan koordinat yang saling tumpang tindih. Gate center tetap dikunci ke peta arena:

```text
1 (11,-6), 2 (9,0), 3 (11,6),
4 (6,10), 5 (2,10), 6 (-2,10), 7 (-6,10),
8 (-11,6), 9 (-9,0), 10 (-11,-6)
```

`gate_count` maju monotonik. Jika progress simulator tidak tersedia, controller tetap dapat menggunakan gate tracker visual sebagai fallback. Tidak ada state lama yang boleh aktif kembali setelah gate berikutnya dikonfirmasi.

### 2. Lookahead waypoint dan throttle adaptif
Untuk setiap waypoint, hitung target heading dari posisi aktual dengan konvensi Webots yang sudah dipakai: 0° = Utara, 90° = Timur, 180° = Selatan, 270° = Barat. Steering berasal dari signed heading error dengan PD damping.

Throttle dipilih berdasarkan fase:

- gate 1–3: cruise moderat sambil mendekati center gate;
- transisi setelah gate 3 dan gate 7: throttle rendah sebelum dan selama belokan;
- koridor gate 4–7: throttle stabil rendah-menengah untuk menjaga posisi Y sekitar 10m;
- gate 8–10: throttle moderat.

Saat heading error besar, throttle harus turun. Saat error kecil dan waypoint sudah searah, throttle dapat naik perlahan. Perubahan throttle rate-limited agar tidak melonjak.

### 3. Heading controller stabil
Pertahankan wrap-around heading error, tetapi gunakan dead-band kecil dengan koreksi halus, bukan langsung melepas rudder ke 1500. Controller mengembalikan steering netral hanya ketika error sangat kecil. Derivative term dibatasi agar noise MAVLink tidak menghasilkan hentakan.

### 4. Progress simulator yang eksplisit
`asv_sim_agent.py` mengekspor progress gate pada telemetry Webots. `sim_pixhawk_bridge.py` meneruskan progress sebagai metadata MAVLink opsional. `PixhawkLink.telemetry()` membaca metadata itu menjadi `gate_count`. Hardware nyata yang tidak mengirim metadata tetap berjalan dengan nilai `None`; route controller memakai fallback visual/posisi.

### 5. Reset evaluasi yang deterministik
Tambahkan `POST /reset` ke controller Webots. Handler hanya mengatur flag; loop Supervisor yang melakukan reset node kapal ke `(10,-11.5,0.04)`, heading Utara, mereset gate tracker, collision list, logger, dan command aktuator. `evaluate_batch.py` memanggil endpoint reset sebelum polling dan menunggu status awal. Ini mencegah batch membaca posisi/s skor dari run sebelumnya.

### 6. Safety
- E-stop tetap aktif pada ±13.8m.
- Saat mendekati batas ±11.5m, throttle dibatasi.
- Jika heading atau telemetry tidak tersedia, steering/throttle kembali netral.
- Wall/buoy collision tetap dicatat dan batch berhenti pada wall hit.
- Tidak mengubah jalur actuator hardware; perubahan progress hanya opsional untuk simulator.

## File yang Diubah

- `simulation/vision_route.py`: waypoint course controller, heading/phase decision, throttle policy.
- `simulation/vision_test.py`: gunakan controller event-driven, konsumsi `gate_count`, pertahankan logging/overlay.
- `simulation/webots/controllers/asv_sim_agent/asv_sim_agent.py`: expose progress dan reset endpoint.
- `simulation/sim_pixhawk_bridge.py`: forward gate progress metadata.
- `simulation/evaluate_batch.py`: reset sebelum run dan validasi status awal.
- `tests/test_vision_route.py`: unit test waypoint, heading wrap, progress monotonic, throttle turn.
- `tests/test_simulation_evaluation.py`: test reset request/status parsing tanpa menjalankan Webots.
- `simulation/HANDOVER.md`: dokumentasikan arsitektur baru dan parameter tuning.

## Verifikasi

1. Unit test route controller untuk semua gate, heading wrap 359°→0°, pre-turn throttle, dan fallback tanpa progress.
2. Unit test evaluator memastikan reset dipanggil dan status awal harus `(10,-11.5)` sebelum batch berjalan.
3. `python -m compileall -q simulation tests`.
4. `pytest -q`.
5. Jalankan Webots dari posisi awal bersih dan evaluator; target akhir 10/10 valid, 0 wall hit, 0 buoy hit.
