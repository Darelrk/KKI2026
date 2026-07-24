# Raspberry Pi Manual RC Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a hardware-safe `vision_test.py --manual-rc` path for Raspberry Pi model monitoring, preserve the existing read-only bridge telemetry contract, document Pi handover, and push the complete work on `feat/manual-rc-dashboard-frontend`.

**Architecture:** Keep the existing Pixhawk control path unchanged when `--manual-rc` is absent. Add one explicit creation guard so manual mode never constructs `PixhawkLink`; manual mode continues camera capture, YOLO inference, overlay/logging, and `BridgeFramePublisher` metadata/frame publishing. The FastAPI bridge's existing `PixhawkTelemetryReader` remains an independent read-only telemetry path controlled by `ASV_PIXHAWK_ENABLED`.

**Tech Stack:** Python 3, argparse, existing Ultralytics/OpenCV runtime, pymavlink only for non-manual mode, FastAPI, Pydantic, pytest, systemd deployment files.

---

## Files and responsibilities

- Modify `vision_test.py`: add `--manual-rc`, gate Pixhawk construction and all Pixhawk cleanup/commands, keep model/bridge behavior active.
- Modify `vision_route.py`: preserve the already-present target tracker and dynamic throttle changes in the dirty working tree; do not overwrite them.
- Modify `tests/test_vision_route.py`: preserve and run the existing throttle/tracker tests already present in the dirty working tree.
- Create `tests/test_manual_rc.py`: test the CLI flag and the no-Pixhawk construction boundary without hardware.
- Modify `asv_dashboard_backend/main.py`: keep the bridge API unchanged while making WebSocket receive-task cleanup deterministic.
- Modify `deploy/raspberry-pi/test-backend.sh`: install test-only packages and run the complete backend/vision test set.
- Modify `start-all-local.bat` and `start-vision-test.bat`: preserve the existing user tuning and endpoint quoting; do not add manual mode to the control-oriented Windows shortcuts.
- Create `handover.md`: give the Raspberry Pi agent exact branch, sync, run, safety, verification, and reporting instructions.
- Create `docs/superpowers/specs/2026-07-24-raspi-manual-rc-backend-design.md`: record the approved backend design.

The existing `asv_dashboard_backend/telemetry.py`, `config.py`, and bridge API
remain unchanged because they already implement the required read-only telemetry
contract. `main.py` changes only WebSocket task cleanup; do not modify dashboard
schemas or add control endpoints.

### Task 1: Add failing manual-RC boundary tests

**Files:**
- Create: `tests/test_manual_rc.py`

- [ ] **Step 1: Write parser and construction-guard tests**

Create this exact test file:

```python
import argparse
import sys

import vision_test


def test_parse_args_accepts_manual_rc(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["vision_test.py", "--manual-rc", "--model", "model/best.pt"],
    )

    args = vision_test.parse_args()

    assert args.manual_rc is True


def test_manual_rc_does_not_construct_pixhawk(monkeypatch) -> None:
    class PixhawkMustNotStart:
        def __init__(self, endpoint: str) -> None:
            raise AssertionError(f"Pixhawk opened unexpectedly: {endpoint}")

    monkeypatch.setattr(vision_test, "PixhawkLink", PixhawkMustNotStart)

    assert (
        vision_test.create_pixhawk_link(
            manual_rc=True,
            endpoint="/dev/ttyACM0",
        )
        is None
    )


def test_control_mode_still_constructs_pixhawk(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setattr(vision_test, "PixhawkLink", lambda endpoint: sentinel)

    assert (
        vision_test.create_pixhawk_link(
            manual_rc=False,
            endpoint="/dev/ttyACM0",
        )
        is sentinel
    )
```

- [ ] **Step 2: Run the new tests and verify they fail for the missing flag/guard**

Run from `D:\KKI2\KKI2026`:

```powershell
python -m pytest -q tests/test_manual_rc.py
```

Expected before implementation: collection/test failure because `parse_args` has no `manual_rc` attribute and `create_pixhawk_link` does not exist.

### Task 2: Implement the manual-RC execution boundary

**Files:**
- Modify: `vision_test.py`

- [ ] **Step 1: Add the CLI flag**

Add this argument in `parse_args()` before the endpoint argument:

```python
parser.add_argument(
    "--manual-rc",
    action="store_true",
    help="Model monitoring only; never open Pixhawk or send MAVLink commands",
)
```

- [ ] **Step 2: Add the testable Pixhawk construction guard**

Add this function after the `PixhawkLink` class and before `parse_args()`:

```python
def create_pixhawk_link(
    *,
    manual_rc: bool,
    endpoint: str,
) -> PixhawkLink | None:
    """Create the control link only for the legacy control path."""
    if manual_rc:
        return None
    return PixhawkLink(endpoint)
```

- [ ] **Step 3: Make dependency messaging accurate for manual mode**

Replace the current `ImportError` message in `main()` with:

```python
    except ImportError as exc:
        dependencies = "ultralytics opencv-python"
        if not args.manual_rc:
            dependencies += " pymavlink pyserial"
        raise RuntimeError(
            f"Dependensi belum lengkap. Jalankan: python -m pip install {dependencies}"
        ) from exc
```

- [ ] **Step 4: Construct no Pixhawk link in manual mode**

Replace:

```python
    link = PixhawkLink(args.endpoint)
```

with:

```python
    link = create_pixhawk_link(
        manual_rc=args.manual_rc,
        endpoint=args.endpoint,
    )
```

- [ ] **Step 5: Guard camera-failure cleanup**

Replace the unconditional `link.close()` in the camera-open failure block with:

```python
        if link is not None:
            link.close()
```

- [ ] **Step 6: Keep YOLO/bridge active but bypass all Pixhawk calls in the frame loop**

After `target_x = target_tracker.update(last_detections, now=now)`, keep target tracking for the local overlay, then replace the current steering/throttle/Pixhawk block with:

```python
                if args.manual_rc:
                    steering_pwm = NEUTRAL_PWM
                    throttle_pwm = NEUTRAL_PWM
                    mode = "RC_MANUAL"
                    telemetry = {
                        "mode": "RC_MANUAL",
                        "armed": None,
                        "rc1": None,
                        "rc3": None,
                        "servo1": None,
                        "servo3": None,
                    }
                else:
                    steering_pwm = (
                        compute_steering_pwm(
                            target_x,
                            frame.shape[1],
                            gain=args.gain,
                            invert=args.invert_steering,
                        )
                        if target_x is not None
                        else NEUTRAL_PWM
                    )
                    throttle_pwm = throttle_controller.update(
                        last_detections,
                        frame_width=int(frame.shape[1]),
                        frame_height=int(frame.shape[0]),
                        steering_pwm=steering_pwm,
                        now=now,
                    )

                    try:
                        mode = link.mode()
                        if mode == "MANUAL":
                            link.send_override(steering_pwm, throttle_pwm)
                        else:
                            throttle_pwm = throttle_controller.reset(now)
                            target_tracker.reset()
                            link.release_override()
                        telemetry = link.telemetry()
                    except Exception as exc:
                        throttle_pwm = throttle_controller.reset(now)
                        target_tracker.reset()
                        link.release_override()
                        mode = "MAVLINK_ERROR"
                        telemetry = {
                            "servo1": None,
                            "servo3": None,
                            "armed": False,
                            "error": str(exc),
                        }
```

`link` is non-optional inside the `else` branch because `create_pixhawk_link()` returns a link whenever `manual_rc` is false; add `assert link is not None` immediately before `mode = link.mode()` if the type checker requires narrowing.

- [ ] **Step 7: Guard final Pixhawk cleanup**

Replace the unconditional cleanup block beginning with `link.send_override(...)` with:

```python
        if link is not None:
            try:
                link.send_override(NEUTRAL_PWM, NEUTRAL_PWM)
                time.sleep(0.1)
                link.release_override()
            finally:
                link.close()
```

Print a mode-specific final message:

```python
        if link is None:
            print("Model monitoring berhenti; Pixhawk tidak diakses.")
        else:
            print("Override dilepas; script berhenti dengan throttle netral.")
```

Do not add any Pixhawk call to the manual branch. The existing bridge status-offline publish and `bridge.close()` remain in the same `finally` block.

- [ ] **Step 8: Run the focused tests**

```powershell
python -m pytest -q tests/test_manual_rc.py tests/test_vision_route.py
```

Expected: all manual-RC, target-tracker, throttle, and route tests pass without a serial device or model file.

### Task 3: Write Raspberry Pi handover

**Files:**
- Create: `handover.md`

- [ ] **Step 1: Write the exact operator handover**

Create `handover.md` with these sections and commands:

```markdown
# Handover Raspberry Pi — Manual RC + Model Monitoring

## Branch dan baseline

- Repository: `https://github.com/Darelrk/KKI2026.git`
- Branch: `feat/manual-rc-dashboard-frontend`
- Baseline `main` saat handover: `1416008`
- Jalur `--manual-rc` menjalankan YOLO dan publisher saja.

## Sinkronisasi di Pi

```bash
cd /home/pi/KKI2026
git status --short
# Jika working tree bersih:
git fetch origin
git switch feat/manual-rc-dashboard-frontend
git pull --ff-only origin feat/manual-rc-dashboard-frontend
```

Jangan memakai `reset --hard`, `clean`, stash otomatis, atau pull di atas
working tree dirty. Laporkan lima perubahan vision lokal jika masih ada.

## Backend bridge

```bash
sudo systemctl start asv-stack.target
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/api/status
curl -fsS http://127.0.0.1:8080/api/telemetry
```

`ASV_PIXHAWK_ENABLED=false` adalah pilihan aman jika Pixhawk sedang digunakan
oleh transmitter/QGroundControl/Mission Planner melalui port yang sama.
Aktifkan hanya jika jalur telemetry terpisah dan tetap read-only.

## Menjalankan model manual RC

```bash
cd /home/pi/KKI2026
python3 vision_test.py \
  --manual-rc \
  --model /home/pi/KKI2026/model/best.pt \
  --camera 0 \
  --bridge-url http://127.0.0.1:8080 \
  --bridge-asv-id default
```

Jangan tambahkan `--endpoint` untuk mode manual RC; mode ini tidak boleh
membuka Pixhawk. Jika dashboard memerlukan raw surface URL, konfigurasikan
`ASV_STREAM_URL` pada `/etc/asv-dashboard.env`. Transmitter RC tetap
menjadi satu-satunya sumber steering/throttle.

## Safety contract

Mode `--manual-rc` tidak boleh:

- mengimpor atau membuka koneksi serial/TCP/UDP Pixhawk;
- menjalankan `ARMING_CHECK`;
- mengirim `MAV_CMD_COMPONENT_ARM_DISARM`;
- mengirim `RC_CHANNELS_OVERRIDE`;
- mengubah mode, throttle, atau steering kapal.

Mode ini tetap boleh menjalankan kamera, YOLO, overlay lokal, log JSONL,
`POST /api/vision/metadata`, dan `POST /api/frame/surface`.

## Verifikasi tanpa hardware

```bash
python3 -m pytest -q tests/test_manual_rc.py tests/test_vision_route.py tests/test_vision_publisher.py tests/test_telemetry.py tests/test_dashboard_backend.py
python3 -m compileall -q vision_test.py vision_route.py asv_dashboard_backend tests
python3 vision_test.py --help
```

Expected: flag `--manual-rc` terlihat; semua test pass; compileall tidak
mengeluarkan error; tidak diperlukan Pixhawk atau model untuk command di atas.

## Laporan agent Raspi

Laporkan:

1. commit sebelum dan sesudah pull;
2. `git status --short`;
3. hasil test dan compileall;
4. response `/healthz`, `/api/status`, `/api/telemetry`;
5. status `asv-stack.target`;
6. apakah model publish metadata/frame;
7. masalah hardware tanpa mencetak secret.
```

- [ ] **Step 2: Review handover for safety and branch accuracy**

Check that it names `feat/manual-rc-dashboard-frontend`, does not instruct a Pixhawk command in manual mode, and keeps read-only telemetry separate from model monitoring.

### Task 4: Verify the complete Raspberry Pi path

**Files:**
- No additional source files.

- [ ] **Step 1: Run backend and vision tests**

```powershell
python -m pytest -q tests/test_manual_rc.py tests/test_vision_route.py tests/test_vision_capture.py tests/test_vision_publisher.py tests/test_telemetry.py tests/test_dashboard_backend.py
```

Expected: all selected tests pass without Pixhawk, camera, bridge, or model hardware.

- [ ] **Step 2: Run syntax validation and CLI smoke check**

```powershell
python -m compileall -q vision_test.py vision_route.py asv_dashboard_backend tests
python vision_test.py --help
```

Expected: compileall exits 0 and help lists `--manual-rc` without importing or connecting to Pixhawk.

- [ ] **Step 3: Re-run frontend regression checks**

```powershell
cd dashboard
npm run test -- --run
npm run typecheck
npm run build
cd ..
```

Expected: the previous frontend suite, typecheck, and production build remain green.

- [ ] **Step 4: Commit only the intended complete branch payload**

Review staged paths. Include the preserved related vision/throttle changes, the manual-RC implementation, tests, design/plan, and `handover.md`; do not include unrelated files:

```powershell
git add vision_test.py vision_route.py tests/test_vision_route.py tests/test_manual_rc.py start-all-local.bat start-vision-test.bat handover.md docs/superpowers/specs/2026-07-24-raspi-manual-rc-backend-design.md docs/superpowers/plans/2026-07-24-raspi-manual-rc-backend.md
git diff --cached --name-status
git commit -m "feat(raspi): add manual RC model monitoring"
```

- [ ] **Step 5: Push the existing feature branch**

```powershell
git push -u origin feat/manual-rc-dashboard-frontend
```

Expected: remote branch is created/updated; do not push to `main` and do not force-push.
