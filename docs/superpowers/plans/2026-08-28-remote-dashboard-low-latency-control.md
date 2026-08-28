# Remote Dashboard Low-Latency Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menambahkan workspace `remote-dashboard/` yang hanya menampilkan satu raw surface camera Go2RTC (`atas`) dan dua slider direct PWM (`throttle_pwm` serta `steering_pwm`), dengan command persisten ke backend FastAPI existing dan deadman server 500 ms.

**Architecture:** Backend existing tetap satu process dan satu-satunya pemilik satu koneksi Pixhawk melalui `PixhawkTelemetryReader`. Adapter `/ws/control/{asv_id}` hanya melakukan exact Origin/ASV/feature gate, validasi strict, ownership/sequence/latest semantics, ack/error internal, lalu menyerahkan command ke reader; reader tetap satu-satunya pemanggil `RC_CHANNELS_OVERRIDE` dan me-release pada disconnect, expiry, shutdown, perubahan mode, heartbeat, flightmode, pilot-input, atau guard failure. Frontend remote adalah static package/project/domain Vercel terpisah yang terhubung langsung melalui Cloudflare Tunnel Pora Pora existing; UI tidak merender telemetry, status, latency, ack, mode, autonomy, underwater camera, model, YOLO, overlay, atau data lain.

**Tech Stack:** Python 3, FastAPI/Starlette WebSocket, Pydantic v2, `time.monotonic()`, threading lock, pytest/TestClient; React 19, TypeScript strict, Vite, Zod, Vitest/jsdom, Testing Library; Go2RTC WebRTC/MJPEG; Cloudflare Tunnel, systemd, Vercel static deployment.

---

## File map

### Backend dan test

- Modify `asv_dashboard_backend/config.py`: `remote_control_enabled=False`, `remote_command_timeout=0.5`, env parsing, timeout cap, dan syarat Pixhawk.
- Create `asv_dashboard_backend/control.py`: strict Pydantic `RemoteControlCommand`, `ControlAck`, `ControlError`, reject reasons, dan registry satu session per ASV; tidak mengimpor `pymavlink`.
- Modify `asv_dashboard_backend/main.py`: `/ws/control/{asv_id}`, exact handshake, supersede, sequence/latest semantics, internal ack/error, release disconnect, dan clear saat mode aplikasi menjadi `AUTONOMOUS`.
- Modify `asv_dashboard_backend/telemetry.py`: remote latest slot/session owner, monotonic expiry, guard, immediate release, dan arbitration melalui reader existing. Keep `asv_dashboard_backend/vision_publisher.py` unchanged.
- Create `tests/test_remote_control_protocol.py`; modify `tests/test_dashboard_backend.py` dan `tests/test_telemetry.py`.

### Deployment

- Modify `deploy/raspberry-pi/asv-dashboard.env.example`: safe defaults, timeout `0.5`, exact CORS origin guidance, dan token tetap Pi-only.
- Modify `deploy/raspberry-pi/cloudflared-config.example.yml`: host remote pada tunnel existing hanya untuk control WSS dan surface Go2RTC; host lama tetap.
- Keep `deploy/raspberry-pi/asv-dashboard.service` unchanged: satu Uvicorn `:8080`; Go2RTC existing tetap `127.0.0.1:1984`.

### Workspace baru

- Create `remote-dashboard/package.json`, `index.html`, `tsconfig.json`, `vite.config.ts`, `vitest.config.ts`, `vitest.setup.ts`, `vercel.json`.
- Create `remote-dashboard/src/main.tsx`, `src/app.tsx`, `src/styles.css`.
- Create `remote-dashboard/src/lib/control-protocol.ts`, `control-channel.ts`, `video-urls.ts` dan test masing-masing.
- Create `remote-dashboard/src/components/remote-control-panel.tsx`, `remote-surface-camera.tsx`, beserta test.
- Modify root `package.json` untuk workspace/script `remote:*`; update `package-lock.json` hanya melalui npm metadata.
- Tidak membuat `live-data.ts`, `remote-status-strip.tsx`, telemetry/status schema frontend, underwater player, atau data panel.

## Kontrak lintas task

- Production backend/video origin adalah `https://remote.monitor-kapal-pora-pora.web.id`; ASV id `default`; control URL adalah `wss://remote.monitor-kapal-pora-pora.web.id/ws/control/default`.
- Frontend env hanya `VITE_REMOTE_BACKEND_ORIGIN` dan `VITE_REMOTE_ASV_ID` dengan default id `default`; tidak ada token/service key.
- Frame strict object: `{ type:"control", seq, client_sent_at_ms, steering_pwm, throttle_pwm, enabled }`; `seq` positif meningkat ketat per session; timestamp integer epoch non-negatif; kedua PWM integer inclusive `1000..2000`; `enabled` boolean; field ekstra/hilang, float/string/bool sebagai integer, `NaN`, dan non-object ditolak.
- Ack/error dikirim dan diproses internal, bukan dirender. Ack `{type:"ack", seq, accepted, reason, client_sent_at_ms, server_received_at_ms}`; `accepted=true` hanya ingress/latest-slot accepted, bukan actuator applied. Error code hanya `invalid_json`, `invalid_message`, `origin_not_allowed` dan tidak memuat secret/stack trace.
- Reason reject: `stale_sequence`, `remote_control_disabled`, `runtime_mode_autonomous`, `pixhawk_unavailable`, `flightmode_not_manual`, `pilot_input_active`, `superseded`.
- Satu ASV hanya satu session. Session baru close session lama dengan code `4001`, clear/release old slot, lalu mulai sequence dari 1. Tidak ada queue histori.
- `ASV_REMOTE_CONTROL_ENABLED` default `false`; enabling membutuhkan `ASV_PIXHAWK_ENABLED=true`. `ASV_REMOTE_COMMAND_TIMEOUT` default/deployment `0.5`, dan konfigurasi menolak nilai `>0.5`.
- Deadman memakai `time.monotonic()` server sejak command diterima. Reader hanya mengirim latest remote command yang masih owner, berumur `<=0.5` detik, dan lolos feature flag, `BridgeState.control_mode == MANUAL`, connection/heartbeat, observed `_mode == MANUAL`, pilot-input guard, serta validasi actuator.
- `POST /api/control/actuator` dan `ASV_CONTROL_TOKEN` tetap untuk publisher/model Pi-only; remote channel tidak memakai endpoint tersebut. CORS HTTP dan Origin WebSocket exact allowlist tanpa wildcard, `allow_credentials=false`; allowlist bukan autentikasi.
- Camera hanya Go2RTC `wss://remote.monitor-kapal-pora-pora.web.id/api/ws?src=atas`, `/api/webrtc`, `/api/stream.mp4`, dan raw fallback `https://remote.monitor-kapal-pora-pora.web.id/stream/atas`. Tidak ada `bawah`, `/ws/vision`, vision metadata, model, YOLO, canvas, atau overlay.

---

### Task 1: Backend protocol, konfigurasi, dan persistent WebSocket

**Files:** `asv_dashboard_backend/config.py`, `asv_dashboard_backend/control.py`, `asv_dashboard_backend/main.py`, `tests/test_remote_control_protocol.py`, `tests/test_dashboard_backend.py`.

- [ ] **Step 1: Tulis failing tests.** Tambahkan test default setting (`false`, `0.5`), env remote tanpa Pixhawk ditolak, timeout `0`/`>0.5` ditolak, strict PWM/sequence/object schema, ack reason coherence, registry duplicate/supersede, valid WebSocket ack, invalid JSON internal, wrong ASV/Origin/feature close `1008`, `enabled=false`, close sesi lama `4001`, dan remote input tidak memanggil `submit_actuator_command`.

```python
VALID = {
    "type": "control", "seq": 1, "client_sent_at_ms": 10,
    "steering_pwm": 1490, "throttle_pwm": 1550, "enabled": True,
}

def test_remote_command_is_strict() -> None:
    assert RemoteControlCommand.model_validate(VALID).steering_pwm == 1490
    for key, value in (("steering_pwm", 999), ("throttle_pwm", 2001),
                       ("steering_pwm", 1490.5), ("throttle_pwm", "1550"),
                       ("seq", True)):
        with pytest.raises(ValidationError):
            RemoteControlCommand.model_validate({**VALID, key: value})
    with pytest.raises(ValidationError):
        RemoteControlCommand.model_validate({**VALID, "extra": True})

def test_registry_keeps_one_active_session_and_strict_sequence() -> None:
    registry = ControlSessionRegistry()
    first, previous = registry.open("default", "first")
    assert previous is None
    assert registry.validate_sequence(first, 1) is None
    assert registry.validate_sequence(first, 1) == "stale_sequence"
    second, previous = registry.open("default", "second")
    assert previous == first
    assert registry.validate_sequence(first, 2) == "superseded"
    assert registry.validate_sequence(second, 1) is None
```

- [ ] **Step 2: Jalankan test untuk memastikan gagal.**

```bash
python -m pytest -q tests/test_remote_control_protocol.py tests/test_dashboard_backend.py -k "remote or control_protocol"
```

Expected: `FAIL` karena setting, module protocol, registry, dan route belum tersedia.

- [ ] **Step 3: Implementasikan kontrak minimum.** `control.py` memakai `ConfigDict(extra="forbid", strict=True)`, integer fields bounded by `1000..2000`/safe JavaScript integer `9007199254740991`, `ControlAck` validator bahwa accepted iff reason null, `ControlError` dengan tiga code, dan `ControlSessionRegistry` dengan `open()`, `validate_sequence()`, serta owner-scoped `release()`.

```python
class RemoteControlCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["control"]
    seq: int = Field(gt=0, le=9_007_199_254_740_991)
    client_sent_at_ms: int = Field(ge=0, le=9_007_199_254_740_991)
    steering_pwm: int = Field(ge=1000, le=2000)
    throttle_pwm: int = Field(ge=1000, le=2000)
    enabled: bool
```

Tambahkan settings fields/env parser/validation sesuai kontrak. Di `main.py`, buat satu registry dan session→WebSocket map per `create_app()`. Tolak ASV mismatch, Origin kosong/tidak allowlisted, atau feature disabled sebelum `accept()` dengan close `1008`. Setelah accept, supersede old session, clear reader old owner, close old socket `4001`, parse JSON/schema, dan kirim error constant untuk malformed frame. Valid frame dicatat epoch/monotonic server; stale/superseded menghasilkan rejected ack; `enabled=false` clear/release; `enabled=true` cek application mode dan reader guard, lalu submit ke reader. `finally` hanya owner aktif yang boleh clear. Existing `PUT /api/control/mode` memanggil clear saat mode menjadi `AUTONOMOUS`; route remote tidak mengubah mode.

- [ ] **Step 4: Jalankan test untuk memastikan lulus.**

```bash
python -m pytest -q tests/test_remote_control_protocol.py tests/test_dashboard_backend.py -k "remote or control_protocol or actuator_endpoint or control_mode"
```

Expected: semua test `PASS`; ack/error internal tepat, Origin/ASV/feature gate aman, one-session/sequence/latest semantics berlaku, no POST-per-input, dan endpoint actuator existing tetap.

- [ ] **Step 5: Commit.**

```bash
git add asv_dashboard_backend/config.py asv_dashboard_backend/control.py asv_dashboard_backend/main.py tests/test_remote_control_protocol.py tests/test_dashboard_backend.py
git commit -m "feat: add remote control websocket protocol"
```

---

### Task 2: Telemetry reader, deadman, guards, dan immediate release

**Files:** `asv_dashboard_backend/telemetry.py`, `tests/test_telemetry.py`.

- [ ] **Step 1: Tulis failing tests.** Dengan fake MAV connection, uji remote direct PWM ketika observed `_mode="MANUAL"` dan heartbeat sehat; inject monotonic `10.0 → 10.501` dan pastikan release tuple `(1,1,0,0,0,0,0,0,0,0)`; owner mismatch tidak clear, owner clear release immediate, shutdown release, heartbeat/flightmode/pilot rejection, dan remote submit tidak memanggil `mavutil.mavlink_connection`.

- [ ] **Step 2: Jalankan test untuk memastikan gagal.**

```bash
python -m pytest -q tests/test_telemetry.py -k "remote or expiry or pilot"
```

Expected: `FAIL` karena slot remote, guard reason, expiry, dan clear belum ada.

- [ ] **Step 3: Implementasikan slot remote memakai `_actuator_lock` existing.** Tambahkan `_remote_command`, `_remote_session_id`, `_remote_command_at`, `submit_remote_control(command, session_id, received_at)`, dan `clear_remote_control(session_id=None)` yang hanya me-release jika owner cocok. `remote_control_rejection_reason()` mengembalikan reason literal untuk feature, connection/heartbeat, observed flightmode, dan pilot guard.

```python
def clear_remote_control(self, session_id=None):
    with self._actuator_lock:
        if session_id is not None and self._remote_session_id != session_id:
            return False
        had_command = self._remote_command is not None
        self._remote_command = None
        self._remote_session_id = None
        self._remote_command_at = float("-inf")
    if had_command or self._override_active:
        self._release_actuator_override()
    return had_command
```

Ubah `_apply_actuator_command()` hanya pada pemilihan command: remote latest memakai timeout `remote_command_timeout`, remote kosong memakai model lane existing dengan timeout existing; kedua lane melewati seluruh connection, heartbeat, observed `MANUAL`, pilot, PWM, dan release guard. `_reset_connection()` dan `close()` clear remote sebelum menutup link. Tidak ada socket/reader Pixhawk baru.

- [ ] **Step 4: Jalankan test untuk memastikan lulus.**

```bash
python -m pytest -q tests/test_telemetry.py -k "remote or expiry or pilot or unified_worker"
```

Expected: test remote expiry/clear/guards/shutdown/no-second-connection dan test model actuator existing `PASS`.

- [ ] **Step 5: Commit.**

```bash
git add asv_dashboard_backend/telemetry.py tests/test_telemetry.py
git commit -m "feat: enforce remote PWM deadman in Pixhawk reader"
```

---

### Task 3: Cloudflare Tunnel dan Pi deployment minimal

**Files:** `deploy/raspberry-pi/asv-dashboard.env.example`, `deploy/raspberry-pi/cloudflared-config.example.yml`; keep `deploy/raspberry-pi/asv-dashboard.service` unchanged.

- [ ] **Step 1: Tulis failing config check.**

```bash
python -c "from pathlib import Path; p=Path('deploy/raspberry-pi/cloudflared-config.example.yml').read_text(); required=['remote.monitor-kapal-pora-pora.web.id','^/ws/control/','^/api/ws$','^/stream/atas$']; assert all(x in p for x in required)"
```

Expected sebelum edit: `AssertionError` karena route minimal remote belum ada.

- [ ] **Step 2: Implementasikan env dan ingress.** Tambahkan `ASV_REMOTE_CONTROL_ENABLED=false` dan `ASV_REMOTE_COMMAND_TIMEOUT=0.5`; pertahankan `ASV_PIXHAWK_ENABLED=false` pada contoh umum. Runtime Pi pengendali mengubah Pixhawk menjadi `true` dan mengisi `ASV_CORS_ORIGINS` dengan exact HTTPS origin Vercel serta optional `http://localhost:3001`; tidak ada wildcard, token, atau secret frontend.

Tambahkan sebelum catch-all Cloudflare route berikut, tanpa mengganti host lama:

```yaml
  - hostname: remote.monitor-kapal-pora-pora.web.id
    path: ^/ws/control/[^/]+$
    service: http://127.0.0.1:8080
  - hostname: remote.monitor-kapal-pora-pora.web.id
    path: ^/api/ws$
    service: http://127.0.0.1:1984
  - hostname: remote.monitor-kapal-pora-pora.web.id
    path: ^/api/webrtc$
    service: http://127.0.0.1:1984
  - hostname: remote.monitor-kapal-pora-pora.web.id
    path: ^/api/stream\.mp4$
    service: http://127.0.0.1:1984
  - hostname: remote.monitor-kapal-pora-pora.web.id
    path: ^/stream/atas$
    service: http://127.0.0.1:1984
  - hostname: remote.monitor-kapal-pora-pora.web.id
    path: ^/.*$
    service: http_status:404
```

Cloudflared meneruskan upgrade WebSocket tanpa buffering/proxy Vercel. Host remote tidak merutekan `/api/status`, `/api/telemetry`, `/ws/vision`, vision metadata, actuator POST, mode mutation, frame upload, atau underwater stream. Existing systemd tetap satu Uvicorn `:8080`; Go2RTC tetap local `:1984`.

- [ ] **Step 3: Jalankan validasi deployment.**

```bash
cloudflared tunnel ingress validate --config deploy/raspberry-pi/cloudflared-config.example.yml
python -c "from pathlib import Path; p=Path('deploy/raspberry-pi/asv-dashboard.service').read_text(); assert p.count('uvicorn asv_dashboard_backend.main:app') == 1; assert '1984' not in p"
```

Expected: `Validating ingress rules: OK`, lalu command Python selesai tanpa output.

- [ ] **Step 4: Commit.**

```bash
git add deploy/raspberry-pi/asv-dashboard.env.example deploy/raspberry-pi/cloudflared-config.example.yml
git commit -m "ops: route minimal remote control and surface video"
```

---

### Task 4: Remote app minimal — satu camera dan dua slider direct PWM

**Files:** seluruh `remote-dashboard/`, root `package.json`, `package-lock.json`.

- [ ] **Step 1: Tulis failing frontend tests.** Tulis Vitest/Testing Library tests untuk Zod strict; channel internal one socket, sequence 1, latest-only refresh `200 ms`, `enabled=false`, ack/error/timeout/reconnect, dan no auto-enable; URL control WSS exact dan video hanya `src=atas`; panel tepat dua slider default `1500` tanpa button; slider pointer/focus/keyboard mengaktifkan direct pair dan release; camera one Go2RTC socket receive-only dan raw fallback tiga detik; app tidak memanggil `fetch` dan tidak memiliki telemetry/status/latency/ack/mode/underwater/model/YOLO/overlay.

```typescript
it('renders only the two direct PWM sliders', () => {
  render(<RemoteControlPanel channel={makeFakeChannel()} />)
  expect(screen.getByLabelText('Throttle PWM')).toHaveValue(1500)
  expect(screen.getByLabelText('Steering PWM')).toHaveValue(1500)
  expect(screen.queryByRole('button')).toBeNull()
  expect(screen.queryByText(/telemetry|status|latency|ack|autonomous|arm|disarm/i)).toBeNull()
})

it('uses one surface Go2RTC path', () => {
  expect(buildGo2RtcUrls('https://remote.monitor-kapal-pora-pora.web.id')).toEqual({
    signaling: 'wss://remote.monitor-kapal-pora-pora.web.id/api/ws?src=atas',
    webrtc: 'https://remote.monitor-kapal-pora-pora.web.id/api/webrtc',
    streamMp4: 'https://remote.monitor-kapal-pora-pora.web.id/api/stream.mp4',
    mjpeg: 'https://remote.monitor-kapal-pora-pora.web.id/stream/atas',
  })
})
```

- [ ] **Step 2: Jalankan test untuk memastikan gagal.**

```bash
npm run test --workspace remote-dashboard -- src/lib src/components
```

Expected: `FAIL` karena workspace dan module remote belum dibuat.

- [ ] **Step 3: Buat package/config dan implementasikan kontrak UI minimum.** `remote-dashboard/package.json` memakai React/React DOM/Zod, Vite/TypeScript/Vitest/jsdom/Testing Library, serta script `dev` port `3001`, `build`, `preview`, `test`, `typecheck`, `check`. Root workspace menambah `remote-dashboard` serta `remote:*` scripts tanpa mengganti dashboard lama. `vercel.json` memakai build `npm run build`, output `dist`, SPA rewrite ke `/index.html`.

`control-protocol.ts` menyamakan Pydantic strict dan safe integer; `control-channel.ts` memakai satu WebSocket, latest pair, sequence reset 1 per socket session, refresh `200 ms`, pending ack/RTT/error/timeout internal, reconnect `250/500/1000/2000/5000 ms`, dan no auto-enable setelah close. `buildControlUrl()` memetakan HTTPS→WSS/HTTP→WS serta menghasilkan `/ws/control/default`.

`video-urls.ts` hanya menghasilkan `api/ws?src=atas`, `api/webrtc`, `api/stream.mp4`, dan `/stream/atas`; `remote-surface-camera.tsx` membuat satu peer receive-only/signaling socket, offer/answer/candidate sesuai Go2RTC, membersihkan peer/socket/timer, lalu memakai raw `<img>` setelah tiga detik/error/close.

`remote-control-panel.tsx` hanya merender dua `<input type="range" min="1000" max="2000" step="1">` berlabel `Throttle PWM` dan `Steering PWM`, default `1500`. Pointer down/focus keyboard movement memanggil internal `enable(pair)`; pointer up/cancel/blur/key release memanggil `disable()`; perubahan saat aktif memanggil `update(pair)`. Tidak ada button tambahan, ack/status/error/latency text, mode/autonomy, arm/disarm, atau command normalized. Semua input invalid tidak mengubah pair dan tidak mengirim command.

`RemoteApp` membuat satu channel, connect mount, close unmount, dan hanya merender surface camera + panel. `main.tsx` hanya membaca `VITE_REMOTE_BACKEND_ORIGIN` serta `VITE_REMOTE_ASV_ID || 'default'`; tidak ada `fetch`/live-data. CSS biasa hanya untuk layout camera, focus-visible, dan slider accessibility.

- [ ] **Step 4: Jalankan test/typecheck/build.**

```bash
npm install --package-lock-only
npm run test --workspace remote-dashboard -- --run
npm run typecheck --workspace remote-dashboard
npm run build --workspace remote-dashboard
```

Expected: test/typecheck `PASS`, Vite menghasilkan `remote-dashboard/dist/index.html`, tepat satu camera dan dua slider teruji, serta tidak ada telemetry/status/latency display, underwater path, model/YOLO/overlay, atau POST fallback. Jangan commit generated `dist/`.

- [ ] **Step 5: Commit.**

```bash
git add package.json package-lock.json remote-dashboard
git commit -m "feat: add minimal remote PWM and surface camera app"
```

---

### Task 5: Safety test matrix dan regression

**Files:** `tests/test_remote_control_protocol.py`, `tests/test_dashboard_backend.py`, `tests/test_telemetry.py`, serta test remote dari Task 4.

- [ ] **Step 1: Lengkapi failing/contract tests.** Coverage wajib:
  - schema menolak 999/2001/float/string/bool/extra/missing/non-object; ack timestamps/reasons; malformed JSON internal;
  - duplicate/out-of-order tidak mengganti latest; tidak ada command queue;
  - wrong ASV, Origin kosong/unknown, feature disabled close `1008`; one active session, supersede `4001`, old clear tidak menghapus new;
  - disconnect, `enabled=false`, monotonic `>500 ms`, backend shutdown, `AUTONOMOUS`, heartbeat stale, observed flightmode bukan `MANUAL`, pilot input, dan actuator validation release;
  - injected reader membuktikan remote memakai reader existing dan tidak membuat Pixhawk connection kedua; existing token `POST /api/control/actuator` tetap;
  - frontend tepat satu surface + dua slider, no fetch/data display, no underwater/vision/model/overlay, no UI ack/status/latency, reconnect/no auto-enable, release blur/unmount.

- [ ] **Step 2: Jalankan matrix.**

```bash
python -m pytest -q tests/test_remote_control_protocol.py tests/test_dashboard_backend.py tests/test_telemetry.py
npm run test --workspace remote-dashboard -- --run
```

Expected: seluruh test `PASS`, termasuk disconnect/expiry/guards/no duplicate Pixhawk dan scope UI minimal.

- [ ] **Step 3: Jalankan regression tanpa area terlarang.**

```bash
python -m pytest -q tests/test_dashboard_backend.py tests/test_telemetry.py
npm run remote:typecheck
```

Expected: dashboard backend lama, model POST, telemetry lifecycle, dan remote typecheck `PASS`; tidak ada perubahan pada `simulation/`, `model/`, atau `worlds/`.

- [ ] **Step 4: Commit test bila belum tercakup commit implementasi.**

```bash
git add tests remote-dashboard/src
 git commit -m "test: cover remote control safety and minimal UI"
```

---

### Task 6: Vercel, DevTools smoke, latency measurement, rollout, dan rollback

**Files:** deployment/runtime only setelah Tasks 1–5; tidak menambah UI status/telemetry/latency.

- [ ] **Step 1: Deploy project Vercel terpisah.** Set root directory `remote-dashboard`, framework Vite, build `npm run build`, output `dist`, SPA rewrite dari `vercel.json`, dan hanya env public:

```text
VITE_REMOTE_BACKEND_ORIGIN=https://remote.monitor-kapal-pora-pora.web.id
VITE_REMOTE_ASV_ID=default
```

Run `vercel --cwd remote-dashboard --prod`; catat origin production output apa adanya untuk allowlist Pi. Jangan set `ASV_CONTROL_TOKEN`, secret, service key, proxy, atau API route Vercel.

- [ ] **Step 2: Validasi route minimal sebelum enable.** Pada Pi pengendali set runtime `ASV_PIXHAWK_ENABLED=true`, `ASV_REMOTE_CONTROL_ENABLED=false`, `ASV_REMOTE_COMMAND_TIMEOUT=0.5`, serta exact Vercel origin pada `ASV_CORS_ORIGINS`; optional development origin hanya `http://localhost:3001`. Restart service existing dan jalankan:

```bash
cloudflared tunnel ingress validate --config deploy/raspberry-pi/cloudflared-config.example.yml
curl -i https://remote.monitor-kapal-pora-pora.web.id/stream/atas
```

Expected: ingress `OK`, raw surface response `200` dengan MJPEG content type; control socket production close `1008` karena feature disabled.

- [ ] **Step 3: DevTools smoke minimal.** Di halaman production pastikan hanya dua slider dan satu surface camera; tidak ada status, telemetry, latency, ack, mode, autonomy, underwater, atau data lain. Network hanya melihat Go2RTC `/api/ws?src=atas` atau fallback `/stream/atas`; tidak ada `/api/ws?src=bawah`, `/ws/vision`, vision metadata, model/YOLO, canvas, atau POST actuator. WS control tepat `wss://remote.monitor-kapal-pora-pora.web.id/ws/control/default`; slider mengirim direct integer PWM dan release internal `enabled=false`; ack tidak dirender. WebRTC timeout tiga detik membersihkan resource dan menampilkan raw MJPEG tanpa memengaruhi control channel.

- [ ] **Step 4: Bench enable dan safety verification.** Dengan propeller aman/disconnected, transmitter tersedia, observed Pixhawk mode `MANUAL`, heartbeat sehat, pilot neutral, dan satu reader terbukti, ubah `ASV_REMOTE_CONTROL_ENABLED=true` tanpa menaikkan timeout, lalu restart service. Uji Origin/ASV/feature rejection, second-tab supersede `4001`, slider release, close tab/network, frame stop `>500 ms`, autonomous mode, heartbeat loss, flightmode change, dan pilot input; setiap kasus harus release tanpa synthetic success/neutral command.

- [ ] **Step 5: Ukur corrected p95 tanpa panel UI.** Sinkronkan NTP dan catat offset browser↔Pi; jangan klaim one-way latency tanpa correction. Dari DevTools console, buka WSS control, kirim 1000 frame `enabled:true` berisi `1500/1500` setiap `200 ms` dengan sequence unik, kumpulkan `server_received_at_ms - client_sent_at_ms - correctedOffset`, lalu kirim satu `enabled:false` dan close. Simpan p50/p95/p99/max, frame loss, reconnect count, dan RTT p95 sebagai artifact operasional, bukan UI. Acceptance p95 corrected `<=100 ms` pada controlled/near-edge network; Internet publik di luar target tidak boleh melemahkan deadman `500 ms`. Ack hanya ingress evidence, bukan actuator applied.

- [ ] **Step 6: Rollback.** Set `ASV_REMOTE_CONTROL_ENABLED=false`, restart `asv-dashboard.service`, pastikan reader release dan handshake close `1008`. Jika tunnel gagal, remove host remote atau ubah host remote menjadi `http_status:404` tanpa menyentuh host lama. Jika video gagal, rollback route/player Go2RTC ke raw `/stream/atas`; jangan membuat backend/Pixhawk kedua atau mengubah deadman.

---

## Non-goals

Tidak mengganti dashboard lama; tidak menampilkan telemetry/status/latency/ack/error atau data lain pada remote UI; tidak ada underwater camera; tidak ada backend cloud, Vercel Function/proxy, database realtime, Supabase, application auth, Cloudflare Access, token frontend, browser MAVLink, Pixhawk connection kedua, arm/disarm, mode/parameter/mission mutation, autonomous runner, firmware/mekanik/navigation change, YOLO/model/inference, vision metadata, canvas/overlay/tracking, sensor fusion, atau synthetic fallback command. P95 ≤100 ms adalah pengukuran operasional input→backend latest slot setelah clock correction, bukan SLA Internet atau jaminan actuator fisik; deadman server 500 ms tidak dapat dinaikkan.

## Self-review singkat

- Enam task mencakup protocol/config/route, single-reader deadman/guards, tunnel/Pi, workspace satu surface + dua slider, safety regression, serta Vercel/DevTools/measurement/rollback.
- Kontrak konsisten pada `default`, PWM `1000..2000`, WSS path, exact Origin, sequence/ack internal, refresh `200 ms`, timeout `0.5`, dan satu Pixhawk owner.
- Tidak ada live-data/status/telemetry/latency panel, underwater/model/YOLO/overlay, atau perubahan `simulation/`, `model/`, `worlds/`; hanya plan ini yang menjadi target commit.
