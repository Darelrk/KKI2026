# Plan Dek Atas Kapal Coast Guard RC 900 x 300 mm

## Status

Draft untuk ditinjau pengguna. Belum ada geometri baru yang dibuat atau diubah di FreeCAD.

## Tujuan

Menyusun tata letak dek atas untuk model RC Coast Guard dengan komponen berikut:

- ruang kemudi;
- helipad mini untuk drone/miniatur;
- dudukan machine gun dekoratif non-fungsional;
- perlengkapan navigasi, komunikasi, dan penyelamatan yang ringan.

## Batasan model

- Ukuran lambung: panjang 900 mm, lebar maksimum sekitar 304 mm.
- Satuan internal FreeCAD: mm.
- Penomoran pengguna: Sekat 0 berada di haluan dan Sekat 6 di buritan.
- Sumbu FreeCAD yang ada belum dibalik: X=0 berada di transom/buritan dan X=900 berada di haluan.
- Konversi posisi pengguna ke FreeCAD: `X_FreeCAD = 900 - jarak_dari_haluan`.
- Dek atas harus tetap ringan dan tidak menaikkan titik berat secara berlebihan.
- Machine gun hanya model visual: tanpa mekanisme menembak, amunisi, atau sistem kendali senjata.

## Tata letak yang dipilih

Urutan dari haluan ke buritan:

1. Dudukan machine gun dekoratif di dek depan.
2. Ruang kemudi di bagian tengah-depan.
3. Tiang radar, antena, dan searchlight di atas/di belakang ruang kemudi.
4. Dek kerja/boarding di antara ruang kemudi dan helipad.
5. Helipad mini yang dapat dilepas di dek belakang.

### Tabel posisi awal

| Komponen | Jarak dari haluan | Rentang X FreeCAD | Ukuran awal |
|---|---:|---:|---:|
| Dudukan machine gun dekoratif | 60–120 mm | 780–840 mm | pedestal diameter 30–40 mm |
| Ruang kemudi | 220–460 mm | 440–680 mm | panjang 220–250 mm, lebar 140–170 mm |
| Tiang radar/antena | 340–420 mm | 480–560 mm | tinggi 100–140 mm |
| Dek kerja/boarding | 460–580 mm | 320–440 mm | jalur bebas minimal 30 mm |
| Helipad mini | 600–820 mm | 80–300 mm | diameter 120–140 mm |

Posisi final harus dipangkas mengikuti lebar aktual lambung pada setiap X. Tidak boleh ada bagian dek yang menggantung keluar dari sisi lambung tanpa pemeriksaan visual.

## Komponen geometris FreeCAD

### 1. Helipad mini

- Bentuk: cakram tipis atau pelat lingkaran dengan marka `H`.
- Diameter target: 120–140 mm.
- Tebal target: 2–3 mm untuk mockup.
- Penempatan: dek belakang, dibuat removable.
- Fungsi: tampilan untuk drone/miniatur, bukan helipad helikopter penuh.

### 2. Ruang kemudi

- Bentuk: kotak rendah dengan atap datar dan kaca depan/samping sebagai elemen visual.
- Panjang: 220–250 mm.
- Lebar: 140–170 mm.
- Tinggi dari dek: 90–110 mm.
- Atap dapat menjadi dudukan antena/searchlight.
- Sisakan akses servis untuk baterai dan elektronik RC.

### 3. Dudukan machine gun dekoratif

- Bentuk: pedestal silinder dan laras tiruan pendek.
- Posisi: dek depan, pada centerline.
- Tinggi rendah agar tidak mengganggu stabilitas.
- Tidak membuat mekanisme putar bermotor atau fungsi menembak.

### 4. Tiang dan perlengkapan atas

- Tiang radar kecil.
- Antena VHF.
- Searchlight.
- Lampu navigasi merah, hijau, dan putih.
- Sirene/horn sebagai aksesori visual.

### 5. Dek kerja dan penyelamatan

- Area datar di antara ruang kemudi dan helipad.
- Handrail/grab rail.
- Lifebuoy.
- Tangga boarding.
- Cleat/towing post.
- Kotak penyimpanan atau emergency box.
- Tutup akses baterai yang dapat dilepas.

## Aksesori Coast Guard yang direkomendasikan

### Prioritas tinggi

1. Radar/mast kecil.
2. Antena VHF.
3. Searchlight.
4. Lampu navigasi.
5. Lifebuoy.
6. Tangga boarding.
7. Handrail.
8. Cleat dan towing post.
9. Tutup akses baterai.

### Prioritas menengah

1. Sirene/horn.
2. Lampu strobo.
3. Kotak P3K.
4. Rescue throw bag.
5. Kotak pemadam api dekoratif.
6. Fender rope.
7. Kamera kecil.
8. Peti perlengkapan rescue.

## Prinsip konstruksi

- Komponen besar seperti ruang kemudi dan helipad harus dibuat removable atau memiliki akses servis.
- Akses baterai tidak boleh tertutup permanen.
- Akses jalan di sisi ruang kemudi minimal 30 mm bila geometri lambung memungkinkan.
- Aksesori kecil dibuat sebagai komponen terpisah supaya mudah dicat dan diganti.
- Helipad dan aksesori atas dibuat ringan; hindari massa besar di atas kabin.
- Semua komponen baru diberi prefix/nama `UpperDeck_` agar tidak mengganggu objek hull, sekat, keel, transom, atau stem yang sudah ada.

## Rencana implementasi MCP FreeCAD setelah persetujuan

1. Buat grup `UpperDeck_Plan`.
2. Buat geometri dasar ruang kemudi, helipad, dek kerja, dan pedestal dekoratif.
3. Tambahkan tiang, radar, searchlight, antena, dan aksesori keselamatan sebagai objek terpisah.
4. Recompute dokumen.
5. Periksa bounding box dan interferensi dengan hull.
6. Tampilkan screenshot isometrik serta tampak atas.
7. Simpan ke `CoastGuardRC_900x300.fcstd` setelah hasil disetujui.

## Verifikasi penerimaan

Plan dianggap sesuai jika:

- helipad berada di dek belakang dan tidak keluar dari lebar lambung;
- ruang kemudi berada di tengah-depan;
- pedestal dekoratif berada di dek depan;
- jalur akses dan akses baterai tetap tersedia;
- tidak ada objek baru yang memotong atau merusak hull;
- semua aksesori baru mudah diidentifikasi dan dapat dihapus terpisah;
- tampilan atas dan isometrik menunjukkan susunan dari haluan ke buritan dengan jelas.

## Referensi

- U.S. Coast Guard, Response Boat–Small II: https://www.dcms.uscg.mil/Our-Organization/Assistant-Commandant-for-Acquisitions-CG-9/Programs/Surface-Programs/Response-Boat-Small-II/
- U.S. Coast Guard, Cutter Boats: https://www.dcms.uscg.mil/Our-Organization/Assistant-Commandant-for-Acquisitions-CG-9/Programs/Surface-Programs/Cutter-Boats/
