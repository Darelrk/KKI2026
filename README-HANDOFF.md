# KKI2026 Complete Source Handoff

Snapshot source ini dibuat dari commit `9caaa09`
(`feat: add Kolam Deli ASV mission dashboard`).

Isi paket:

- `dashboard/`: dashboard frontend terbaru;
- `asv_dashboard_backend/`: backend asli proyek, tidak diubah pada commit ini;
- `deploy/`, `docs/`, `model/`, `tests/`, serta seluruh script proyek yang tercatat di Git.

Tidak disertakan karena dapat dibuat ulang atau bersifat lokal:

- `.git/` dan riwayat Git;
- `node_modules/`, `.output/`, cache, dan hasil build;
- file `.env` atau kredensial lokal.

Untuk menjalankan frontend, baca `dashboard/README.md` dan gunakan `npm ci`
 dari root proyek sebelum menjalankan `npm run dev --workspace dashboard`.
