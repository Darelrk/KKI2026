# Checkpoint Metode Computer Vision: Blind Corner ASV

**Tanggal:** 2026-07-15  
**Status:** Desain disetujui untuk dokumentasi; belum diimplementasikan ke kode.

## Tujuan

Mendokumentasikan metode navigasi ketika kapal ASV melewati belokan patah setelah pola **3×3 bola pertama**. Area setelah belokan sudah dipastikan blank, sehingga kamera tidak dapat melihat buoy berikutnya sampai kapal melakukan survey.

Kehilangan buoy pada area blank adalah kondisi lintasan yang diperkirakan, bukan kegagalan deteksi biasa.

## Konteks lintasan

- Ukuran total lintasan: **60 m × 30 m**.
- Dua area berdampingan: masing-masing **30 m × 30 m**.
- Jalur ditandai oleh pasangan bola merah–hijau dengan jarak **2 m**.
- Panduan KKI menyebutkan 10 pasangan bola merah–hijau, total 20 bola.
- Setelah pola 3×3 pada bagian awal lintasan, terdapat belokan patah menuju area tanpa view buoy.

Istilah `3×3` pada dokumen ini adalah **pola/checkpoint lintasan**, bukan asumsi jumlah sembilan objek atau tiga pasangan. Pola harus ditentukan dari urutan/geometri lintasan yang dikonfigurasi untuk venue.

## State machine

```text
VISUAL_TRACK
    ↓ checkpoint pola 3×3 terkonfirmasi
BLIND_TURN
    ↓ heading belokan tercapai
SURVEY_SEARCH
    ↓ pasangan merah + hijau terlihat stabil
VISUAL_TRACK
```

Jika survey gagal menemukan jalur berikutnya dalam batas yang ditentukan:

```text
SURVEY_SEARCH → FAILSAFE
```

## State `VISUAL_TRACK`

Kapal mengikuti titik tengah antara buoy merah dan hijau.

Deteksi checkpoint tidak boleh memakai jumlah frame. Sistem harus menghasilkan event gate yang valid:

1. Buoy merah dan hijau terlihat stabil.
2. Posisi pasangan berubah sesuai kapal yang melewati gate.
3. Satu gate hanya dihitung satu kali.
4. Debounce mencegah penghitungan ulang pada frame berikutnya.
5. Urutan gate digunakan untuk mengenali pola 3×3.

Checkpoint blind-turn hanya aktif setelah pola tersebut terkonfirmasi. Hilangnya buoy sementara sebelum checkpoint tidak boleh langsung memicu blind-turn.

Model saat ini mengenali label `red_buoy` dan `green_buoy`; model belum memiliki kelas khusus bernama `pattern_3x3`. Karena itu, implementasi harus menggunakan tracker temporal/geometri dan konfigurasi urutan rute, bukan menganggap pola sudah tersedia dari satu prediksi YOLO.

## State `BLIND_TURN`

Setelah checkpoint pola 3×3 terkonfirmasi:

- Kamera tidak digunakan untuk menentukan arah.
- Kapal menjalankan belokan yang sudah direncanakan.
- Heading dikontrol menggunakan compass/IMU Pixhawk.
- Sudut belokan dibuat sebagai parameter; nilai awal dapat 90° jika hasil pengukuran lintasan memang siku-siku.
- Throttle dibuat rendah dan aman.
- Belokan tidak boleh hanya mengandalkan durasi PWM karena kecepatan dipengaruhi baterai, arus, dan beban kapal.

Parameter yang perlu tersedia:

- `turn_angle_deg`
- `blind_turn_throttle_pwm`
- `heading_tolerance_deg`
- `blind_turn_timeout_s`

## State `SURVEY_SEARCH`

Setelah heading belokan tercapai:

1. Kurangi kecepatan kapal.
2. Lakukan sapuan heading kiri–kanan terbatas menggunakan rudder.
3. Gunakan kamera untuk mencari jalur berikutnya.
4. Anggap jalur ditemukan hanya jika buoy merah dan hijau terlihat stabil beberapa frame.
5. Setelah pasangan valid ditemukan, kembali ke `VISUAL_TRACK`.

Kamera tetap menghadap ke depan. Survey dilakukan dengan mengubah heading kapal; belum diperlukan mekanisme pan-tilt tambahan.

Parameter yang perlu tersedia:

- `survey_throttle_pwm`
- `survey_sweep_deg`
- `survey_sweep_rate`
- `survey_timeout_s`
- `reacquire_frames`
- `reacquire_confidence`

## State `FAILSAFE`

Jika pasangan buoy berikutnya tidak ditemukan dalam batas waktu atau jarak survey:

- throttle kembali netral;
- steering kembali netral atau kapal masuk `HOLD`;
- log mencatat `survey_timeout`;
- kapal tidak terus bergerak tanpa arah.

## Data log minimum

Setiap perubahan state dan keputusan navigasi perlu dicatat dalam JSONL:

- timestamp;
- state sebelum dan sesudah;
- event pemicu;
- jumlah gate yang sudah dilewati;
- status checkpoint 3×3;
- heading aktual dan heading target;
- sudut survey;
- deteksi merah/hijau dan confidence;
- steering PWM;
- throttle PWM;
- status mode, armed, RC, dan servo output Pixhawk;
- alasan failsafe jika terjadi.

Contoh event:

```json
{
  "event": "state_transition",
  "from": "BLIND_TURN",
  "to": "SURVEY_SEARCH",
  "reason": "target_heading_reached",
  "heading_deg": 271.4,
  "target_heading_deg": 270.0
}
```

## Kondisi implementasi saat ini

`D:/KKI2/vision_test.py` saat ini sudah memiliki:

- deteksi buoy YOLO;
- pemilihan target tengah pasangan merah–hijau;
- RC override steering/throttle melalui MAVLink;
- log JSONL;
- throttle netral saat target tidak terlihat.

Skrip tersebut belum memiliki:

- state machine rute;
- gate-crossing tracker;
- pengenalan checkpoint pola 3×3;
- pembacaan heading untuk kontrol belokan;
- blind-turn;
- survey search;
- timeout/failsafe survey.

## Verifikasi keselamatan sebelum uji air

Pengujian harus bertahap:

1. Uji tracker gate dan transisi state menggunakan data/frame rekaman.
2. Uji heading dan transisi state di meja tanpa propeller/thruster aktif.
3. Uji steering blind-turn dengan throttle netral.
4. Pastikan output servo Pixhawk benar-benar berubah sesuai perintah.
5. Uji survey di air dengan throttle rendah dan area aman.
6. Baru lakukan uji lintasan penuh.

Riwayat pengujian menunjukkan `RC3` pernah menerima throttle, tetapi `SERVO3` masih terbaca 1500. Masalah output fisik itu harus diselesaikan dan diverifikasi sebelum blind-turn dengan propulsi dijalankan di air.

## Di luar cakupan

Metode ini tidak menambahkan SLAM, peta kompleks, hardware kamera baru, atau kontrol otomatis yang tidak diperlukan. Fokusnya adalah checkpoint visual yang eksplisit, belokan terencana berbasis heading, survey terbatas, dan failsafe sederhana.
