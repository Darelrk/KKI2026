# Remote Dashboard Low-Latency Control Design

**Tanggal:** 2026-08-28  
**Status:** Design spec  
**Scope:** Dashboard remote baru, kontrak control WebSocket, dan routing deployment; belum mengubah source implementasi.

## 1. Problem dan tujuan

Dashboard `dashboard/` saat ini adalah dashboard operasional/model yang sudah berjalan. Kebutuhan baru adalah workspace remote terpisah untuk operator yang memerlukan permukaan kendali sekecil mungkin dengan jalur yang jujur dan rendah latensi:

1. satu stream kamera permukaan mentah dari Go2RTC, dengan source `atas`;
2. dua slider direct PWM: `steering_pwm` dan `throttle_pwm`.

UI remote **hanya** merender satu permukaan kamera mentah dan dua slider tersebut. UI tidak merender telemetry, status, latency, sequence, kamera underwater, model/YOLO, overlay, vision metadata, autonomy toggle, acknowledgement, rejection, atau data lain. Penanganan kegagalan koneksi/input boleh memakai perilaku native browser yang diperlukan untuk mencegah operasi tidak aman, misalnya menghentikan input dan membuat slider disabled; UI tidak menambahkan banner, toast, angka, atau indikator status sendiri.

Target internal adalah waktu dari input operator di browser sampai command diterima backend FastAPI **≤100 ms** pada kondisi jaringan yang dikendalikan. Internet publik dan rute Cloudflare tidak dapat diberi SLA 100 ms; target ini diukur melalui test harness/log, bukan ditampilkan di UI, dan tidak boleh dipakai untuk melemahkan deadman atau guard keselamatan.

Keputusan arsitektur utama:

- remote dashboard adalah app/workspace baru di repo yang sama;
- app tersebut dideploy sebagai project/domain Vercel terpisah;
- backend tetap satu `asv_dashboard_backend` pada Raspberry Pi;
- backend tetap memiliki satu koneksi Pixhawk;
- backend dan stream tetap melewati Cloudflare Tunnel Pora Pora yang sama;
- asumsi hostname publik remote adalah `https://remote.monitor-kapal-pora-pora.web.id`;
- control channel adalah `wss://remote.monitor-kapal-pora-pora.web.id/ws/control/default`;
- video tidak melewati Vercel Function dan tidak melewati channel control;
- remote dashboard tidak menjalankan YOLO, model inference, overlay model, atau vision metadata.

## 2. Scope

### 2.1 Termasuk

- Workspace frontend baru `remote-dashboard/` dengan package dan deployment Vercel mandiri.
- Satu player kamera permukaan raw Go2RTC untuk source `atas`; WebRTC adalah jalur utama dan raw MJPEG adalah fallback dari stream yang sama.
- Tepat dua input accessible bertipe range untuk direct PWM `steering_pwm` dan `throttle_pwm`, masing-masing integer valid **1000..2000**.
- Persistent WebSocket `/ws/control/{asv_id}` untuk command, acknowledgement, reconnect, sequence, timestamp, dan latest-command semantics; data protocol tersebut boleh tetap internal dan tidak dirender.
- Deadman backend 500 ms memakai waktu monotonic server.
- Pelepasan override segera ketika control WebSocket disconnect, superseded, expired, backend berhenti, atau guard Pixhawk gagal.
- Pemeliharaan validasi PWM, expiry, heartbeat Pixhawk, observed flightmode `MANUAL`, pilot-input guard, dan actuator safety yang sudah ada.
- CORS HTTP dan pemeriksaan `Origin` WebSocket yang membatasi browser remote tanpa menyebutnya sebagai autentikasi.
- Routing hostname remote pada tunnel yang sama hanya untuk control WSS dan path Go2RTC yang diperlukan oleh source `atas`.
- Kontrak pengukuran latency internal, acceptance criteria, rollout, dan rollback.

### 2.2 Tidak termasuk

- Penggantian atau penghapusan dashboard lama `dashboard/`.
- Backend cloud baru, Vercel API route, Vercel Function sebagai proxy, database realtime, atau Supabase pada live control path.
- Koneksi Pixhawk kedua, proses MAVLink di browser, arm/disarm, perubahan mode Pixhawk, parameter write, mission upload, atau autonomous runner baru.
- Kamera underwater `bawah` pada remote app, telemetry, status, latency, sequence, model/YOLO inference, vision metadata, canvas overlay, acknowledgement/rejection display, autonomy toggle, atau panel/data UI lain.
- Perubahan firmware ArduPilot, konfigurasi mekanik kapal, atau perilaku autonomous navigation.
- Implementasi source, test, build, atau perubahan pada `simulation/`, `model/`, `worlds/`, dan perubahan pengguna yang sudah ada.
- Autentikasi aplikasi. Ketiadaan autentikasi adalah keputusan risiko yang disengaja dan dijelaskan pada bagian keamanan.

## 3. Invarian sistem yang harus dipertahankan

1. `PixhawkTelemetryReader` adalah satu-satunya pemilik koneksi MAVLink/Pixhawk pada backend. Handler WebSocket hanya memvalidasi dan menyerahkan command ke reader tersebut.
2. `BridgeState.control_mode` (`MANUAL` atau `AUTONOMOUS`) adalah mode kontrol aplikasi, bukan flight mode yang dibaca dari Pixhawk.
3. `PixhawkTelemetryReader._mode` tetap merupakan observed flight mode ArduPilot. RC override remote hanya boleh diterapkan saat nilainya tepat `MANUAL`.
4. Remote dashboard tidak mengubah `BridgeState.control_mode`, tidak memanggil autonomous runner, dan tidak membuka koneksi Pixhawk.
5. `POST /api/control/actuator` tetap menjadi jalur existing yang memakai token Pi-only untuk publisher/model. Remote WebSocket tidak memakai endpoint POST tersebut dan tidak membawa token ke browser.
6. Command yang disimpan hanya command terbaru; tidak ada antrean histori PWM yang dapat diputar terlambat.
7. Jika salah satu guard keselamatan gagal, output override dilepas sehingga transmitter RC/Pixhawk memperoleh kembali otoritas sesuai perilaku existing.
8. Data ack, rejection, sequence, timestamp, deadman, dan latency hanya menjadi bagian protokol/log/test internal. Tidak ada komponen remote yang merendernya.

## 4. Arsitektur dan topologi

```text
                           project Vercel terpisah
┌───────────────────────────────────────────────────────────────┐
│ remote-dashboard/                                            │
│  satu raw surface player (`atas`)       dua slider PWM       │
└──────────────────────┬───────────────────────┬──────────────┘
                       │ HTTPS/WSS Go2RTC       │ WSS control
                       │ /api/ws?src=atas      │ /ws/control/default
                       ▼                        ▼
┌───────────────────────────────────────────────────────────────┐
│ Cloudflare Tunnel Pora Pora yang sama                         │
│ hostname remote.monitor-kapal-pora-pora.web.id                │
└──────────────────────┬───────────────────────┬──────────────┘
                       │                       │
                       ▼                       ▼
                 Go2RTC :1984           FastAPI :8080
                 /api/ws                /ws/control/{id}
                 /api/webrtc                   │
                 /api/stream.mp4               │
                 /api/stream.mjpeg?src=atas  ▼
                       │                 satu Pixhawk MAVLink
                       ▼                 PixhawkTelemetryReader
                 raw WebRTC/MJPEG
                 tanpa YOLO/overlay
```

Host lama `monitor-kapal-pora-pora.web.id` tetap melayani dashboard lama sesuai konfigurasi existing. Host remote hanya menambahkan ingress pada tunnel yang sama; tidak ada tunnel, FastAPI process, atau koneksi Pixhawk kedua.

Video dan kontrol adalah dua jalur terpisah:

- Control: browser → WSS → Cloudflare → FastAPI → latest command → `PixhawkTelemetryReader` → `RC_CHANNELS_OVERRIDE` bila semua guard lolos.
- Video: browser → Go2RTC signaling WSS/HTTPS → Cloudflare → Go2RTC → satu stream source `atas`; jika WebRTC gagal, player yang sama beralih ke raw MJPEG. Jalur ini tidak mengirim command dan tidak menerima metadata vision.

Endpoint status/telemetry FastAPI bukan bagian dari remote app dan tidak dirutekan pada host remote. Endpoint tersebut tetap boleh dipakai secara internal atau oleh host dashboard lama sesuai konfigurasi existing.

## 5. Tanggung jawab component dan file

### 5.1 Backend existing

| File | Tanggung jawab pada desain ini |
|---|---|
| `asv_dashboard_backend/config.py` | Menambah konfigurasi eksplisit `remote_control_enabled` dari `ASV_REMOTE_CONTROL_ENABLED` dengan default aman `false`, serta timeout remote tetap `0.5` detik dari `ASV_REMOTE_COMMAND_TIMEOUT`. Jika remote control diaktifkan tanpa `ASV_PIXHAWK_ENABLED=true`, konfigurasi ditolak. `cors_origins` tetap explicit, tanpa wildcard. Timeout heartbeat existing tidak diperlebar. |
| `asv_dashboard_backend/control.py` (baru) | Menjadi modul kecil untuk schema Pydantic strict (`RemoteControlCommand`, `ControlAck`, `ControlError`) dan registry satu sesi control aktif per `asv_id`. Modul ini tidak mengimpor `pymavlink`, tidak membuka socket Pixhawk, dan tidak menerapkan PWM. |
| `asv_dashboard_backend/state.py` | Tetap menjadi pemilik status live dan `control_mode` aplikasi. Jika registry sesi ditempatkan di sini pada implementasi, ia hanya menyimpan identitas sesi/latest lease; ia tidak mengirim MAVLink. `control_mode` tidak digabung dengan `_mode` Pixhawk. |
| `asv_dashboard_backend/main.py` | Menambahkan adapter `@app.websocket("/ws/control/{asv_id}")`, memeriksa ASV id dan Origin, menerima text JSON, memvalidasi melalui schema, mengirim ack/error internal, dan memanggil method reader. Route ini tidak membuat reader atau koneksi baru. Route HTTP read-only existing tetap dipakai untuk dashboard lama/internal, bukan remote app. |
| `asv_dashboard_backend/telemetry.py` | Tetap memiliki satu `PixhawkTelemetryReader`. Menambahkan penyimpanan command remote/latest owner dan method clear/release yang aman. Loop existing tetap memeriksa umur command, heartbeat, observed `MANUAL`, pilot-input guard, feature flag, dan koneksi sebelum mengirim override. Pelepasan disconnect harus dapat dipanggil segera dan thread-safe. |
| `asv_dashboard_backend/vision_publisher.py` | Tidak diubah oleh remote control. Publisher model tetap memakai `POST /api/control/actuator` dan `ASV_CONTROL_TOKEN`; lane actuator existing tidak diganti menjadi WebSocket browser. |
| `tests/test_remote_control_protocol.py` (baru) | Test schema strict, tipe integer, batas PWM, sequence, timestamp, ack/error, dan latest-command/session rules tanpa hardware. |
| `tests/test_dashboard_backend.py` | Test route WSS, ASV mismatch, Origin allowlist, feature-disabled response, ack timestamp, no POST-per-input contract, dan coexistence dengan endpoint existing. |
| `tests/test_telemetry.py` | Test expiry 500 ms memakai monotonic clock, immediate release saat clear/disconnect, heartbeat/flightmode/pilot guard, dan bukti command remote menggunakan reader yang sama tanpa koneksi Pixhawk kedua. |

### 5.2 Deployment Raspberry Pi dan tunnel

| File | Tanggung jawab pada desain ini |
|---|---|
| `deploy/raspberry-pi/asv-dashboard.env.example` | Mendokumentasikan `ASV_REMOTE_CONTROL_ENABLED=false` sebagai default aman, `ASV_REMOTE_COMMAND_TIMEOUT=0.5`, `ASV_PIXHAWK_ENABLED=true` hanya pada host yang memang akan dikendalikan, serta `ASV_CORS_ORIGINS` berisi origin Vercel remote yang sebenarnya dan origin development yang diperlukan saja. `ASV_CONTROL_TOKEN` tetap rahasia di Pi untuk jalur model dan tidak pernah disalin ke Vercel. |
| `deploy/raspberry-pi/cloudflared-config.example.yml` | Menambahkan route host `remote.monitor-kapal-pora-pora.web.id` hanya ke FastAPI untuk `/ws/control/.*` dan ke Go2RTC untuk `/api/ws`, `/api/webrtc`, `/api/stream.mp4`, serta `/api/stream.mjpeg?src=atas`. Route lain berakhir 404 pada host remote. Upgrade WebSocket harus diteruskan. Ingress host lama tetap ada. |
| `deploy/raspberry-pi/asv-dashboard.service` | Tetap menjalankan satu `uvicorn asv_dashboard_backend.main:app` pada port 8080. Tidak ada unit service baru untuk remote control dan tidak ada service Pixhawk kedua. |
| service Go2RTC existing | Tetap menjadi pemilik media pada port lokal 1984. Konfigurasi source `atas` harus sudah menghasilkan raw Go2RTC/WebRTC/MJPEG sebelum remote UI diaktifkan. |

### 5.3 Workspace frontend baru

`remote-dashboard/` adalah package mandiri yang ditambahkan ke root npm workspace. Ia boleh memakai React/Vite dan dependency yang sudah dipakai repo, tetapi tidak mengimpor komponen mission/model dari `dashboard/`.

| File | Tanggung jawab pada desain ini |
|---|---|
| `remote-dashboard/package.json` | Script dev/build/preview/test/typecheck untuk package remote dan dependency minimum frontend. Tidak ada proxy control atau server runtime yang menyimpan token. |
| `remote-dashboard/vite.config.ts` dan `remote-dashboard/vercel.json` | Build static untuk project Vercel terpisah dan fallback SPA. Browser memanggil hostname tunnel secara langsung; tidak ada serverless relay. |
| `remote-dashboard/src/main.tsx` dan `remote-dashboard/src/app.tsx` | Bootstrap app, membaca `VITE_REMOTE_BACKEND_ORIGIN` dan `VITE_REMOTE_ASV_ID`, lalu merender satu player source `atas` dan tepat dua slider. Default ASV id adalah `default`. Tidak ada fetch status/telemetry. |
| `remote-dashboard/src/lib/control-protocol.ts` | Zod schema/type yang sama dengan Pydantic control protocol. Tidak mengubah nilai PWM menjadi normalized intent dan tidak melakukan network I/O. |
| `remote-dashboard/src/lib/control-channel.ts` | Pemilik satu WebSocket control persisten: connect, close, reconnect backoff, sequence, coalescing command terbaru, refresh deadman ≤200 ms ketika slider sedang dipegang, ack/error internal, dan pengukuran RTT untuk test/log. Tidak memakai `fetch` POST untuk input dan tidak mengekspos data protocol ke DOM. |
| `remote-dashboard/src/lib/video-urls.ts` | Menurunkan URL Go2RTC dari satu origin remote untuk source `atas`, termasuk WSS signaling dan raw MJPEG fallback. Tidak mengetahui control protocol. |
| `remote-dashboard/src/components/remote-control-panel.tsx` | Merender tepat dua input range accessible untuk steering/throttle direct PWM 1000..2000. Tidak ada tombol enable, autonomy toggle, ack/rejection, status, atau angka data lain. `enabled` hanya field protocol internal selama pointer/keyboard engagement aktif. |
| `remote-dashboard/src/components/remote-video-player.tsx` | Merender satu player raw Go2RTC/WebRTC untuk source `atas`; ketika gagal, player WebRTC dibersihkan dan diganti raw MJPEG `atas`. Tidak membuat canvas overlay, tidak memanggil `/ws/vision`, dan tidak membaca vision metadata. |
| `remote-dashboard/src/components/remote-app.test.tsx`, `remote-dashboard/src/lib/control-protocol.test.ts`, dan `remote-dashboard/src/lib/control-channel.test.ts` | Test kontrak bahwa DOM hanya memiliki satu media surface dan dua slider, protocol/direct PWM, no-POST, refresh/expiry/reconnect, ack/error internal, serta native disable saat koneksi/input gagal. Test video memastikan request hanya ke Go2RTC raw path source `atas` dan tidak ada metadata/overlay. |
| `package.json` root | Menambahkan `remote-dashboard` ke npm workspaces dan script package-level bila diperlukan. `dashboard/` tetap menjadi workspace/package lama. Lockfile hanya berubah sebagai konsekuensi metadata workspace saat implementasi, bukan bagian dari desain atau commit ini. |

Tidak ada `live-data.ts` atau `remote-status-strip.ts` pada remote workspace. Komponen yang merender status/telemetry/latency/sequence atau kamera kedua berada di luar desain ini.

## 6. Kontrak HTTP, WebSocket, dan video

### 6.1 Path media remote

Remote app tidak memanggil endpoint FastAPI status/telemetry/health. Ia hanya memakai path Go2RTC yang diperlukan untuk satu source surface `atas` melalui `https://remote.monitor-kapal-pora-pora.web.id`:

| Method/path | Pemilik | Fungsi |
|---|---|---|
| WSS `/api/ws?src=atas` | Go2RTC :1984 | Signaling WebRTC untuk player source `atas`. |
| HTTP `/api/webrtc` | Go2RTC :1984 | Negosiasi HTTP bila diperlukan oleh kontrak Go2RTC existing untuk source `atas`. |
| HTTP `/api/stream.mp4` | Go2RTC :1984 | Compatibility path media Go2RTC bila diperlukan oleh player surface. |
| HTTP `/api/stream.mjpeg?src=atas` | Go2RTC :1984 | Fallback raw MJPEG untuk source `atas`. |

Tidak ada request remote ke `/healthz`, `/api/status`, `/api/telemetry`, `PUT /api/control/mode`, `POST /api/control/actuator`, `/api/vision/metadata`, `/ws/vision`, atau path media source lain. Response media ditangani sebagai media; tidak ada schema metadata atau data tambahan yang dirender.

### 6.2 Control WebSocket

URL:

```text
wss://remote.monitor-kapal-pora-pora.web.id/ws/control/default
```

`default` adalah nilai `ASV_ID` existing dan route harus mencocokkan id secara tepat.

Setelah upgrade berhasil, browser mengirim object JSON berikut. Pydantic dan Zod menggunakan object strict; field ekstra, field hilang, string untuk integer, float non-integer, `NaN`, dan nilai di luar batas ditolak.

```json
{
  "type": "control",
  "seq": 42,
  "client_sent_at_ms": 1787923200123,
  "steering_pwm": 1490,
  "throttle_pwm": 1550,
  "enabled": true
}
```

Kontrak field:

- `type`: literal `"control"`.
- `seq`: integer positif, monotonically increasing per sesi, maksimum `9007199254740991` agar aman di JavaScript.
- `client_sent_at_ms`: integer epoch milliseconds dari `Date.now()`, non-negatif, maksimum `9007199254740991`. Nilai ini hanya untuk measurement dan tidak menjadi sumber expiry.
- `steering_pwm`: integer `1000..2000` inclusive.
- `throttle_pwm`: integer `1000..2000` inclusive.
- `enabled`: `true` untuk meminta override remote, `false` untuk melepasnya. Nilai PWM tetap harus valid ketika `enabled=false` agar satu schema berlaku untuk semua frame.

Ack backend dikirim untuk setiap command yang lolos parsing JSON/schema:

```json
{
  "type": "ack",
  "seq": 42,
  "accepted": true,
  "reason": null,
  "client_sent_at_ms": 1787923200123,
  "server_received_at_ms": 1787923200156
}
```

`accepted=true` berarti command valid dan masuk ke latest-command slot setelah ingress safety gate; ini **bukan** klaim bahwa MAVLink sudah diterapkan pada aktuator. `server_received_at_ms` diambil segera setelah frame diterima/validasi selesai menggunakan UTC epoch milliseconds untuk measurement dan audit. Ack dan reason diproses internal oleh channel dan tidak dirender oleh remote UI. `accepted=false` memakai schema sama dengan `reason` berikut:

- `stale_sequence`: `seq` tidak lebih besar dari sequence terakhir sesi;
- `remote_control_disabled`: feature flag remote false;
- `runtime_mode_autonomous`: mode aplikasi bukan `MANUAL`;
- `pixhawk_unavailable`: reader tidak memiliki koneksi/heartbeat yang valid;
- `flightmode_not_manual`: observed Pixhawk flight mode bukan `MANUAL`;
- `pilot_input_active`: input transmitter terdeteksi pada window guard existing;
- `superseded`: sesi lama telah digantikan sesi baru.

Command `enabled=false` yang schema-valid selalu membersihkan latest remote command dan meminta release; release tidak menunggu heartbeat baru. Jika command valid tetapi guard tidak aman, backend tidak menyimpannya sebagai command aktif.

Payload untuk kesalahan yang tidak memiliki `seq` valid adalah:

```json
{
  "type": "error",
  "code": "invalid_json",
  "message": "control frame must be valid JSON"
}
```

`code` terbatas pada `invalid_json`, `invalid_message`, dan `origin_not_allowed`. Pesan error tidak boleh memuat secret atau stack trace. Setelah error schema, koneksi tetap boleh hidup agar client dapat mengirim frame valid berikutnya; setelah Origin/ASV/feature gate handshake ditolak, koneksi ditutup. Semua ack/error tetap internal dan tidak menjadi elemen atau teks UI.

### 6.3 Sesi, ownership, dan latest-command semantics

- Satu `asv_id` hanya memiliki satu control session aktif.
- Koneksi baru yang sudah melewati ASV/Origin/feature checks menggantikan sesi lama. Sesi lama ditutup dengan close code aplikasi `4001` (`superseded`) dan latest command miliknya dilepas sebelum sesi baru menerima control.
- `seq` dimulai dari 1 pada setiap sesi dan harus meningkat ketat. Sequence lama tidak pernah mengubah slot.
- Backend menyimpan satu command terbaru beserta `session_id`, `seq`, dan waktu monotonic penerimaan. Tidak ada queue per input.
- Tidak ada kontrol enable terpisah di UI. Saat operator mulai menekan/menahan salah satu slider dengan pointer atau keyboard, channel mengirim `enabled=true`; selama engagement aktif, channel mengirim refresh paling lambat setiap 200 ms. Command yang belum terkirim diganti dengan nilai terbaru, bukan diantrikan.
- `pointerup`, `pointercancel`, pelepasan tombol keyboard, kehilangan fokus, `visibilitychange` ke hidden, unmount, atau error input mengirim `enabled=false`, menghentikan refresh, dan meminta release. WebSocket `error`/`close` juga menghentikan refresh dan membuat kedua slider disabled memakai state native browser agar tidak ada input yang tampak aktif tanpa jalur kendali.
- Ack, rejection, sequence, timestamp, dan alasan disabled tidak ditampilkan; hanya state disabled native yang boleh terlihat bila diperlukan untuk keselamatan.

### 6.4 Raw video

Remote app hanya membuka satu signaling/player Go2RTC untuk surface (`atas`):

```text
wss://remote.monitor-kapal-pora-pora.web.id/api/ws?src=atas
```

Handshake memakai kontrak Go2RTC existing:

```json
{ "type": "webrtc/offer", "value": "<sdp>" }
{ "type": "webrtc/answer", "value": "<sdp>" }
{ "type": "webrtc/candidate", "value": "<candidate>" }
```

Player memakai video receive-only, `autoplay`, `playsInline`, dan `muted`. Jika koneksi WebRTC tidak usable dalam tiga detik atau masuk state error/close, player menutup resource-nya dan beralih ke satu raw MJPEG element:

```text
https://remote.monitor-kapal-pora-pora.web.id/api/stream.mjpeg?src=atas
```

Fallback tersebut tetap raw; tidak ada re-encode FastAPI, YOLO, bounding box, canvas, vision metadata, underwater source, atau control message pada jalur video. Kegagalan video tidak mematikan atau menghidupkan kembali control WebSocket.

## 7. Lifecycle, guard, error, reconnect, dan deadman

### 7.1 Handshake dan startup

1. Browser memuat static app dari project Vercel remote.
2. App membuka satu jalur media Go2RTC untuk `atas` dan WSS control. App tidak memanggil status, telemetry, atau health endpoint.
3. Backend menolak ASV id yang salah, Origin yang tidak ada/di luar allowlist, atau `ASV_REMOTE_CONTROL_ENABLED=false` dengan close code `1008`.
4. Jika handshake diterima, backend membuat session id dan latest slot kosong. Tidak ada override aktif sebelum operator melakukan engagement pada salah satu slider dan command valid `enabled=true`.
5. Go2RTC player membuka jalurnya sendiri; video ready bukan prasyarat control dan sebaliknya.

### 7.2 Penerimaan dan penerapan command

Pada ingress, backend melakukan urutan berikut:

1. decode text sebagai JSON object;
2. validasi strict schema dan batas PWM;
3. validasi sequence sesi;
4. catat `server_received_at_ms` dan waktu monotonic;
5. untuk `enabled=false`, bersihkan slot dan release;
6. untuk `enabled=true`, cek feature flag, `BridgeState.control_mode == MANUAL`, Pixhawk connected/heartbeat, observed flight mode `MANUAL`, dan pilot-input guard;
7. jika aman, replace latest slot dan kirim ack accepted internal;
8. jika tidak aman, kirim ack rejected internal tanpa membuat command aktif.

Loop `PixhawkTelemetryReader` tetap menjadi satu-satunya jalur yang memanggil `rc_channels_override_send`. Setiap iterasi menerapkan hanya latest slot yang:

- berumur paling banyak **500 ms** berdasarkan `time.monotonic()` server;
- masih dimiliki sesi aktif;
- feature flag tetap aktif;
- koneksi Pixhawk dan heartbeat masih sehat;
- observed flight mode tetap `MANUAL`;
- pilot-input guard existing tidak aktif;
- seluruh validasi actuator existing lolos.

Jika salah satu kondisi gagal, reader memanggil release existing bila override aktif. Timeout 500 ms dimulai saat backend menerima command, bukan saat browser membuat event dan bukan dari `client_sent_at_ms`. Nilai `ASV_REMOTE_COMMAND_TIMEOUT` tidak boleh dinaikkan di deployment remote.

### 7.3 Disconnect, expiry, mode, dan restart

- Disconnect WebSocket masuk ke `finally` handler; jika sesi tersebut masih owner latest slot, slot dibersihkan dan release dipanggil segera, tanpa menunggu siklus refresh.
- Jika koneksi tetap terbuka tetapi frame berhenti, umur slot melampaui 500 ms dan reader melepas override pada iterasi kontrol berikutnya. Dengan loop existing maksimum 100 ms, release tidak menunggu input berikutnya.
- Sesi baru menutup sesi lama dan melepaskan command lama sebelum mengambil ownership.
- Saat `BridgeState.control_mode` berubah ke `AUTONOMOUS`, backend membersihkan/release command remote aktif dan menolak command `enabled=true` dengan `runtime_mode_autonomous`; remote UI tidak menampilkan mode tersebut dan tidak memiliki toggle untuk mengubahnya.
- `AUTONOMOUS` di atas adalah state aplikasi. Guard observed Pixhawk `_mode == MANUAL` tetap wajib dan tidak diganti menjadi pengecekan state aplikasi.
- Saat heartbeat Pixhawk hilang sesuai `pixhawk_heartbeat_timeout` existing, reader me-release dan melakukan reconnect sesuai lifecycle existing. Ack/rejection tetap internal; remote tidak menampilkan status offline.
- Saat backend process berhenti/restart, `PixhawkTelemetryReader.close()` tetap me-release override. Reconnect browser dimulai dengan backoff `250 ms, 500 ms, 1 s, 2 s`, maksimum `5 s`; setelah reconnect, operator harus memulai engagement slider lagi. Selama channel gagal, kedua input tetap disabled secara native.
- Error video hanya mengaktifkan fallback raw MJPEG. Error control tidak pernah diganti dengan command netral sintetis yang disamarkan sebagai sukses.

## 8. CORS, Origin, Cloudflare, dan Vercel

### 8.1 Origin HTTP

`ASV_CORS_ORIGINS` berisi daftar origin exact yang diperlukan: origin deployment Vercel remote yang benar, `http://localhost:3000` untuk dashboard lama, dan `http://localhost:3001` untuk remote workspace saat development bila memang digunakan. Origin adalah skema+host+port tanpa path dan tanpa wildcard. `allow_credentials` tetap `false`. Method/path media Go2RTC yang diperlukan oleh remote boleh melewati origin tersebut; method existing untuk dashboard lama tetap dipertahankan sesuai kontrak backend, tetapi host remote tidak membuka endpoint FastAPI status/telemetry.

Origin frontend Vercel berbeda dari hostname backend tunnel. `https://remote.monitor-kapal-pora-pora.web.id` adalah target control/video, bukan otomatis nilai `Access-Control-Allow-Origin`. Origin Vercel yang sebenarnya harus dicatat pada environment Pi sebelum app production mengirim traffic.

### 8.2 Origin WebSocket

`CORSMiddleware` tidak melindungi WebSocket upgrade. Karena itu handler `/ws/control/{asv_id}` sendiri memeriksa header `Origin` terhadap `cors_origins` dan menolak Origin kosong atau tidak dikenal dengan `1008`. Pemeriksaan ini membatasi browser cross-site yang tidak disengaja, tetapi bukan autentikasi: client non-browser dapat memalsukan header dan DNS hostname tetap publik.

Go2RTC signaling juga harus menerima upgrade dari origin Vercel remote. Route cloudflared tidak boleh mengubah atau meng-buffer frame WebSocket. Vercel tidak menjadi proxy WSS; browser terhubung langsung ke hostname tunnel.

### 8.3 Ingress remote yang diizinkan

Aturan host remote pada tunnel yang sama secara konseptual adalah:

| Host/path | Service lokal | Alasan |
|---|---|---|
| `remote.monitor-kapal-pora-pora.web.id/ws/control/.*` | `http://127.0.0.1:8080` | Persistent control WSS dan upgrade. |
| `remote.monitor-kapal-pora-pora.web.id/api/ws` | `http://127.0.0.1:1984` | Go2RTC signaling; `src=atas` wajib. |
| `remote.monitor-kapal-pora-pora.web.id/api/webrtc` | `http://127.0.0.1:1984` | Go2RTC HTTP negotiation untuk surface bila diperlukan. |
| `remote.monitor-kapal-pora-pora.web.id/api/stream.mp4` | `http://127.0.0.1:1984` | Go2RTC compatibility path untuk surface bila diperlukan. |
| `remote.monitor-kapal-pora-pora.web.id/api/stream.mjpeg?src=atas` | `http://127.0.0.1:1984` | Satu-satunya raw MJPEG fallback surface. |
| route lain | `http_status:404` | Tidak dipublikasikan pada host remote. |

Tidak ada route remote untuk `/healthz`, `/api/status`, `/api/telemetry`, endpoint vision, metadata, frame upload, actuator POST, atau control-mode mutation. Status/telemetry tetap internal atau berada pada ingress host lama sesuai konfigurasi existing dan tidak pernah dipanggil remote app.

## 9. Security tradeoff

Tidak ada autentikasi aplikasi sesuai keputusan produk. Konsekuensinya harus dinyatakan secara operasional:

> Cloudflare Tunnel hanya menyediakan publikasi jalur dan TLS; Cloudflare Tunnel bukan autentikasi. Siapa pun yang dapat mengakses hostname remote dan memenuhi protokol dapat mencoba mengontrol kapal ketika `ASV_REMOTE_CONTROL_ENABLED=true`.

Mitigasi yang tetap diwajibkan tanpa menyelundupkan token ke frontend:

- default feature flag remote `false`, lalu aktifkan hanya pada Pi yang benar;
- TLS/WSS/HTTPS dan hostname khusus remote;
- route tunnel allowlist hanya untuk control WSS dan raw Go2RTC surface `atas`;
- CORS exact origin dan pemeriksaan Origin WSS untuk mengurangi cross-site misuse, sambil tetap menganggapnya bukan auth;
- satu sesi control aktif per ASV agar dua tab tidak mengirim override bersamaan; sesi baru tetap dapat mengambil alih karena auth memang tidak ada;
- expiry server 500 ms, immediate release disconnect, heartbeat guard, observed `MANUAL`, pilot-input guard, dan validasi PWM 1000..2000;
- `ASV_CONTROL_TOKEN` model tetap hanya berada di environment Pi; tidak ada static control token, secret, atau service key pada bundle Vercel;
- tidak menyediakan arm/disarm, mode mutation, parameter write, autonomous spawn, atau data/status panel dari remote UI;
- logging latency/sequence tidak mencatat secret dan tidak menambahkannya ke DOM.

Tradeoff yang diterima: Origin check/CORS tidak mencegah penyerang yang mengetahui hostname dan dapat membuat WebSocket sendiri. Dengan tidak adanya auth, pengoperasian harus memperlakukan hostname sebagai endpoint kendali publik dan menjaga transmitter/operator siap mengambil alih. Auth aplikasi, Cloudflare Access, atau policy jaringan tambahan bukan bagian desain ini.

## 10. Latency budget dan measurement

### 10.1 Budget target

Budget untuk input event sampai frame command diterima dan disimpan backend:

| Segmen | Budget target |
|---|---:|
| Event UI → PWM integer, validasi lokal, dan enqueue browser | ≤5 ms |
| WebSocket browser → Cloudflare → tunnel → Raspberry Pi | ≤80 ms target transport, tidak dijamin Internet |
| FastAPI parse strict JSON, safety gate, simpan latest slot, dan timestamp ingress | ≤10 ms |
| Margin scheduling/clock/measurement | ≤5 ms |
| **Total target** | **≤100 ms** |

Budget ini tidak berarti actuator fisik pasti bergerak dalam 100 ms. Waktu Pixhawk loop, MAVLink, servo, ESC, dan dinamika kapal diukur terpisah melalui log/test harness. Deadman 500 ms tetap batas keselamatan yang lebih penting daripada throughput. Tidak ada angka budget atau hasil latency yang dirender di UI.

### 10.2 Metode pengukuran internal

Setiap command valid membawa `client_sent_at_ms`; backend mengembalikan nilai tersebut dan `server_received_at_ms` pada ack internal.

- Untuk measurement authoritative input→backend, browser dan Pi disinkronkan NTP/clock source yang sama. Test harness menghitung `server_received_at_ms - client_sent_at_ms` per sequence dan menyimpan p50, p95, p99, max, frame loss, serta reconnect count dari sekurang-kurangnya 1000 command pada rate refresh yang sama dengan production.
- Karena clock publik dapat skew, test harness mencatat offset clock sebelum run dan menolak hasil yang tidak dikoreksi. Timestamp ack tidak boleh dipakai untuk mengklaim latency satu arah tanpa koreksi tersebut.
- RTT browser `performance.now()` dari send sampai ack boleh dicatat oleh test harness/log untuk diagnosis, tetapi tidak ditampilkan, tidak menjadi status, dan tidak masuk DOM.
- Acceptance latency production memakai p95 ≤100 ms pada jaringan terkontrol/near-edge. Hasil Internet publik di atas 100 ms dicatat sebagai kondisi transport yang tidak dijamin, bukan alasan menghapus guard atau menaikkan deadman. Backend parse/queue tetap harus memenuhi ≤10 ms pada test lokal.
- Ack `accepted` mengukur penerimaan/queue backend, bukan keberhasilan transmisi `RC_CHANNELS_OVERRIDE`; status Pixhawk/telemetry dan log reader menjadi bukti jalur hardware yang terpisah, bukan data remote UI.

## 11. Testing dan acceptance criteria

### 11.1 Kontrak backend

Implementasi dianggap memenuhi desain jika test berikut tersedia dan lulus:

- `RemoteControlCommand` menerima hanya integer PWM 1000..2000 dan menolak 999, 2001, float, string, boolean, field ekstra, field hilang, dan JSON non-object.
- `seq` harus meningkat ketat; duplicate/out-of-order mendapat ack rejected dan tidak mengubah latest slot.
- Ack selalu mengembalikan sequence dan `server_received_at_ms`; accepted berarti queued, bukan applied.
- ASV id salah, Origin kosong/tidak dikenal, dan feature flag disabled ditolak tanpa membuat koneksi Pixhawk baru.
- Dua koneksi untuk satu ASV menghasilkan satu sesi aktif; supersede menutup sesi lama dan me-release command lama.
- Command terbaru menggantikan command sebelumnya tanpa antrean; command stale tidak pernah dikirim ke Pixhawk.
- Command remote yang berumur >500 ms dilepas memakai monotonic clock. Test menggunakan fake clock atau injection terisolasi, bukan sleep flaky.
- Disconnect memanggil release segera; release tetap terjadi saat backend shutdown.
- Semua guard existing tetap teruji: PWM, heartbeat, observed flightmode `MANUAL`, pilot-input guard, feature flag, dan release override.
- `BridgeState.control_mode == AUTONOMOUS` menolak remote enabled command tanpa mengubah observed flight mode dan tanpa menjalankan autonomous process.
- Existing `POST /api/control/actuator` dengan token dan lifecycle telemetry tetap memiliki kontrak sebelumnya.

### 11.2 Kontrak frontend

- DOM remote memiliki tepat satu player/media surface source `atas` dan tepat dua input range direct PWM: steering dan throttle.
- Tidak ada tombol enable, autonomy toggle, kamera kedua, panel status/telemetry, angka latency/sequence/PWM, acknowledgement/rejection text, overlay model/YOLO, vision metadata, atau elemen data lain.
- UI mengirim `steering_pwm`/`throttle_pwm` langsung, bukan normalized intent atau field alternatif.
- Interaksi input membuat frame WebSocket pada channel persisten dan tidak membuat POST per event.
- Engagement pointer/keyboard mengirim `enabled=true` dengan refresh ≤200 ms; release, blur, visibility hidden, unmount, atau input cancellation mengirim `enabled=false` dan menghentikan refresh.
- Ack, rejection, timeout, close, backoff, dan deadman tidak ditampilkan. WebSocket error/close atau kegagalan input hanya boleh menghentikan refresh dan membuat input disabled dengan state native browser bila diperlukan untuk keselamatan.
- URL control selalu WSS pada production origin remote dan URL video hanya berasal dari Go2RTC `api/ws`/raw MJPEG path dengan `src=atas`.
- Test network tidak menemukan `/ws/vision`, `/api/vision/metadata`, `/api/status`, `/api/telemetry`, YOLO/model request, kamera `bawah`, canvas detection overlay, atau static token pada bundle remote.
- WebRTC player membersihkan peer/WebSocket/timer dan beralih ke satu raw MJPEG `atas` dalam tiga detik tanpa memengaruhi control channel.
- Tidak ada command sintetis yang dikirim sebagai fallback ketika media atau control gagal.

### 11.3 Acceptance operasional

Sebelum enable di air:

1. Deploy remote project Vercel terpisah dan catat origin production yang sebenarnya.
2. Isi CORS exact origin pada Pi dan konfigurasi ingress hostname remote pada tunnel Pora Pora yang sama, hanya untuk control WSS dan path Go2RTC surface.
3. Verifikasi dari browser production bahwa satu stream raw surface `atas` dapat memakai WebRTC dan fallback MJPEG; pastikan tidak ada request status/telemetry dari remote app.
4. Uji control di bangku dengan propulsi aman/disconnected dan transmitter tersedia sebagai override fisik.
5. Verifikasi secara internal browser menerima ack, backend hanya memiliki satu Pixhawk reader, observed mode `MANUAL`, dan command release saat slider dilepas; tidak perlu merender hasil tersebut.
6. Putuskan jaringan/close tab; ukur release ≤500 ms plus scheduling loop existing dan pastikan output kembali ke authority Pixhawk/transmitter.
7. Jalankan latency probe internal 1000 command dengan NTP-corrected timestamp; catat p50/p95/p99 dan kondisi jaringan. P95 terkontrol harus ≤100 ms; hasil hanya menjadi log/test evidence.
8. Pastikan dashboard lama tetap berfungsi pada host lama dan tidak menerima perubahan UI atau jalur data remote.

## 12. Rollout dan rollback

### Rollout bertahap

1. Tambahkan workspace dan kontrak backend dengan feature flag tetap `ASV_REMOTE_CONTROL_ENABLED=false`.
2. Tambahkan ingress remote pada tunnel yang sama dengan route surface Go2RTC/control WSS; verifikasi satu raw stream `atas` lebih dulu.
3. Deploy static remote app ke project Vercel terpisah; set hanya public origin backend/video dan ASV id. Jangan set token.
4. Tambahkan origin Vercel production ke allowlist CORS/WS pada Pi, lalu uji handshake control dalam mode disabled untuk memastikan penolakan internal tetap benar.
5. Set `ASV_REMOTE_CONTROL_ENABLED=true` hanya setelah Pixhawk reader, observed `MANUAL`, safety switch, transmitter fallback, dan bench test diverifikasi. Restart service secara normal sehingga close path me-release override.
6. Pantau log ack/rejection, RTT, ingress p95, reconnect, heartbeat, dan release secara internal. Tidak ada perubahan pada dashboard lama selama rollout.

### Rollback

- Set `ASV_REMOTE_CONTROL_ENABLED=false` dan restart `asv-dashboard.service`; shutdown reader harus me-release override.
- Jika perlu, hapus route `/ws/control/.*` dari hostname remote atau arahkan host remote ke `http_status:404`; route dashboard lama tetap dipertahankan.
- Rollback Vercel ke deployment remote sebelumnya atau nonaktifkan project remote. Tidak perlu dan tidak boleh membuat backend/Pixhawk kedua.
- Biarkan `ASV_MODEL_ACTUATORS_ENABLED` dan `ASV_CONTROL_TOKEN` existing tetap sesuai jalur model; jangan menghapus token Pi sebagai cara rollback remote.
- Jika video bermasalah, rollback hanya route/player Go2RTC ke raw MJPEG `atas`; jangan mengubah control deadman atau menyamakan jalur video dengan control.

## 13. Assumptions

- `ASV_ID` production tetap `default`, sehingga path contoh menggunakan `/ws/control/default`.
- FastAPI bridge lokal tetap pada `127.0.0.1:8080`, dan Go2RTC existing tetap pada `127.0.0.1:1984`, sesuai topologi operasional repo.
- Go2RTC sudah dikonfigurasi dengan source `atas` serta menyediakan signaling/WebRTC/raw MJPEG pada path yang disebutkan.
- Tunnel remote yang dipakai adalah tunnel Cloudflare Pora Pora yang sama, dengan hostname `remote.monitor-kapal-pora-pora.web.id`; tidak ada tunnel baru.
- Remote UI dideploy sebagai project/domain Vercel terpisah dari backend tunnel. Origin Vercel production yang benar dicatat sebagai nilai exact pada `ASV_CORS_ORIGINS` sebelum control diaktifkan.
- Browser operator mendukung WebSocket, WebRTC, dan `<img>` raw MJPEG; fallback tidak memerlukan model atau overlay.
- ArduPilot Rover Boat pada Pixhawk V2.4.8 tetap dikendalikan oleh satu reader backend dan observed flight mode `MANUAL` saat direct PWM dipakai.
- Tidak ada autentikasi aplikasi pada release pertama; hostname remote diperlakukan sebagai endpoint control publik dan operator menerima tradeoff tersebut.
- Satu sesi aktif per ASV adalah kebijakan yang dipilih untuk mengurangi konflik tab, bukan pengganti authentication.
- Runtime control mode existing tetap dipelihara sebagai state aplikasi terpisah; remote hanya mengonsumsi state itu sebagai guard dan tidak men-spawn autonomous.
