# Mode Manual RC + Dashboard Model Monitoring

**Tanggal:** 2026-07-23  
**Status:** Disetujui pengguna untuk implementasi

## Current delivery scope

This session changes the dashboard frontend only. The Raspberry Pi Codex will
implement the backend/model `--manual-rc` path separately. The frontend
consumes the existing live metadata and read-only telemetry contracts; it does
not open Pixhawk, send MAVLink, or control the RC path.

## Tujuan

Menampilkan hasil YOLO live dan telemetry GPS di dashboard dengan status
operasi yang jujur: model hanya monitoring, sedangkan Pixhawk dikendalikan
oleh transmitter RC. Integrasi Raspberry Pi yang menghasilkan metadata,
telemetry, dan mode `--manual-rc` disediakan oleh Codex Raspberry Pi.

## Frontend contract

- The frontend receives model metadata through the existing vision WebSocket.
- The frontend receives GPS, heading, speed, and ordered track points through
  the existing telemetry broadcast.
- The RC transmitter remains the only Pixhawk control source; the dashboard
  exposes no control command.
- Dashboard status must distinguish model monitoring from autonomous control.

## Arsitektur

```text
Camera -> vision_test.py --manual-rc -> YOLO
                              |
                              +-> metadata/surface frame -> bridge -> dashboard

RC receiver -------------------------------> Pixhawk -> read-only telemetry -> bridge -> dashboard GPS
```

`vision_test.py` dan backend tidak boleh membuka dua jalur kendali MAVLink. Backend hanya membaca telemetry. Jika serial Pixhawk dipakai oleh Mission Planner/QGroundControl, aplikasi tersebut harus ditutup atau endpoint telemetry dipisahkan sebelum demo.

## Frontend changes

1. Update `dashboard/src/components/navigation-map.tsx` so the plotted path
   contains the ordered telemetry track followed by the current position when
   that position is not already the final point.
2. Keep one SVG polyline connecting each consecutive GPS point, the current
   boat marker, heading rotation, and the existing no-fix empty state.
3. Update the operational status copy in
   `dashboard/src/components/signal-rail.tsx` to show `MODEL MONITORING` and
   `RC MANUAL`; do not imply autonomous navigation.
4. Add focused frontend tests for current-position path continuity and the
   manual-control status copy. Keep the existing metadata and telemetry
   schemas unchanged.

The Raspberry Pi changes are explicitly out of scope for this session:
`vision_test.py --manual-rc`, Pixhawk connection handling, backend telemetry,
bridge publishing, and model inference wiring.

## Tracking map

The existing dashboard path plot is retained instead of adding a geographic
basemap. The map section represents the boat's movement over time:

- each valid GPS point is kept in chronological order;
- consecutive points are joined into one clear SVG polyline;
- the current position is shown as the final boat marker and included as the
  final path point when it is not already present;
- the marker rotates with heading when heading telemetry is available;
- no invented points or interpolation are added;
- without a valid GPS fix, the dashboard shows the existing empty state.

## Keamanan dan failure handling

- Frontend tidak memiliki tombol atau jalur untuk arm, disarm, mode change,
  parameter write, throttle, steering, atau RC override.
- Kegagalan bridge tidak boleh mengubah state kontrol Pixhawk.
- Jika GPS unavailable, dashboard tetap menampilkan model/camera dan status GPS
  unavailable.
- Jika model berhenti, dashboard menghapus overlay setelah stale timeout yang
  sudah ada.
- Label/status demo harus membedakan `MODEL MONITORING` dan `RC MANUAL` dari
  autonomous navigation.

## Acceptance criteria

- `NavigationMap` menghubungkan setiap titik telemetry berurutan menjadi satu
  jalur dan menyertakan posisi terbaru jika berbeda dari titik terakhir.
- Marker kapal menampilkan posisi terbaru dan rotasi heading jika tersedia.
- Dashboard menampilkan status `MODEL MONITORING` dan `RC MANUAL`.
- Metadata YOLO yang diterima tetap muncul pada overlay kamera yang ada.
- GPS, heading, speed, dan status unavailable tetap mengikuti kontrak telemetry.
- Unit test frontend lulus tanpa hardware.
- Tidak ada perubahan pada backend, model, Pixhawk, RC, atau dashboard API.
