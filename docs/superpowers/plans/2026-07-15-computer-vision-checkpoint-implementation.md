# Computer Vision Checkpoint Blind Corner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tambahkan checkpoint pola 3×3, blind-turn berbasis heading, survey reacquisition, dan failsafe ke pipeline vision ASV tanpa mengubah model YOLO atau menambah hardware.

**Architecture:** Logika rute dibuat sebagai modul Python murni yang tidak bergantung pada kamera atau MAVLink sehingga dapat diuji dengan data deteksi sintetis. `vision_test.py` tetap menjadi entry point webcam/MAVLink dan hanya menghubungkan deteksi, heading Pixhawk, `RouteController`, RC override, overlay, dan JSONL telemetry. Checkpoint pola 3×3 direpresentasikan sebagai signature geometri urutan gate dari lintasan yang dikonfigurasi; bukan asumsi sembilan bola atau tiga pasangan.

**Tech Stack:** Python 3.14, stdlib (`dataclasses`, `enum`, `math`, `time`), `pytest`, OpenCV, Ultralytics YOLO, pymavlink, ArduRover MANUAL + `RC_CHANNELS_OVERRIDE`.

---

## File map

- **Create:** `D:/KKI2/vision_route.py` — shared detection/PWM helpers plus pure route state, gate tracker, pattern matcher, survey controller, and route decisions.
- **Modify:** `D:/KKI2/vision_test.py` — import shared helpers, read `VFR_HUD.heading`, parse route parameters, call `RouteController`, send decisions, display state, and write transition telemetry.
- **Create:** `D:/KKI2/tests/test_vision_route.py` — deterministic unit tests for shared helpers, state machine, gate tracking, checkpoint, and survey.
- **Reference:** `D:/KKI2/docs/superpowers/specs/2026-07-15-computer-vision-checkpoint-blind-corner.md` — behavior and safety contract.

Tidak ada dependency baru dan tidak ada perubahan pada model `D:/KKI2/model/best.pt`.

---

### Task 1: Tambahkan domain state machine dan heading math

**Files:**
- Create: `D:/KKI2/vision_route.py`
- Create: `D:/KKI2/tests/test_vision_route.py`

- [ ] **Step 1: Tulis test heading dan state awal**

```python
from vision_route import RouteConfig, RouteController, RouteState, signed_heading_error


def test_signed_heading_error_wraps_at_north():
    assert signed_heading_error(1.0, 359.0) == 2.0
    assert signed_heading_error(359.0, 1.0) == -2.0


def test_controller_starts_in_visual_track():
    controller = RouteController(RouteConfig())
    decision = controller.step([], frame_width=640, heading_deg=0.0, now=0.0)
    assert decision.state is RouteState.VISUAL_TRACK
    assert decision.steering_pwm == 1500
    assert decision.throttle_pwm == 1500
```

- [ ] **Step 2: Jalankan test untuk memastikan baseline gagal**

Run: `python -m pytest -q tests/test_vision_route.py`

Expected: FAIL karena `vision_route.py` dan tipe domain belum ada.

- [ ] **Step 3: Implementasikan tipe domain minimum**

Tambahkan ke `vision_route.py`:

```python
from dataclasses import dataclass
from enum import Enum
import math
from typing import Sequence


# Move the existing Detection dataclass, constants, clamp(),
# select_target_x(), and compute_steering_pwm() here unchanged. vision_test.py
# imports them from this module after the move; vision_route.py never imports
# vision_test.py, so the route module remains importable in unit tests.


class RouteState(str, Enum):
    VISUAL_TRACK = "VISUAL_TRACK"
    BLIND_TURN = "BLIND_TURN"
    SURVEY_SEARCH = "SURVEY_SEARCH"
    FAILSAFE = "FAILSAFE"


def normalize_heading(value: float) -> float:
    return value % 360.0


def signed_heading_error(target_deg: float, current_deg: float) -> float:
    return normalize_heading(target_deg - current_deg + 180.0) - 180.0


@dataclass(frozen=True)
class RouteConfig:
    turn_angle_deg: float = 90.0
    turn_direction: int = 1
    heading_tolerance_deg: float = 8.0
    blind_turn_throttle_pwm: int = 1500
    survey_throttle_pwm: int = 1500
    survey_sweep_deg: float = 35.0
    survey_sweep_rate_deg_s: float = 12.0
    blind_turn_timeout_s: float = 20.0
    survey_timeout_s: float = 20.0
    reacquire_frames: int = 3
    reacquire_confidence: float = 0.35


@dataclass(frozen=True)
class RouteDecision:
    state: RouteState
    steering_pwm: int = NEUTRAL_PWM
    throttle_pwm: int = NEUTRAL_PWM
    target_x: float | None = None
    target_heading_deg: float | None = None
    event: str | None = None
    gate_count: int = 0
    checkpoint_confirmed: bool = False


class RouteController:
    def __init__(self, config: RouteConfig) -> None:
        self.config = config
        self.state = RouteState.VISUAL_TRACK

    def step(
        self,
        detections: Sequence[Detection],
        *,
        frame_width: int,
        heading_deg: float | None,
        now: float,
        checkpoint_name: str | None = None,
    ) -> RouteDecision:
        return RouteDecision(state=self.state)
```

The initial implementation must validate positive frame width, heading tolerance, timeouts, sweep values, and `turn_direction in {-1, 1}`. It must not send arm commands.

- [ ] **Step 4: Jalankan test untuk memastikan domain minimum lulus**

Run: `python -m pytest -q tests/test_vision_route.py`

Expected: PASS untuk heading math/state awal; controller behavior selain state awal tetap covered by later tasks.

---

### Task 2: Implementasikan gate tracker dan signature checkpoint 3×3

**Files:**
- Modify: `D:/KKI2/vision_route.py`
- Modify: `D:/KKI2/tests/test_vision_route.py`

- [ ] **Step 1: Tulis test pair stability, gate crossing, debounce, dan pattern event**

```python
from vision_route import (
    Detection,
    GateTracker,
    GateFeature,
    PatternMatcher,
    PatternSignature,
)


def det(label, x, y, confidence=0.9):
    return Detection(label, confidence, x, y, 20.0, 20.0)


def feature(name, x, y):
    return GateFeature(name=name, center_x_norm=x, center_y_norm=y)


def test_gate_requires_red_and_green():
    tracker = GateTracker(crossing_y=0.70, cooldown_s=1.0)
    assert tracker.update([det("red_buoy", 300, 300)], frame_width=640, frame_height=640, now=0.0) is None


def test_gate_event_is_emitted_once_after_crossing():
    tracker = GateTracker(crossing_y=0.70, cooldown_s=1.0)
    pair = [det("red_buoy", 280, 200), det("green_buoy", 360, 200)]
    crossed = [det("red_buoy", 280, 500), det("green_buoy", 360, 500)]
    assert tracker.update(pair, frame_width=640, frame_height=640, now=0.0) is None
    event = tracker.update(crossed, frame_width=640, frame_height=640, now=0.2)
    assert event is not None
    assert tracker.update(crossed, frame_width=640, frame_height=640, now=0.3) is None


def test_first_3x3_signature_matches_ordered_route_features():
    signature = PatternSignature(
        name="first_3x3",
        required_features=(
            feature("entry", 0.25, 0.30),
            feature("middle", 0.50, 0.50),
            feature("exit", 0.75, 0.70),
        ),
        tolerance=0.20,
    )
    matcher = PatternMatcher(signature)
    assert matcher.observe(feature("entry", 0.24, 0.31)) is None
    assert matcher.observe(feature("middle", 0.49, 0.51)) is None
    assert matcher.observe(feature("exit", 0.76, 0.69)) == "first_3x3"
```

- [ ] **Step 2: Jalankan test untuk mengunci kegagalan awal**

Run: `python -m pytest -q tests/test_vision_route.py -k 'gate or 3x3'`

Expected: FAIL karena `GateTracker` dan `PatternSignature` belum ada.

- [ ] **Step 3: Implementasikan observasi gate dan matcher**

Tambahkan tipe dan perilaku berikut:

```python
@dataclass(frozen=True)
class GateFeature:
    name: str
    center_x_norm: float
    center_y_norm: float


@dataclass(frozen=True)
class GateEvent:
    center_x_norm: float
    center_y_norm: float
    red_confidence: float
    green_confidence: float
    route_feature: GateFeature
    checkpoint_name: str | None = None


@dataclass(frozen=True)
class PatternSignature:
    name: str
    required_features: tuple[GateFeature, ...]
    tolerance: float = 0.20


class PatternMatcher:
    def __init__(self, signature: PatternSignature) -> None:
        self.signature = signature
        self._features: list[GateFeature] = []

    def classify(self, center_x_norm: float, center_y_norm: float) -> GateFeature:
        candidates = [
            feature
            for feature in self.signature.required_features
            if max(
                abs(feature.center_x_norm - center_x_norm),
                abs(feature.center_y_norm - center_y_norm),
            ) <= self.signature.tolerance
        ]
        if not candidates:
            return GateFeature("unclassified", center_x_norm, center_y_norm)
        return min(
            candidates,
            key=lambda feature: (
                (feature.center_x_norm - center_x_norm) ** 2
                + (feature.center_y_norm - center_y_norm) ** 2
            ),
        )

    def observe(self, feature: GateFeature) -> str | None:
        self._features.append(feature)
        expected = self.signature.required_features
        window = self._features[-len(expected):]
        if len(window) != len(expected):
            return None
        matches = all(
            actual.name == wanted.name
            and abs(actual.center_x_norm - wanted.center_x_norm) <= self.signature.tolerance
            and abs(actual.center_y_norm - wanted.center_y_norm) <= self.signature.tolerance
            for actual, wanted in zip(window, expected)
        )
        if not matches:
            return None
        self._features.clear()
        return self.signature.name


class GateTracker:
    def __init__(
        self,
        *,
        crossing_y: float = 0.70,
        cooldown_s: float = 1.0,
        pattern_matcher: PatternMatcher | None = None,
    ) -> None:
        self.crossing_y = crossing_y
        self.cooldown_s = cooldown_s
        self.pattern_matcher = pattern_matcher
        self.gate_count = 0
        self._approaching = False
        self._last_event_at = -math.inf

    def update(
        self,
        detections: Sequence[Detection],
        *,
        frame_width: int,
        frame_height: int,
        now: float,
    ) -> GateEvent | None:
        if frame_width <= 0 or frame_height <= 0:
            raise ValueError("frame dimensions must be positive")
        red = max(
            (d for d in detections if d.label == "red_buoy"),
            key=lambda d: (d.confidence, d.area),
            default=None,
        )
        green = max(
            (d for d in detections if d.label == "green_buoy"),
            key=lambda d: (d.confidence, d.area),
            default=None,
        )
        if red is None or green is None:
            return None
        center_x_norm = ((red.x_center + green.x_center) / 2.0) / frame_width
        center_y_norm = ((red.y_center + green.y_center) / 2.0) / frame_height
        if center_y_norm < self.crossing_y:
            self._approaching = True
            return None
        if not self._approaching or now - self._last_event_at < self.cooldown_s:
            return None
        self._approaching = False
        self._last_event_at = now
        self.gate_count += 1
        feature = (
            self.pattern_matcher.classify(center_x_norm, center_y_norm)
            if self.pattern_matcher is not None
            else GateFeature("unclassified", center_x_norm, center_y_norm)
        )
        checkpoint_name = (
            self.pattern_matcher.observe(feature)
            if self.pattern_matcher is not None
            else None
        )
        return GateEvent(
            center_x_norm=center_x_norm,
            center_y_norm=center_y_norm,
            red_confidence=red.confidence,
            green_confidence=green.confidence,
            route_feature=feature,
            checkpoint_name=checkpoint_name,
        )
```

The `PatternSignature` fixture is built from the supplied diagram/recorded frames as a normalized route-geometry sequence. Its name is `first_3x3`, but it is not converted into a raw object count. `GateTracker` must reject one-color frames, normalize coordinates, debounce events, and feed one `GateFeature` per passed gate to `PatternMatcher`. The fixture values must be recorded explicitly before integration tests are run.


- [ ] **Step 4: Uji gate tracker dan pattern**

Run: `python -m pytest -q tests/test_vision_route.py -k 'gate or 3x3'`

Expected: PASS, including one-event debounce, one-color rejection, and ordered `first_3x3` confirmation.


---

### Task 3: Tambahkan heading telemetry Pixhawk

**Files:**
- Modify: `D:/KKI2/vision_test.py`
- Modify: `D:/KKI2/tests/test_vision_route.py`

- [ ] **Step 1: Tulis test parsing heading**

```python
from types import SimpleNamespace
from vision_test import vfr_hud_heading


def test_vfr_hud_heading_returns_normalized_heading():
    assert vfr_hud_heading(SimpleNamespace(heading=271)) == 271.0
    assert vfr_hud_heading(SimpleNamespace(heading=-1)) == 359.0


def test_vfr_hud_heading_returns_none_without_field():
    assert vfr_hud_heading(SimpleNamespace()) is None
```

- [ ] **Step 2: Jalankan test parsing sebelum implementasi**

Run: `python -m pytest -q tests/test_vision_route.py -k heading`

Expected: FAIL karena helper belum tersedia.

- [ ] **Step 3: Simpan dan expose `VFR_HUD.heading`**

Di `vision_test.py`:

```python
def vfr_hud_heading(message: Any) -> float | None:
    value = getattr(message, "heading", None)
    if value is None:
        return None
    return float(value) % 360.0
```

`PixhawkLink` harus:

- menyimpan `_last_vfr_hud`;
- meminta message type `VFR_HUD` di `telemetry()` bersama `HEARTBEAT`, `RC_CHANNELS`, dan `SERVO_OUTPUT_RAW`;
- mengembalikan `heading_deg` dari cache terakhir;
- mengembalikan `None` bila heading belum pernah diterima;
- tidak mengubah perilaku arm/disarm.

- [ ] **Step 4: Jalankan test dan compile check**

Run: `python -m pytest -q tests/test_vision_route.py -k heading && python -m py_compile vision_test.py vision_route.py`

Expected: PASS dan exit code 0.

---

### Task 4: Integrasikan blind-turn, survey search, CLI, dan telemetry

**Files:**
- Modify: `D:/KKI2/vision_route.py`
- Modify: `D:/KKI2/vision_test.py`
- Modify: `D:/KKI2/tests/test_vision_route.py`

- [ ] **Step 1: Tulis test transisi route**

Tambahkan test behavior berikut:

```python
def make_controller(**config_overrides):
    config = RouteConfig(**config_overrides)
    return RouteController(config)


def enter_survey(**config_overrides):
    controller = make_controller(**config_overrides)
    controller.step(
        [],
        frame_width=640,
        heading_deg=0.0,
        now=0.0,
        checkpoint_name="first_3x3",
    )
    controller.step([], frame_width=640, heading_deg=90.0, now=1.0)
    assert controller.state is RouteState.SURVEY_SEARCH
    return controller


def test_checkpoint_enters_blind_turn_once():
    controller = make_controller()
    decision = controller.step(
        [],
        frame_width=640,
        heading_deg=0.0,
        now=0.0,
        checkpoint_name="first_3x3",
    )
    assert decision.state is RouteState.BLIND_TURN
    assert decision.event == "checkpoint_first_3x3"


def test_blind_turn_enters_survey_at_target_heading():
    controller = make_controller()
    controller.step(
        [],
        frame_width=640,
        heading_deg=0.0,
        now=0.0,
        checkpoint_name="first_3x3",
    )
    decision = controller.step([], frame_width=640, heading_deg=85.0, now=2.0)
    assert decision.state is RouteState.SURVEY_SEARCH
    assert decision.throttle_pwm == controller.config.survey_throttle_pwm


def test_survey_requires_both_colors_for_reacquisition():
    controller = enter_survey(reacquire_frames=2)
    one_color = [det("red_buoy", 320, 300)]
    decision = controller.step(one_color, frame_width=640, heading_deg=90.0, now=1.1)
    assert decision.state is RouteState.SURVEY_SEARCH


def test_survey_resumes_visual_track_after_stable_pair():
    controller = enter_survey(reacquire_frames=2)
    pair = [det("red_buoy", 280, 300), det("green_buoy", 360, 300)]
    controller.step(pair, frame_width=640, heading_deg=90.0, now=1.1)
    decision = controller.step(pair, frame_width=640, heading_deg=90.0, now=1.2)
    assert decision.state is RouteState.VISUAL_TRACK


def test_survey_timeout_fails_safe():
    controller = enter_survey(survey_timeout_s=2.0)
    decision = controller.step([], frame_width=640, heading_deg=90.0, now=3.1)
    assert decision.state is RouteState.FAILSAFE
    assert decision.throttle_pwm == 1500
    assert decision.steering_pwm == 1500
```

- [ ] **Step 2: Jalankan test untuk mengunci perilaku yang belum ada**

Run: `python -m pytest -q tests/test_vision_route.py -k 'checkpoint or blind_turn or survey'`

Expected: FAIL karena transition behavior belum diimplementasikan.

- [ ] **Step 3: Implementasikan route decisions**

`RouteController.step()` harus:

1. `VISUAL_TRACK`: gunakan `select_target_x()` dan `compute_steering_pwm()`; throttle memakai konfigurasi jika target valid, netral jika tidak.
2. Saat `GateTracker` mengonfirmasi `first_3x3`, simpan `target_heading_deg = current_heading + turn_direction * turn_angle_deg`, masuk `BLIND_TURN`, dan emit event satu kali.
3. `BLIND_TURN`: jika heading `None`, emit `heading_unavailable` dan masuk `FAILSAFE`; jika error heading lebih besar dari tolerance, ubah error menjadi steering PWM terbatas dan kirim blind-turn throttle; jika tolerance tercapai, masuk `SURVEY_SEARCH`.
4. `SURVEY_SEARCH`: lakukan sapuan heading terbatas terhadap heading awal survey, gunakan `survey_throttle_pwm`, dan hanya hitung reacquisition bila red+green stabil sebanyak `reacquire_frames`.
5. `SURVEY_SEARCH` timeout: masuk `FAILSAFE` dengan steering dan throttle netral.
6. `FAILSAFE`: selalu mengembalikan PWM netral dan tidak melakukan transisi otomatis.

- [ ] **Step 4: Tambahkan CLI parameter dan loop integration**

Tambahkan ke `parse_args()` dengan default aman:

```text
--turn-angle-deg 90
--turn-direction {left,right}
--blind-turn-throttle-pwm 1500
--survey-throttle-pwm 1500
--survey-sweep-deg 35
--survey-sweep-rate 12
--blind-turn-timeout 20
--survey-timeout 20
--reacquire-frames 3
--reacquire-confidence 0.35
```

Di loop utama:

- import `Detection`, `GateTracker`, `RouteController`, `RouteDecision`, dan shared helpers dari `vision_route.py`; hapus definisi duplikat dari `vision_test.py`;
- buat `GateTracker` dengan `PatternMatcher` dan signature `first_3x3` yang berasal dari fixture geometri lintasan;
- ambil `telemetry = link.telemetry()` sebelum keputusan route;
- panggil `gate_event = gate_tracker.update(detections, frame_width=frame.shape[1], frame_height=frame.shape[0], now=now)`;
- pass `telemetry["heading_deg"]` dan `gate_event.checkpoint_name` jika event tersedia ke `RouteController.step()`;
- saat mode `MANUAL`, kirim decision steering/throttle;
- saat mode bukan `MANUAL`, release override dan paksa keputusan netral;
- tambahkan `route_state`, `route_event`, `heading_deg`, `target_heading_deg`, `gate_count`, dan `checkpoint_confirmed` ke JSONL;
- tampilkan state dan heading pada overlay;
- `finally` tetap mengirim netral lalu release override seperti perilaku sekarang.

Pisahkan pembuatan record agar bisa diuji tanpa hardware:

```python
def build_route_record(
    *,
    detections: Sequence[Detection],
    frame_width: int,
    decision: RouteDecision,
    telemetry: dict[str, Any],
) -> dict[str, Any]:
    return {
        "vision": {
            "detections": [asdict(detection) for detection in detections],
            "frame_width": frame_width,
        },
        "route": {
            "state": decision.state.value,
            "event": decision.event,
            "target_heading_deg": decision.target_heading_deg,
            "gate_count": decision.gate_count,
            "checkpoint_confirmed": decision.checkpoint_confirmed,
        },
        "command": {
            "steering_pwm": decision.steering_pwm,
            "throttle_pwm": decision.throttle_pwm,
        },
        "ardupilot": telemetry,
    }
```

- [ ] **Step 5: Jalankan seluruh unit test dan CLI smoke test**

Run: `python -m pytest -q tests/test_vision_route.py`  
Expected: PASS seluruh test route, gate, pattern, heading, survey, dan failsafe.

Run: `python -m py_compile vision_test.py vision_route.py`  
Expected: exit code 0.

Run: `python vision_test.py --help`  
Expected: semua parameter blind-turn/survey tercetak dan proses berhenti tanpa membuka kamera/MAVLink.

---

### Task 5: Verifikasi keselamatan dan dokumentasi hasil

**Files:**
- Modify: `D:/KKI2/docs/superpowers/specs/2026-07-15-computer-vision-checkpoint-blind-corner.md`
- Create: `D:/KKI2/tests/test_vision_log.py`

- [ ] **Step 1: Tulis test JSONL route telemetry**

```python
from vision_route import RouteDecision, RouteState
from vision_test import build_route_record


def test_route_record_contains_transition_fields():
    record = build_route_record(
        detections=[],
        frame_width=640,
        decision=RouteDecision(
            state=RouteState.SURVEY_SEARCH,
            event="target_heading_reached",
            target_heading_deg=270.0,
            gate_count=3,
            checkpoint_confirmed=True,
        ),
        telemetry={"heading_deg": 271.4, "mode": "MANUAL"},
    )
    assert record["route"]["state"] == "SURVEY_SEARCH"
    assert record["route"]["checkpoint_confirmed"] is True
    assert record["ardupilot"]["heading_deg"] == 271.4
```

- [ ] **Step 2: Jalankan test log**

Run: `python -m pytest -q tests/test_vision_log.py`

Expected: PASS dan test gagal jika route transition fields atau heading telemetry dihilangkan.

- [ ] **Step 3: Jalankan bench test tanpa propeller/thruster**

1. Disarm Pixhawk melalui Mission Planner.
2. Pastikan `SERVO1_FUNCTION=26`, `SERVO3_FUNCTION=70`, `SERVO3_MIN=1100`, `SERVO3_TRIM=1500`, `SERVO3_MAX=1900`.
3. Jalankan `python vision_test.py --duration 10 --blind-turn-throttle-pwm 1500 --survey-throttle-pwm 1500 --log route_bench.jsonl`.
4. Feed frame/fixture checkpoint 3×3 dan pastikan log menunjukkan `VISUAL_TRACK → BLIND_TURN → SURVEY_SEARCH` tanpa output propulsi.
5. Pastikan akhir proses mengirim steering/throttle 1500 dan me-release override.

Expected: tidak ada arm command, tidak ada propeller/thruster bergerak, dan setiap baris log valid JSON.

- [ ] **Step 4: Verifikasi output servo sebelum uji air**

Jalankan pemeriksaan telemetry yang sudah digunakan sebelumnya dan pastikan saat override throttle non-netral:

```text
RC3 != 1500
SERVO3 != 1500
```

Jika `RC3` berubah tetapi `SERVO3` tetap 1500, hentikan uji air dan selesaikan safety/output ArduPilot terlebih dahulu.

- [ ] **Step 5: Uji air terbatas dan update status spec**

Uji di area aman dengan throttle minimum yang sudah diverifikasi:

1. visual tracking normal;
2. checkpoint pola 3×3;
3. blind-turn satu kali;
4. survey sampai buoy berikutnya ditemukan;
5. timeout survey dengan throttle netral;
6. stop/Q/ESC dan release override.

Setelah hasil nyata tersedia, update bagian `Kondisi implementasi saat ini` dan `Verifikasi keselamatan` pada spec. Jangan menandai metode berhasil sebelum log menunjukkan transisi dan output servo fisik yang sesuai.

---

## Self-review plan

- **Spec coverage:** state machine, checkpoint pola 3×3, heading-based blind-turn, survey reacquisition, both-color requirement, timeout/failsafe, JSONL logging, dan verifikasi servo semuanya memiliki task.
- **No new dependency:** seluruh logika baru dapat diuji dengan stdlib dan data `Detection` sintetis.
- **Safety:** default throttle blind-turn/survey tetap 1500 untuk bench; nilai non-netral hanya diaktifkan setelah output servo diverifikasi.
- **No hidden pattern assumption:** signature pola disimpan sebagai route geometry contract, bukan dikonversi diam-diam menjadi 9 bola atau 3 pasangan.
- **No placeholders:** setiap task memiliki file, test, command, expected result, dan urutan integrasi yang eksplisit.
