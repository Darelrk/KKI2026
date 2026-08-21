# Simulator ASV KKI 2026

Simulator ini memodelkan kapal monohull single-azimuth-thruster untuk menguji
navigasi otonom sebelum kapal dibawa ke kolam. World berisi dua arena 30 x 30 m
yang saling dicerminkan (Arena A dan B), mengikuti susunan warna dan posisi
objek pada panduan KKI.

## Model kapal dan fisika

- LOA 1,065 m, beam 0,300 m, tinggi 0,755 m, massa 9,5 kg.
- Satu thruster di buritan; RC1 mengatur sudut azimuth maksimum +/-80 derajat
  dan RC3 mengatur dorongan.
- Gerak memakai rigid-body Webots: gaya diberikan pada posisi thruster, dengan
  buoyancy, drag air, inersia, pusat massa rendah, dan tumbukan fisik.
- RC3 1500 berarti netral/coast. Controller memakai pulsa dorong sesuai error
  kecepatan dan kembali netral jika kecepatan sudah cukup atau perintah hilang
  lebih dari satu detik. Thruster tidak terus-menerus diberi gas. Di tikungan
  docking tertentu, simulator dapat memakai pulsa reverse yang singkat untuk
  mengerem; ini mengasumsikan ESC reversible dan dapat dimatikan dengan
  `ASV_REVERSE_THRUST_ENABLED=0`.
- Lima sensor ultrasonik virtual bergaya HC-SR04: depan, depan-kiri,
  depan-kanan, kiri, dan kanan; rentang 0,05 sampai 5,00 m.

Model utama berada di `webots/protos/KKIBoat.proto`; fisika dan telemetri berada
di `webots/controllers/asv_sim_agent/asv_sim_agent.py`.

## Menjalankan

Jalankan semua perintah dari root repository `E:\KKI2026`.

Cara paling singkat (default Arena A, fixed-course + kamera/YOLO + sensor
ultrasonik):

```powershell
simulation\run_simulation.bat
```

Launcher akan membuka Webots bila belum aktif, menunggu controller pada port
8889, menjalankan bridge MAVLink, mereset Arena A, lalu memulai navigasi.
Istilah `sensor-only` hanya berarti kemajuan gate/marker tidak diambil dari
scorer internal Webots (ground truth); computer vision tetap aktif.
Webots baru dibuka dengan mode **Real-Time** otomatis. Jika jendela Webots
sudah terbuka sebelum launcher dijalankan dan masih pause, tekan tombol **Play**
sekali.

Untuk Arena B cukup gunakan:

```powershell
simulation\run_simulation.bat B
```

Mode scorer lama (menggunakan penghitung gate/marker dari Webots) hanya bila
diperlukan:

```powershell
simulation\run_simulation.bat A scorer
```

`sensor-only` masih boleh ditulis eksplisit (`A sensor-only`), tetapi tidak
lagi wajib. Setelah mengubah PROTO, world, atau controller Webots, tutup dan
buka ulang Webots agar model baru benar-benar dimuat.

Cara manual pada dua terminal:

```powershell
python simulation\sim_pixhawk_bridge.py
python -m simulation.vision_test `
  --camera http://127.0.0.1:8889/stream_raw.mjpg `
  --model model\best.pt `
  --endpoint tcp:127.0.0.1:5762 `
  --arena A --duration 0
```

Uji yang paling mendekati kapal nyata harus memakai mode tanpa penghitung
scorer Webots:

```powershell
python -m simulation.vision_test `
  --camera http://127.0.0.1:8889/stream_raw.mjpg `
  --model model\best.pt `
  --endpoint tcp:127.0.0.1:5762 `
  --arena A --sensor-only --duration 300 `
  --origin-lat -6.200000 --origin-lon 106.816666
```

`--sensor-only` tidak membaca `gate_count` atau `marker_count` dari Webots.
Progress gerbang dihitung dari crossing bidang gerbang menggunakan posisi lokal
GPS berturut-turut; marker memakai bidang pass yang sama. Parameter `origin-*`
harus diganti dengan titik referensi survei saat dipindahkan ke kolam.
Shortcut batch sensor-only: `simulation\run_simulation.bat` (Arena A) atau
`simulation\run_simulation.bat B` (Arena B).

Dependensi Python utama:

```powershell
python -m pip install ultralytics opencv-python pymavlink pyserial numpy
```

## Algoritma navigasi

Kontrol utama berjalan 20 Hz dan tidak menunggu latensi inferensi YOLO.

Kontrak lintasan Arena A bersifat deterministik: Gate 1--3 (slalom kanan),
blind left turn menuju koridor atas, Gate 4--7 (empat pasangan vertikal), blind
left turn menuju sisi kiri, Gate 8--10 (slalom kiri), marker biru lalu hijau,
kemudian jalur docking. Arena B hanya mencerminkan koordinat dan heading.

1. Waypoint dan heading memberi arah global serta urutan 10 gerbang. Setelah
   tiga pasang buoy pertama (Gate 3), controller mengerem singkat dan memberi
   pulsa kiri terbatas hanya untuk membuka blind spot. Begitu pasangan Gate 4
   terlihat, pulsa dilepas: setelah tinggi y=9,35 m kapal mengunci lajur
   masuk y=10 m sebelum Gate 4, lalu heading controller kembali mengambil
   alih dan YOLO hanya memberi trim kecil. Gate 4--7 diarahkan ke midpoint masing-masing
   (semuanya y=10 m), sehingga koreksi hanya mengikuti bearing geometris ke
   pasangan berikutnya; tidak ada kick/reverse tambahan di Gate 5. Setelah
   empat pasangan koridor (Gate 7), pola peek-and-handoff yang sama dipakai
   menuju Gate 8. Pola dicerminkan untuk Arena B. Pada mode `--sensor-only`,
   penghitung simulator tidak menjadi input
   kontrol: crossing bidang gerbang dihitung dari GPS lokal dan arah gerak,
   sementara kamera/YOLO dan ultrasonik tetap aktif sebagai sensor keselamatan.
2. YOLO mendeteksi `red_buoy` dan `green_buoy`. Model saat ini memang tidak
   memiliki kelas kotak marker.
3. Detektor warna-geometri terpisah mencari `blue_marker` dan `green_marker`.
   Ia memakai HSV + kontur persegi panjang, sehingga tidak perlu retraining
   YOLO dan tidak menganggap kotak sebagai buoy.
4. Matcher CV hanya menerima pasangan yang masuk akal: merah di kiri, hijau di
   kanan, tinggi/ukuran sebanding, dan kedalaman gambar serupa. Ini mencegah
   buoy dari dua gerbang berbeda dipasangkan.
5. Titik tengah pasangan memberi koreksi PWM lokal yang dihaluskan, dibatasi,
   dan kedaluwarsa dalam 0,55 detik. Menjelang garis gerbang, otoritas CV
   dikurangi agar tidak membatalkan antisipasi belok monohull.
6. Ketika marker aktif terlihat, lapisan visual marker memberi counter-steer
   menjauhi kotak dan membatasi throttle sampai kotak lewat. Waypoint sisi aman
   tetap menjadi panduan utama; detektor ini hanya koreksi jarak dekat.
7. Sensor ultrasonik memperlambat kapal mulai 1,20 m. Pada halangan depan
   0,55 m, controller memberi pulsa escape kecil sambil mengarahkan azimuth ke
   sisi yang lebih lapang; bila kapal benar-benar terhenti selama 0,80 detik,
   satu pulsa reverse pendek dipakai untuk melepas halangan sebelum kembali ke
   escape maju. Di basin marker, geofence mulai memulihkan kapal pada jarak
   2,4 m dari dinding agar momentum tidak membawa hull ke pembatas. Pelepasan
   hysteresis terjadi pada 0,85 m.
8. Setelah Gate 10, kapal wajib melintasi bidang marker biru kemudian hijau
   secara berurutan. Kotak marker adalah rintangan fisik: guidance melewati
   sisi kiri-bawah kotak biru lalu sisi kanan/timur kotak hijau (dengan lead
   sedikit ke utara); scoring memakai bidang pass yang sama. Setelah hijau,
   kapal melewati staging
   utara-timur lalu tiga waypoint return yang selalu maju.
9. Docking dinyatakan selesai hanya setelah 10/10 gerbang dan 2/2 marker valid,
   kapal mengikuti entry dock sambil menyelaraskan heading, lalu bertahan 3
   detik pada jarak <=0,75 m, heading error <=15 derajat, dan kecepatan
   <=0,15 m/s.

Waypoint adalah panduan kasar, bukan satu-satunya sumber kemudi. Karena koreksi
lokal memakai kamera dan ultrasonik, pergeseran posisi buoy yang moderat masih
dapat ditangani. Jika topologi, urutan gerbang, atau ukuran arena berubah total,
konfigurasi waypoint/arena tetap harus diperbarui; sistem tidak mengklaim dapat
menebak lintasan baru secara otomatis.

## Kontrak transfer ke kapal nyata

Simulator ini menguji tiga lapisan yang sama dengan perangkat keras: (1)
estimasi keadaan dari GPS/IMU/kecepatan/ultrasonik dan kamera, (2) finite-state
mission controller untuk gerbang, marker, dan docking, serta (3) pemetaan
aktuator RC1/RC3 ke azimuth dan thrust. `gate_count` dan `marker_count` hanya
untuk scoring/debug saat mode biasa; keduanya sengaja diputus pada
`--sensor-only` agar keberhasilan tidak berasal dari ground truth tersembunyi.

Throttle bukan gas konstan: target speed diturunkan saat heading error besar,
ultrasonik dekat, atau deteksi buoy/marker dekat; PWM kembali netral ketika
hull sudah melaju atau telemetri stale. Jika posisi/heading tidak diperbarui
melewati timeout, autopilot mengirim RC1/RC3 netral sebagai fail-safe.

Sebelum ekspor, identifikasi dulu tiga parameter di kolam: PWM netral ESC,
kecepatan terhadap PWM, dan laju yaw terhadap sudut azimuth/thrust. Fisika
Webots saat ini adalah model uji (bukan bukti performa kapal), sehingga angka
PWM dan gain harus dituning ulang dari log manuver nyata. Kriteria penerimaan
minimum: 10/10 gerbang valid, 2/2 marker valid, tidak menyentuh buoy/dinding,
docking stabil 3 detik, tidak ada stale-telemetry escape, dan hasil tetap sama
pada Arena A/B serta beberapa offset posisi awal.

Parameter fisika simulator dapat diubah tanpa mengedit controller melalui
`ASV_MAX_AZIMUTH_DEG` (default 80 derajat), `ASV_MAX_THRUST_N`, `ASV_MAX_REVERSE_THRUST_N`, dan
`ASV_REVERSE_THRUST_ENABLED`. Nilai tersebut adalah parameter identifikasi,
bukan angka yang boleh langsung diasumsikan sama dengan kapal lapangan.

## Arena dan titik penting

Arena A memakai pusat gerbang berikut:

```text
G1 (11,-6) -> G2 (9,0) -> G3 (11,6)
-> G4 (6,10) -> G5 (2,10) -> G6 (-2,10) -> G7 (-6,10)
-> G8 (-11,6) -> G9 (-9,0) -> G10 (-11,-6)
-> marker biru (-9.7,-8.7), pass kiri (-11.2,-9.2)
-> marker hijau (-6.9,-11.9), pass kanan (-5.55,-11.25)
-> staging (-4.8,-10.8) -> return (1,-8.5) -> (7,-8.3)
-> entry dock (11.5,-10.45)
-> dock biru vertikal (11.5,-13.0)
```

Arena B merupakan pencerminan terhadap `x=15`; start A `(11.1,-11.5)`, start
B `(18.9,-11.5)`, dan dock B `(18.5,-13.0)`. Kotak biru dan hijau pada bagian
bagian bawah adalah checkpoint fisik yang harus dilewati tanpa menyentuhnya,
bukan dock; Arena B menggunakan posisi cerminnya.
Dock akhir berbentuk vertikal dan dijaga tiga buoy biru: di sisi kiri untuk
Arena A dan sisi kanan untuk Arena B.

## Monitoring dan evaluasi

- Stream kamera vision mentah: `http://127.0.0.1:8889/stream_raw.mjpg`
- Stream kamera dashboard dengan HUD: `http://127.0.0.1:8889/stream.mjpg`
- Status: `http://127.0.0.1:8889/status`
- Detail gerbang: `http://127.0.0.1:8889/gates`
- Reset Arena A: `POST http://127.0.0.1:8889/reset?arena=A`
- Reset Arena B: `POST http://127.0.0.1:8889/reset?arena=B`

Jalankan evaluator setelah navigasi aktif:

```powershell
python simulation\evaluate_batch.py --arena A --duration 300
```

Setiap reset membuat folder `simulation/logs/run_<timestamp>/`. Bukti utama
terdapat pada `gate_scoring.json`, `summary_report.md`, log sentuhan buoy,
log dinding, dan track telemetri. Sebuah run bersih harus memenuhi 10/10 gerbang,
2/2 marker, 0 missed, 0 sentuhan buoy, 0 sentuhan dinding, dan `docked=true`.

Run sebelum koreksi marker/dock memakai tujuan lama dan tidak boleh dipakai
sebagai bukti penerimaan rute ini. Jalankan evaluator Arena A dan B kembali
setelah restart Webots untuk menghasilkan bukti dengan kontrak baru.

## File penting

- `vision_route.py`: waypoint, speed governor, PD heading, CV gate centering,
  ultrasonic avoidance, dan docking.
- `vision_test.py`: inferensi YOLO, autopilot 20 Hz, MAVLink, UI, dan log.
- `sim_pixhawk_bridge.py`: jembatan telemetri/RC Webots ke MAVLink.
- `webots/worlds/kki_pool_arena.wbt`: Arena A/B dan posisi objek.
- `evaluate_batch.py`: reset dan penilaian run.

Nama telemetri resmi untuk sensor adalah `ultrasonic`. Alias `sonar` masih
dikirim sementara hanya untuk kompatibilitas dengan dashboard/script lama.
