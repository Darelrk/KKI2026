# Remote-Triggered Dashboard Capture Implementation Plan

For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

Goal: Memindahkan tombol capture dari KKI Dashboard ke KKI Remote, tetapi tetap menjalankan capture pada tab/browser KKI Dashboard sehingga file terunduh di device dashboard dan berisi gabungan dua kamera yang sudah ada. Setiap user yang membuka web dashboard KKI dan tersambung ke /ws/capture menerima event yang sama dan mengunduh JPEG gabungan masing-masing.

Architecture: KKI Remote mengirim POST /api/capture/request tanpa body ke backend Raspberry Pi. Backend meneruskan event melalui kanal khusus WS /ws/capture/{asv_id} kepada semua tab KKI Dashboard yang terhubung; setiap tab Dashboard menjalankan captureBothCameras() lokal dan downloadCameraCapture() yang sudah ada. Kanal capture terpisah dari telemetry dan PWM agar tidak merusak fallback polling, ACK control, atau kepemilikan Pixhawk.

Tech Stack: FastAPI, Python asyncio, React 19, TypeScript, native fetch, native WebSocket, Vitest, pytest, Cloudflare Tunnel.

## Kontrak wire

POST /api/capture/request

- Request body: empty
- Request headers: Origin dari browser KKI Remote (produksi: https://kki-remote.vercel.app), Accept: application/json
- 200 application/json: {"ok": true, "dashboards": N}
- dashboards = jumlah listener Dashboard yang menerima event saat request diproses; 0 berarti belum ada tab dashboard tersambung.
- Origin tidak terdaftar di ASV_CORS_ORIGINS → 403.

WS /ws/capture/{asv_id}

- Dashboard -> backend: tidak mengirim payload (hanya keepalive/ignore).
- backend -> Dashboard: {"type": "capture_request"}
- Validasi asv_id (harus sama dengan ASV_ID) dan Origin terhadap ASV_CORS_ORIGINS (exact match, tanpa wildcard).
- Event tidak diputar ulang saat reconnect; hanya request baru yang dikirim.
- Semua tab dashboard yang tersambung menerima event; masing-masing mengunduh capture lokal.
- Capture tidak membutuhkan ASV_REMOTE_CONTROL_ENABLED, tidak memakai /ws/control, tidak mengirim PWM, tidak mengubah pemilik koneksi Pixhawk.

## Koreksi state repo (verified 2026-09-14, main = ee3b5ac)

1. Branch `dashboard-manual-cutover` belum ada; buat dari `main`.
2. Restore remote-dashboard memakai `origin/feat/remote-dashboard-low-latency-control` (bukan nama lokal).
3. Root package.json di main hanya memuat workspace `dashboard`; entri remote-dashboard (workspace + scripts remote:*) harus direstore dari branch fitur sebelum check/build remote bisa jalan.
4. Origin produksi aktif: https://kki-remote.vercel.app dan https://kki-2026-dashboard.vercel.app (keduanya sudah ada di ASV_CORS_ORIGINS aktif di Pi). remote.monitor-kapal-pora-pora.web.id adalah hostname tunnel, bukan Origin browser.
5. allow_methods CORS di main.py sudah GET/POST/PUT (tidak perlu diubah).
6. Route tunnel untuk /ws/capture di hostname dashboard sudah tercakup catch-all 8080; route baru yang wajib hanya ^/api/capture/request$ pada remote.monitor-kapal-pora-pora.web.id sebelum ^/.*$ 404.
7. Di Pi, pytest harus memakai /opt/asv-dashboard/.venv/bin/python; full suite memerlukan PYTHONPATH=/opt/asv-dashboard/.venv/lib/python3.13/site-packages:/usr/lib/python3/dist-packages.

## Peta file

Backend (dikerjakan lebih dulu):

- Modify asv_dashboard_backend/main.py: registry listener capture, POST /api/capture/request, WS /ws/capture/{asv_id}.
- Do not modify control.py, telemetry.py, state.py, atau jalur submit PWM.
- Test tests/test_capture_relay.py.

KKI Dashboard (menyusul setelah backend):

- Create dashboard/src/lib/use-capture-requests.ts untuk listener WebSocket khusus.
- Modify dashboard/src/components/dashboard-client.tsx untuk meneruskan counter request.
- Modify dashboard/src/components/dashboard-shell.tsx untuk memanggil capture lokal saat counter berubah.
- Modify dashboard/src/components/telemetry-panel.tsx untuk menghapus tombol, tetapi mempertahankan status capture.
- Remove only dead capture-button CSS dari dashboard/src/styles.css.
- Update dashboard/src/lib/use-capture-requests.test.tsx, dashboard/src/components/dashboard-capture.test.tsx, dan dashboard/src/components/telemetry-panel.test.tsx.

KKI Remote (menyusul):

- Restore remote-dashboard/ dari origin/feat/remote-dashboard-low-latency-control + restore entri root package.json.
- Create remote-dashboard/src/lib/capture-request.ts untuk URL, bodyless POST, dan response validation.
- Modify remote-dashboard/src/app.tsx untuk tombol dan status hasil.
- Update remote-dashboard/tests/capture-request.test.ts, remote-dashboard/tests/remote-app.test.tsx, dan affected panel tests.

Deploy examples:

- Modify deploy/raspberry-pi/asv-dashboard.env.example comments so both Dashboard and Remote origins are explicit.
- Modify deploy/raspberry-pi/cloudflared-config.example.yml with capture routes before hostname catch-all 404. The active Pi config, not only this example, is authoritative.

## Task 1: Tambah relay backend capture (dikerjakan lebih dulu)

Files:

- Modify: asv_dashboard_backend/main.py.
- Create: tests/test_capture_relay.py.

Step 1: Tulis test merah (TestClient + dua koneksi WebSocket):

- POST /api/capture/request dengan listener dashboard tersambung → 200 {"ok": true, "dashboards": 1} dan listener menerima {"type": "capture_request"}.
- POST tanpa listener → 200 {"ok": true, "dashboards": 0}.
- Dua listener (dua tab) → dashboards: 2, keduanya menerima event.
- asv_id salah pada WS → ditolak.
- Origin WS tidak disetujui → ditolak.
- Origin POST tidak disetujui → 403.
- Listener disconnect → tidak crash backend, socket dibersihkan, POST berikutnya dashboards: 0.
- Pesan WS malformed dari client → tidak crash backend dan tidak mengubah state Pixhawk/control.

Step 2: python -m pytest tests/test_capture_relay.py -q memakai /opt/asv-dashboard/.venv/bin/python → gagal karena rute belum ada.

Step 3: Implementasi relay app-local di create_app:

```python
capture_sockets: set[WebSocket] = set()

@app.post("/api/capture/request")
async def post_capture_request(request: Request) -> dict[str, object]:
    origin = request.headers.get("origin")
    if origin not in resolved_settings.cors_origins:
        raise HTTPException(status_code=403, detail="origin not allowed")

    delivered = 0
    for socket in tuple(capture_sockets):
        try:
            await socket.send_json({"type": "capture_request"})
        except (RuntimeError, WebSocketDisconnect):
            capture_sockets.discard(socket)
        else:
            delivered += 1
    return {"ok": True, "dashboards": delivered}

@app.websocket("/ws/capture/{asv_id}")
async def capture_websocket(websocket: WebSocket, asv_id: str) -> None:
    origin = websocket.headers.get("origin")
    if (
        asv_id != resolved_settings.asv_id
        or origin not in resolved_settings.cors_origins
    ):
        await websocket.close(code=1008)
        return

    await websocket.accept()
    capture_sockets.add(websocket)
    try:
        while True:
            try:
                incoming = await websocket.receive()
            except WebSocketDisconnect:
                break
            if incoming.get("type") == "websocket.disconnect":
                break
    finally:
        capture_sockets.discard(websocket)
```

Jangan memasukkan event capture ke BridgeState.publish_telemetry.

Step 4: Full backend suite hijau (/opt/asv-dashboard/.venv/bin/python -m pytest -q dengan PYTHONPATH lengkap), deploy service backend, verifikasi:

- curl -fsS http://127.0.0.1:8080/healthz
- POST lokal dengan Origin https://kki-remote.vercel.app → dashboards: 0.
- Route tunnel ^/api/capture/request$ ditambahkan pada remote.monitor-kapal-pora-pora.web.id (config aktif) sebelum ^/.*$ 404; cloudflared tunnel ingress validate lalu restart service cloudflared.
- CORS preflight OPTIONS dari remote → mengizinkan Origin dan POST.
- POST publik tanpa dashboard → dashboards: 0.

Commit: "feat: relay remote capture requests to dashboard"

## Task 2: Dashboard listener (menyusul, frontend)

- Create dashboard/src/lib/use-capture-requests.ts + test: hook membuka ${asvTelemetryWsUrl}/ws/capture/{asvId} hanya mode direct; {"type":"capture_request"} menaikkan counter; JSON malformed/other types diabaikan; reconnect 2000ms saat closed; cleanup menutup socket.
- dashboard-client.tsx memanggil hook, meneruskan captureRequestCount ke DashboardShell.
- dashboard-shell.tsx trigger captureBothCameras() hanya saat counter berubah (bukan mount awal); refs dan captureBothCameras() tidak diubah.
- telemetry-panel.tsx: hapus tombol Capture, pertahankan captureState/captureFilename dan status saved/error.
- Update dashboard-capture.test.tsx dan telemetry-panel.test.tsx sesuai kontrak baru.

## Task 3: Remote capture button (menyusul, frontend)

- Restore remote-dashboard dari origin/feat/remote-dashboard-low-latency-control; restore entri root package.json (workspace + scripts remote:*); npm install; baseline check.
- Create remote-dashboard/src/lib/capture-request.ts + test: POST bodyless, Accept: application/json, validasi {"ok":true,"dashboards":N}.
- app.tsx: tombol "Capture di Dashboard" selalu tersedia (tidak tergantung PWM/ACK); status: dashboards>0 "Capture dikirim ke dashboard", dashboards=0 "Dashboard belum terbuka", error "Backend capture tidak tersedia".
- Update remote-app.test.tsx.

## Task 4: Deploy examples + verifikasi end-to-end

- Update env example (origin eksplisit: https://monitor-kapal-pora-pora.web.id untuk dashboard host, https://kki-remote.vercel.app untuk remote) — jangan hapus origin lama yang dipakai.
- Update cloudflared-config.example.yml dengan route ^/ws/capture/[^/]+$ (dashboard host) dan ^/api/capture/request$ (remote host) sebelum catch-all 404.
- Browser smoke test: dashboard di device A (dua feed kamera live), remote di device B, klik Capture → device A otomatis mengunduh JPEG gabungan, device B tidak; PWM/ACK/telemetry tidak berubah.
- Acceptance: klik remote → semua tab dashboard tersambung memicu capture lokal; tab tertutup → dashboards: 0.

## Self-review

- Semua user dashboard tersambung menerima event dan mengunduh lokal.
- Event tidak replay saat reconnect; counter per-request.
- Capture sepenuhnya independen dari PWM/ASV_REMOTE_CONTROL_ENABLED.
- Tidak ada wildcard CORS; ASV_CONTROL_TOKEN tetap Pi-only.
- Verifikasi produksi memakai Origin https://kki-remote.vercel.app, bukan hostname tunnel.
