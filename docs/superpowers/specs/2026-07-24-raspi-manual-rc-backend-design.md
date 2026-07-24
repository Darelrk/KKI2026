# Backend Raspberry Pi Manual RC + Model Monitoring

**Tanggal:** 2026-07-24  
**Status:** Disetujui berdasarkan kontrak `2026-07-23-manual-rc-dashboard-design.md` dan permintaan backend Raspi.

## Tujuan

Menjalankan YOLO di Raspberry Pi untuk monitoring kamera dan publish metadata/frame ke bridge ketika mode `--manual-rc` aktif, tanpa membuka Pixhawk dari proses vision dan tanpa mengirim perintah MAVLink. Transmitter RC tetap menjadi satu-satunya sumber kendali kapal.

## Baseline yang diselaraskan

- `main` dan `origin/main` sama-sama berada pada commit `1416008`.
- Commit terbaru memperbaiki inisialisasi koneksi Pixhawk, pemindaian baud rate, deteksi port, dan pelepasan port serial.
- Perubahan vision/throttle yang masih ada di working tree dipertahankan dan menjadi bagian dari integrasi backend ini; tidak ditimpa atau di-reset.

## Arsitektur

```text
--manual-rc:
  Kamera -> YOLO -> BridgeFramePublisher -> ASV bridge -> Dashboard
             |
             +-> preview/log lokal

Telemetry opsional terpisah:
  Pixhawk -> PixhawkTelemetryReader (read-only) -> /api/telemetry -> Dashboard

Kontrol:
  Transmitter RC -> Pixhawk
```

`vision_test.py` memiliki dua jalur eksplisit:

1. Mode default tetap memakai `PixhawkLink` untuk perilaku vision-control yang sudah ada.
2. Mode `--manual-rc` tidak membuat `PixhawkLink`, sehingga tidak memuat koneksi serial/MAVLink, tidak memanggil `arm_vehicle()`, tidak mengubah mode, dan tidak mengirim `RC_CHANNELS_OVERRIDE`.

Bridge telemetry tetap merupakan reader read-only yang sudah ada. Jika endpoint serial yang sama dipakai QGroundControl/Mission Planner, `ASV_PIXHAWK_ENABLED` harus dimatikan atau diarahkan ke jalur telemetry terpisah agar tidak terjadi perebutan port.

## Perubahan kode

- Tambah flag `--manual-rc` pada `vision_test.py`.
- Pisahkan pembuatan `PixhawkLink` melalui guard yang dapat diuji tanpa hardware.
- Pada mode manual RC:
  - tetap membuka kamera, menjalankan model, menggambar deteksi, menulis log, dan mengirim metadata/frame ke bridge;
  - memakai label runtime `RC_MANUAL` hanya sebagai status monitoring lokal;
  - mengisi nilai steering/throttle lokal dengan neutral sebagai nilai non-command;
  - tidak memanggil method apa pun pada `PixhawkLink` karena objek tersebut tidak dibuat;
  - cleanup tidak mengirim release override atau arm/disarm.
- Error dependency manual RC tidak mensyaratkan `pymavlink`/`pyserial`; mode kontrol tetap memberi pesan dependency lengkap.

- Lifecycle receive loop WebSocket dimiliki oleh handler dan task publisher
  dibatalkan deterministik saat client disconnect; payload dan kontrak endpoint
  tetap tidak berubah.
- Tidak mengubah schema dashboard, endpoint bridge, atau kontrak telemetry read-only.

## Keamanan dan failure handling

- `--manual-rc` tidak boleh membuka `/dev/ttyACM*`, `/dev/ttyUSB*`, `COM*`, TCP MAVLink, atau UDP MAVLink.
- Tidak boleh ada eksekusi `ARMING_CHECK`, `MAV_CMD_COMPONENT_ARM_DISARM`, `RC_CHANNELS_OVERRIDE`, atau method Pixhawk lain dalam jalur manual RC.
- Kegagalan bridge hanya memengaruhi publish metadata/frame; tidak memengaruhi kontrol RC.
- Kegagalan kamera/model tetap menghentikan proses vision secara normal dan tidak mengirim command cleanup ke Pixhawk pada mode manual RC.
- Telemetry bridge tetap read-only dan boleh unavailable tanpa membuat model monitoring mengambil alih kontrol.

## Verifikasi

Tanpa hardware:

```bash
python -m pytest -q tests/test_manual_rc.py tests/test_vision_route.py tests/test_vision_capture.py tests/test_vision_publisher.py tests/test_telemetry.py tests/test_dashboard_backend.py
python -m compileall -q vision_test.py vision_route.py asv_dashboard_backend tests
python vision_test.py --help
```

Acceptance minimum:

- Parser menerima `--manual-rc`.
- Guard pembuatan Pixhawk mengembalikan `None` pada mode manual dan tidak menginstansiasi `PixhawkLink`.
- Test kontrol manual tidak menemukan panggilan arm/disarm/override.
- Test vision/throttle existing tetap lulus.
- Bridge telemetry existing tetap lulus.

## Di luar cakupan

- Mengubah firmware ArduPilot, parameter safety, mode kapal, atau mapping RC.
- Mengirim command dari dashboard.
- Membuat service vision otomatis yang menyalakan motor/propulsi.
- Mengubah Supabase schema atau API dashboard.
