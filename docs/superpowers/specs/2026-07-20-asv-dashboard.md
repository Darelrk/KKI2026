# PRD Dashboard ASV — Vercel Camera Viewer

**Tanggal:** 2026-07-20  
**Status:** Deployment Vercel dan Supabase Free dipilih; fallback kamera full-color dibatasi oleh ukuran pesan Realtime.

## 1. Batasan produk

Dashboard hanya menampilkan kamera dari model ASV yang sudah berjalan di Raspberry Pi 5.

Dashboard tidak menjalankan model, tidak mengambil alih navigasi, dan tidak menjadi backend pemrosesan kamera.

Target deployment frontend: **Vercel**.

Database dan kanal realtime yang dipilih: **Supabase Free**.

## 2. Arsitektur

```text
Kamera + model ASV yang sudah berjalan di Raspberry Pi
        │ menghasilkan frame hasil model
        ▼
Surface camera bridge di Pi
        │ HTTP/MJPEG read-only
        ▼
cloudflared Tunnel → HTTPS public camera hostname
        │
        ▼
Vercel dashboard → menampilkan feed surface
        │
        ├── Supabase Postgres/Realtime → status dan metadata sesi
        └── Supabase Realtime Broadcast → fallback underwater full-color
```

Tidak diperlukan custom cloud backend. Namun tetap diperlukan:

- local camera bridge di Raspberry Pi apabila proses model belum memiliki endpoint stream;
- Cloudflare Tunnel atau jalur HTTPS setara agar Vercel dapat mengakses kamera di balik jaringan Pi;
- Supabase Free sebagai managed database dan realtime service;
- Supabase Realtime Broadcast untuk fallback frame underwater full-color yang ukurannya dibatasi.

Vercel Functions tidak digunakan sebagai relay kamera. Continuous video/MJPEG tidak boleh dipompa melalui Function atau database realtime.

## 3. Dependency

### 3.1 Vercel frontend

```text
next
react
react-dom
@supabase/supabase-js
```

`@supabase/supabase-js` dipakai untuk membaca status Supabase dan subscribe ke channel Realtime.

Tidak diperlukan pada MVP:

```text
socket.io
mediasoup
janus
webrtc server
@vercel/functions
```

### 3.2 Raspberry Pi camera bridge

File dependency: `D:/KKI2/requirements-dashboard.txt`

```text
fastapi
uvicorn[standard]
supabase
```

Keterangan:

- `fastapi` dan `uvicorn` hanya dipakai jika model belum menyediakan endpoint kamera;
- `supabase` mengirim status dan fallback frame ke Supabase;
- dependency model dan OpenCV tetap dikelola oleh environment model yang sudah berjalan;
- `pymavlink` hanya ditambahkan jika status Pixhawk ikut dipublikasikan, bukan kebutuhan dashboard kamera MVP.

### 3.3 Raspberry Pi system dependency

```text
cloudflared
```

`cloudflared` dipasang sebagai binary/service sistem, bukan package Python.

## 4. Data dan kanal Supabase Realtime

Status terakhir disimpan pada tabel `asv_live`, dengan kolom minimum:

```text
online
model_status
camera
stream_url
run_id
updated_at
```

Fallback underwater full-color dikirim melalui channel Broadcast:

```text
channel: asv-camera
event: underwater_frame
payload: mime, data_base64, captured_at
```

Ketentuan frame fallback:

- tetap **full-color**, bukan grayscale;
- maksimal 1 frame/detik;
- payload Realtime harus jauh di bawah batas 256 KB;
- target `data_base64` maksimal 180 KB;
- JPEG harus di-resize atau dikompresi ulang jika melebihi target;
- hanya frame terbaru yang dipakai, tidak membuat histori frame tanpa batas.

Yang tidak boleh disimpan atau dikirim:

- continuous surface video melalui Supabase;
- frame mentah tanpa kompresi;
- buffer MJPEG;
- file model atau hasil inferensi besar.

## 5. Jalur kamera

1. Model ASV menghasilkan annotated frame di Raspberry Pi.
2. Surface camera bridge menyediakan endpoint read-only, misalnya `/stream.mjpg`.
3. `cloudflared` meneruskan endpoint lokal ke hostname HTTPS.
4. Vercel dashboard membaca `stream_url` dari tabel `asv_live` Supabase.
5. Browser menampilkan surface stream langsung dari hostname kamera.
6. Jika surface stream atau USB underwater terputus, Pi mengirim frame underwater full-color terbaru melalui Broadcast `asv-camera`.
7. Jika Pi atau tunnel mati, dashboard menampilkan status offline dan placeholder, bukan retry tanpa batas.

Jika model yang sudah berjalan telah menyediakan URL stream yang kompatibel dengan browser, FastAPI camera bridge tidak perlu ditambahkan.

## 6. Keamanan minimum

- Supabase URL dan publishable key pada Vercel hanya digunakan sebagai client key.
- Secret/service key tidak pernah masuk browser atau repository.
- Row Level Security Supabase diaktifkan untuk tabel `asv_live`.
- Channel fallback tidak dipakai untuk video kontinu dan hanya menerima payload berukuran terbatas.
- Endpoint kamera bersifat read-only.
- Tunnel menggunakan HTTPS.
- URL kamera tidak ditulis permanen ke source code; gunakan Supabase metadata atau environment variable.

## 7. Acceptance criteria

- [ ] Frontend dashboard berhasil deploy di Vercel.
- [ ] Model ASV tetap berjalan di Raspberry Pi tanpa dipindahkan ke Vercel.
- [ ] Browser dapat membuka surface feed melalui URL HTTPS publik.
- [ ] Dashboard membaca status `asv_live` dari Supabase secara realtime.
- [ ] Fallback underwater tetap full-color dan diterima melalui Broadcast.
- [ ] Payload fallback berada di bawah 256 KB dan `data_base64` mengikuti target 180 KB.
- [ ] Tidak ada video kontinu yang dikirim melalui Supabase atau Vercel Function.
- [ ] Dashboard menampilkan kondisi offline ketika Pi, bridge, tunnel, atau Supabase terputus.
- [ ] Tidak ada custom cloud backend atau relay video Vercel pada MVP.

## 8. Di luar cakupan MVP

- menjalankan YOLO/model di Vercel;
- navigasi ASV, autopilot, dan RC control;
- dashboard scoring lengkap KKI;
- penyimpanan rekaman video;
- WebRTC media server;
- telemetry Pixhawk lengkap.
