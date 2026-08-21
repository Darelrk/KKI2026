# Handover Simulator ASV KKI 2026

## Ruang lingkup

Simulator memodelkan ASV monohull 9,5 kg dengan satu azimuth thruster,
computer vision YOLO, lima sensor ultrasonik, Arena A/B, skoring sepuluh
gerbang, dua marker bawah, dan docking stabil. Spesifikasi badan kapal: LOA 1,065 m, beam
0,300 m, tinggi 0,755 m.

## Arsitektur runtime

```text
Webots rigid body + camera + ultrasonic + gate tracker
  | MJPEG :8889
  | MAVLink telemetry UDP :14550
  | RC actuator UDP :9090
  v
sim_pixhawk_bridge.py -- MAVLink TCP :5762 -- vision_test.py
                                                | YOLO buoy pair matcher
                                                | HSV marker-box detector
                                                | CourseAutopilot 20 Hz
                                                v
                                           RC1 + RC3 override
```

`vision_test.py` menjalankan kontrol course pada thread 20 Hz agar inferensi
YOLO 4 FPS dan detektor marker tidak menahan aktuator. Model YOLO saat ini
hanya memiliki kelas `red_buoy` dan `green_buoy`; `blue_marker`/`green_marker`
dibuat dari segmentasi HSV dan uji bentuk persegi panjang. Progress simulator berasal dari
`gate_count`; pada perangkat keras tanpa field tersebut, jalur visual/kompas
lama tetap menjadi fallback dan perlu diuji tersendiri.

## Keputusan implementasi penting

- Webots menggunakan gaya pada offset buritan, bukan mengubah translation atau
  rotation kapal secara langsung.
- RC1 mengatur pod sampai +/-80 derajat pada model terkalibrasi; RC3 1500 adalah netral/coast.
- Speed governor mengirim pulsa dorong saat perlu dan kembali netral ketika
  overspeed. Timeout satu detik juga menetralkan RC3. Dalam simulator, pulsa
  reverse pendek dipakai pada recovery/docking jika ESC reversible; nonaktifkan
  dengan `ASV_REVERSE_THRUST_ENABLED=0` untuk menguji ESC forward-only.
- Sensor resmi disebut `ultrasonic`, bukan sonar. Lima kanal: `front_left`,
  `front`, `front_right`, `left`, `right`. Alias JSON `sonar` dipertahankan
  sementara untuk kompatibilitas.
- Computer vision memasangkan merah-kiri/hijau-kanan dengan pemeriksaan
  alignment, ukuran, dan kedalaman. Koreksi kamera dibatasi 160 PWM,
  dihaluskan, serta kedaluwarsa setelah 0,55 detik.
- Kotak marker tidak berasal dari kelas YOLO. `detect_marker_boxes()` memakai
  HSV, rectangularity, solidity, dan aspect ratio untuk menghasilkan deteksi
  `blue_marker`/`green_marker`; saat marker aktif terlihat, controller menjauh
   dari pusat kotak dengan koreksi terbatas; throttle hanya dibatasi kuat saat
   kotak benar-benar memenuhi frame agar rute tidak merayap terlalu dini.
- Vision memakai `/stream_raw.mjpg`; `/stream.mjpg` tetap tersedia untuk
  dashboard tetapi berisi HUD/koridor grafis yang tidak boleh masuk ke model.
- Ultrasonic avoidance memiliki slow 1,20 m, stop/escape 0,55 m, dan release
  hysteresis 0,85 m. Pulsa escape diperlukan karena single thruster tidak bisa
  mengubah heading saat thrust nol; bila benar-benar tersangkut, satu reverse
  pulse setelah 0,80 detik membantu melepaskan halangan. Geofence basin mulai
  recovery 2,4 m dari dinding bawah/lateral.
- Setelah Gate 10, marker biru dan hijau harus dilintasi berurutan dalam
  koridor pusatnya. Kotak marker bersifat fisik: guidance melewati sisi aman
  kiri-bawah biru lalu kanan/timur hijau dengan lead utara; reverse-turn hanya
  dipakai bila benar-benar dekat dan overspeed, kemudian staging keluar hijau,
  tiga waypoint return progresif, serta alignment heading di entry sebelum
  menuju dock.
- Dock akhir adalah kotak biru vertikal dengan tiga buoy biru, bukan marker
  biru di kiri lintasan. Sukses memerlukan 10 gate + 2 marker valid, posisi
  <=0,75 m, heading error <=15 derajat, speed <=0,15 m/s, stabil 3 detik.
- Arena B dibuat dengan pencerminan `x_B = 30 - x_A` terhadap garis `x=15`.

## File utama

- `webots/protos/KKIBoat.proto`: geometri, massa, collision body, thruster, dan
  lima DistanceSensor ultrasonik.
- `webots/worlds/kki_pool_arena.wbt`: dua arena dan posisi objek.
- `webots/controllers/asv_sim_agent/asv_sim_agent.py`: fisika, HTTP, MAVLink,
  reset, sensor, collision, gate tracker, dan logger.
- `vision_route.py`: route control, speed governor, CV correction, ultrasonic
  avoidance, dan docking.
- `vision_test.py`: YOLO, MAVLink, autopilot 20 Hz, UI, dan JSONL.
- `sim_pixhawk_bridge.py`: multiplex MAVLink dan penerjemah sensor.
- `evaluate_batch.py`: reset serta polling hasil end-to-end.

## Kontrak arena

Start A `(11.1,-11.5)`, dock A `(11.5,-13.0)`. Start B `(18.9,-11.5)`,
dock B `(18.5,-13.0)`. Pusat gerbang A:

```text
(11,-6), (9,0), (11,6), (6,10), (2,10), (-2,10), (-6,10),
(-11,6), (-9,0), (-11.3,-6)
```

Marker biru A `(-9.7,-8.7)` harus dilintasi sebelum marker hijau
`(-6.9,-11.9)`; pass point controller adalah `(-11.2,-9.2)` lalu
`(-5.55,-11.25)`. Setelah itu kapal mengikuti staging `(-4.8,-10.8)`, return
`(1,-8.5) -> (7,-8.3)`, dan entry dock `(11.5,-10.45)`. Arena B memakai
titik cermin.

## Verifikasi sebelum handoff

Run end-to-end sebelum koreksi marker/dock berakhir pada target lama dan tidak
boleh dipakai untuk penerimaan versi ini. Buat run baru Arena A dan B setelah
restart Webots; bukti harus memperlihatkan 10/10 gate dan 2/2 marker valid.

1. Restart Webots setelah mengubah PROTO/controller.
2. Jalankan `start_webots.bat A`, lalu `run_simulation.bat A`.
3. Jalankan `python simulation\evaluate_batch.py --arena A --duration 300`.
4. Ulangi untuk B.
5. Terima run hanya jika 10/10 gate valid, 2/2 marker valid, missed 0, buoy
   touch 0, wall touch 0, dan `docked=true`.
6. Jalankan tes dengan plugin eksternal dinonaktifkan bila environment pytest
   hang saat autoload:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q
```

Catat `run_id` dan koordinat crossing dari endpoint `/gates`; jangan memakai
folder log lama karena setiap `POST /reset` membuat sesi baru.

## Batas generalisasi

Pergeseran buoy dan dock yang moderat ditangani oleh koreksi visual serta
ultrasonik, tetapi topologi/urutan gerbang tetap dikonfigurasi. Arena yang
sepenuhnya berbeda membutuhkan pembaruan waypoint atau planner global; jangan
mengklaim generalisasi tanpa konfigurasi untuk topologi baru.
