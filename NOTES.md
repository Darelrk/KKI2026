# NOTES OPERASIONAL & PENYESUAIAN ASV KKI2026 (Raspberry Pi 5)

---

## 🚀 1. PETUNJUK MEMULAI (ALL-IN-ONE SHORTCUT)

Di Desktop Raspberry Pi 5 sudah tersedia **satu file shortcut utama**:
- **`/home/pi/Desktop/START_ASV.sh`** (atau jalankan `asv-start` di terminal).

### Cara Penggunaan:
1. Double-click **`START_ASV.sh`** pada Desktop.
2. Jendela Terminal akan terbuka dan secara otomatis me-restart 5 service backend:
   - `asv-dashboard.service` (Bridge API, WebSocket & Telemetri MAVLink - Port 8080)
   - `asv-stream.service` (Server Dual Camera MJPEG - Port 8081)
   - `asv-vision.service` (Inferensi YOLO Model `best.pt` - 3.5 FPS di CPU Pi 5)
   - `go2rtc.service` (WebRTC Ultra-Low Latency Engine - Port 1984)
   - `cloudflared.service` (Tunnel Publik `monitor-kapal-pora-pora.web.id`)
3. Terminal akan menampilkan **log real-time** & **ringkasan URL live**.
4. **Untuk mematikan seluruh backend**: Cukup tekan **`[ENTER]`** atau **`CTRL+C`** pada terminal tersebut.

### Perintah Terminal Tambahan:
- `asv-start` : Jalankan seluruh service (Interactive Foreground).
- `asv-stop`  : Hentikan seluruh service ASV sekaligus.
- `asv-status`: Cek status aktif service & hasil live API `/api/telemetry` & `/api/status`.

---

## 🌐 2. DAFTAR ENDPOINT & LIVE URL

- **Dashboard Vercel Live**: `https://kki-2026-dashboard.vercel.app`
- **Cloudflare Tunnel Public**: `https://monitor-kapal-pora-pora.web.id`
- **Backend API & WS Bridge (Local)**: `http://127.0.0.1:8080`
  - Telemetri MAVLink: `http://127.0.0.1:8080/api/telemetry`
  - WebSocket Telemetry Push: `ws://127.0.0.1:8080/ws/telemetry/default`
  - WebSocket Vision Push: `ws://127.0.0.1:8080/ws/vision/default`
- **Dual Camera Stream (Local)**: 
  - Kamera Atas (Surface): `http://127.0.0.1:8081/stream/atas` (`/dev/video0`)
  - Kamera Bawah (Underwater): `http://127.0.0.1:8081/stream/bawah` (`/dev/video2`)
- **WebRTC Stream Engine (Local)**: `http://127.0.0.1:1984`

---

## 🎮 3. PANDUAN MANUAL RC & PIXHAWK TELEMETRY

1. **Pengoperasian Manual RC (Tanpa QGroundControl/Mission Planner)**:
   - Remote Transmitter FlySky terhubung langsung ke Receiver ➔ Port `RCIN` Pixhawk.
   - Channel 1 (Kemudi Steering Servo) & Channel 3 (Gas Throttle ESC) dapat dikendalikan langsung pada mode `MANUAL` Pixhawk tanpa perlu membuka QGroundControl.

2. **Keamanan Pixhawk Safety Switch**:
   - Jika tombol **Safety Switch** Pixhawk berkedip merah, Pixhawk mengunci sinyal PWM Throttle ke ESC.
   - **Tekan tombol Safety Switch selama 3 detik** hingga lampu merah menyala **SOLID (tidak berkedip)** untuk mengaktifkan motor ESC.

3. **Catatan Sinyal Throttle & ESC Maju-Mundur**:
   - Parameter Pixhawk `RC3_TRIM` telah diset ke `1500.0` (posisi tengah/netral presisi).
   - Pastikan ESC dikalibrasi atau diatur pada mode **Forward/Reverse** (Maju-Mundur). Pada beberapa ESC mobil/kapal, fungsi mundur memerlukan *double-tap* stick throttle (tarik mundur 1x rem, lepas netral, tarik mundur 2x jalan mundur).

4. **Koneksi Auto-Reconnect MAVLink Resilien**:
   - Backend `asv_dashboard_backend/telemetry.py` akan mendeteksi terputus hanya dalam **1.0 detik** (`pixhawk_heartbeat_timeout = 1.0`).
   - Jika Pixhawk mengalami restart/brownout akibat lonjakan arus servo, backend akan mencoba menyambung ulang secara otomatis setiap **0.5 detik** (`pixhawk_reconnect_seconds = 0.5`) dan mendeteksi port USB baru (`/dev/ttyACM*` / `/dev/serial/by-id/*ArduPilot*`).

---

## 🛠️ 4. SCRIPT DIAGNOSTIK

- **Diagnostik Servo MAVLink**:
  ```bash
  /opt/asv-dashboard/.venv/bin/python /home/pi/KKI2026/servo_mavlink.py
  ```
- **Diagnostik Pixhawk Pre-Arm Safety**:
  ```bash
  /opt/asv-dashboard/.venv/bin/python /home/pi/KKI2026/pixhawk_prearm_diag.py
  ```
- **Monitoring Live RC Input & Servo Output**:
  ```bash
  /opt/asv-dashboard/.venv/bin/python -c "
  from pymavlink import mavutil; import time
  m = mavutil.mavlink_connection('/dev/ttyACM0', baud=115200)
  m.wait_heartbeat()
  m.mav.request_data_stream_send(m.target_system, m.target_component, 6, 10, 1)
  while True:
      msg = m.recv_match(type=['RC_CHANNELS','SERVO_OUTPUT_RAW'], blocking=True)
      if msg.get_type()=='RC_CHANNELS': print(f'RC  Ch1:{msg.chan1_raw}us | Ch3:{msg.chan3_raw}us')
      elif msg.get_type()=='SERVO_OUTPUT_RAW': print(f'OUT S1:{msg.servo1_raw}us | S3:{msg.servo3_raw}us')
  "
  ```

---

## 🧪 5. HASIL DIAGNOSIS THROTTLE MAVLINK (3 September 2026)

Pengujian fisik memastikan jalur throttle yang benar adalah `RC3` ke `MAIN OUT 3`:
- `RCMAP_THROTTLE=3`, `SERVO3_FUNCTION=70` (Throttle), `SERVO3_MIN/TRIM/MAX=1100/1500/1900`
- MAVLink `RC_CHANNELS_OVERRIDE` mengubah `RC_CHANNELS.chan3_raw` dan `SERVO_OUTPUT_RAW.servo3_raw` sesuai perintah.

Hasil pembanding pada mode `MANUAL` dan kondisi armed:

| Sumber | Urutan input | Output MAIN OUT 3 | Hasil fisik |
|---|---|---:|---|
| Radio | RC3 digerakkan melewati netral | 1380–1608 us | Motor bergerak |
| MAVLink | RC3=1799 langsung | hingga 1728 us | Motor diam/terpancing sesaat |
| MAVLink | RC3=1500 selama 1 detik, lalu RC3=1700 selama 2 detik | hingga 1644 us | Motor bergerak |

Kesimpulan: kanal, packing MAVLink, dan pin output sudah benar. ESC memerlukan
fase netral stabil sebelum throttle aktif. Kontrol software harus mengirim
RC3=1500 saat mulai mengambil override, baru meneruskan target throttle.

Backend menerapkan urutan tersebut untuk jalur remote dan autonomous melalui
`ASV_THROTTLE_NEUTRAL_PRIMING_SECONDS=1.0`. Nilai `0.0` menonaktifkan primer.
