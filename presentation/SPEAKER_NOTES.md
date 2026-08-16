# Catatan Presenter: Kapal ASV Coast Guard 900mm (KKI 2026)

Panduan berbicara untuk presentasi besok (8 Slide).

---

## SLIDE 1: Cover / Judul Proyek
* **Poin Pembuka**: "Selamat pagi/siang Dewan Juri dan Rekan-rekan sekalian. Kami dari Tim ASV KKI 2026 mempersembahkan kapal tak berawak (Autonomous Surface Vehicle) kategori Coast Guard 900mm berbasis Computer Vision dan sistem kontrol hibrida ArduPilot."
* **Sorotan Utama**: Kapal ini dirancang khusus untuk bernavigasi otonom melalui 10 gerbang slalom dan koridor sempit secara mandiri di kolam lomba tanpa ketergantungan sinyal GPS.

---

## SLIDE 2: Desain Mekanikal & Struktur Lambung
* **Dimensi & Stabilitas**: Panjang lambung 900 mm dengan lebar maksimum 304 mm yang dihitung cermat melalui analisis hidrostatis untuk memastikan titik berat (*center of gravity*) tetap rendah dan stabil terhadap ombak air kolam.
* **Modularitas**:
  - *Haluan*: Pedestal dekoratif Coast Guard.
  - *Kabin*: Modul removable untuk akses cepat servis baterai LiPo dan perangkat elektronik tanpa merusak struktur lambung.
  - *Atap*: Dudukan kamera permukaan Logitech C920, mast radar, dan antena komunikasi.

---

## SLIDE 3: Arsitektur Hardware Hibrida (Pixhawk + Raspberry Pi 5)
* **Pemisahan Tugas (*Separation of Concerns*)**:
  - **Pixhawk (ArduPilot)**: Menangani aktuasi real-time tingkat rendah (servo rudder kemudi dan ESC motor brushless) dengan frekuensi 20 Hz serta memprioritaskan keselamatan (*Manual RC Override instant takeover*).
  - **Raspberry Pi 5**: Bertindak sebagai *companion computer* berkinerja tinggi yang menjalankan inferensi model AI YOLOv8 dan algoritma visual servoing.
* **Komunikasi MAVLink**: Terhubung via serial berkecepatan tinggi dengan sistem *auto-reconnect* jika terjadi fluktuasi kabel.

---

## SLIDE 4: Computer Vision & Model YOLO
* **Model Deteksi**: Menggunakan YOLOv8 yang di-training khusus untuk mengenali buoy merah (`red_buoy`) dan buoy hijau (`green_buoy`).
* **Visual Midpoint Extraction**: Algoritma langsung menghitung garis tengah antara buoy merah (kiri) dan hijau (kanan) di bidang piksel kamera, lalu memetakan simpangannya menjadi perintah kemudi presisi.
* **Target Memory Persistence**: Fitur *Visual Target Tracker* mempertahankan arah lintasan selama 0.8 detik saat buoy mulai keluar dari sudut pandang kamera saat kapal melewatinya.

---

## SLIDE 5: Algoritma Navigasi Otonom (Zero-GPS)
* **Keunggulan Tanpa GPS**: "Di kolam lomba indoor/semi-outdoor, GPS memiliki deviasi 3-6 meter yang tidak dapat dipakai untuk melewati gerbang selebar 2 meter. Oleh karena itu, seluruh navigasi kami dipandu 100% secara visual oleh kamera."
* **Sekuens Sektor 10 Gerbang**:
  1. *Slalom Kanan (Gate 1 &rarr; 2 &rarr; 3)*: Heading Utara &plusmn;20&deg; menyusuri gerbang.
  2. *Sudut Barat-Laut (Gate 3 &rarr; 4)*: Belok 310&deg; NW masuk koridor atas.
  3. *Koridor Atas (Gate 4 &rarr; 5 &rarr; 6 &rarr; 7)*: Meluncur cepat menyusuri garis $Y = 10.0\text{ m}$ (heading 270&deg; Barat).
  4. *Sudut Barat-Daya (Gate 7 &rarr; 8)*: Belok 230&deg; SW masuk slalom kiri.
  5. *Slalom Kiri & Finish (Gate 8 &rarr; 9 &rarr; 10)*: Heading 160&deg; &rarr; 200&deg; menembus gerbang akhir.

---

## SLIDE 6: Dashboard Telemetri Real-Time & Live Stream
* **Monitoring Pilot Darat**: Dashboard berbasis Next.js dideploy di Vercel dengan latensi video ultra-rendah via Go2RTC/WebRTC (&lt;150 ms).
* **Keamanan Jaringan**: Menggunakan Cloudflare Tunnel sehingga Raspberry Pi dapat diakses aman dari internet publik tanpa konfigurasi port forwarding berbahaya.
* **Canvas Overlay**: Menampilkan visualisasi AR *Lane Guidance* (garis tengah hijau-kuning Google Maps style) langsung di atas feed video kamera.

---

## SLIDE 7: Hasil Uji & Validasi Simulasi
* **Hasil Pengujian**:
  - Kecepatan jelajah: **2.20 m/s** (Laju cepat dan responsif).
  - Waktu tempuh total 10 gerbang: **28.7 detik**.
  - Benturan Dinding (*Wall Hits*): **0 Kali (Zero Wall Hits)**.
  - Melewati gerbang slalom dan koridor atas secara bersih (*clean valid clearance*).

---

## SLIDE 8: Kesimpulan & Penutup
* **Poin Penutup**: "Dengan integrasi mekanikal lambung yang kokoh, sistem visi cerdas YOLOv8, aktuasi andal ArduPilot, serta navigasi otonom zero-GPS, kapal ASV Coast Guard 900mm kami siap bersaing dan memberikan performa terbaik pada KKI 2026. Terima kasih."
