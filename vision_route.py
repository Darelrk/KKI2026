"""Pure computer-vision route control primitives for the ASV blind corner."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Sequence


NEUTRAL_PWM = 1500
PWM_MIN = 1000
PWM_MAX = 2000
STEERING_MAX_DELTA = 400
TARGET_LABELS = {"red_buoy", "green_buoy"}


@dataclass(frozen=True)
class Detection:
    """One model detection in pixel coordinates."""

    label: str
    confidence: float
    x_center: float
    y_center: float
    width: float
    height: float

    @property
    def area(self) -> float:
        return self.width * self.height


def clamp(value: float, lower: float, upper: float) -> float:
    """Clamp a number to an inclusive range."""
    if lower > upper:
        raise ValueError("lower bound must not exceed upper bound")
    return max(lower, min(upper, value))


def select_target_x(
    detections: Sequence[Detection],
    *,
    single_buoy_offset: float = 0.0,
) -> float | None:
    """Return the midpoint of the best red/green target, or offset for a single buoy."""
    relevant = [d for d in detections if d.label in TARGET_LABELS]
    if not relevant:
        return None

    best_by_label: dict[str, Detection] = {}
    for detection in relevant:
        previous = best_by_label.get(detection.label)
        if previous is None or (
            detection.confidence,
            detection.area,
        ) > (previous.confidence, previous.area):
            best_by_label[detection.label] = detection

    red = best_by_label.get("red_buoy")
    green = best_by_label.get("green_buoy")
    if red is not None and green is not None:
        return (red.x_center + green.x_center) / 2.0

    if red is not None:
        offset = single_buoy_offset if single_buoy_offset > 0.0 else (red.width * 1.5)
        return max(0.0, red.x_center + offset)

    if green is not None:
        offset = single_buoy_offset if single_buoy_offset > 0.0 else (green.width * 1.5)
        return max(0.0, green.x_center - offset)
    best = max(relevant, key=lambda d: (d.confidence, d.area))
    return best.x_center


class VisualTargetTracker:
    """Stabilize buoy targets across brief one-buoy detection gaps."""

    def __init__(self, *, hold_s: float = 0.8, smoothing_alpha: float = 0.5) -> None:
        if hold_s < 0.0:
            raise ValueError("hold_s must be non-negative")
        if not 0.0 < smoothing_alpha <= 1.0:
            raise ValueError("smoothing_alpha must be between 0 and 1")
        self.hold_s = hold_s
        self.smoothing_alpha = smoothing_alpha
        self._last_pair_target_x: float | None = None
        self._last_pair_at: float | None = None
        self._last_target_x: float | None = None
        self._last_target_at: float | None = None

    def reset(self) -> None:
        """Forget stale visual targets."""
        self._last_pair_target_x = None
        self._last_pair_at = None
        self._last_target_x = None
        self._last_target_at = None

    def update(
        self,
        detections: Sequence[Detection],
        *,
        now: float,
    ) -> float | None:
        """Return a smoothed target while tolerating brief detection gaps."""
        has_red = any(detection.label == "red_buoy" for detection in detections)
        has_green = any(detection.label == "green_buoy" for detection in detections)
        has_target = has_red or has_green
        target_x = select_target_x(detections)

        if has_red and has_green:
            self._last_pair_target_x = target_x
            self._last_pair_at = now
        elif (
            has_target
            and self._last_pair_target_x is not None
            and self._last_pair_at is not None
            and now - self._last_pair_at <= self.hold_s
        ):
            target_x = self._last_pair_target_x
        elif not has_target:
            if (
                self._last_target_x is None
                or self._last_target_at is None
                or now - self._last_target_at > self.hold_s
            ):
                return None
            target_x = self._last_target_x

        if target_x is None:
            return None
        if self._last_target_x is None:
            smoothed_target_x = target_x
        else:
            smoothed_target_x = self._last_target_x + self.smoothing_alpha * (
                target_x - self._last_target_x
            )
        self._last_target_x = smoothed_target_x
        if has_target:
            self._last_target_at = now
        return smoothed_target_x

def compute_steering_pwm(
    target_x: float,
    frame_width: int,
    *,
    center_pwm: int = NEUTRAL_PWM,
    max_delta: int = STEERING_MAX_DELTA,
    gain: float = 1.0,
    invert: bool = False,
) -> int:
    """Map target position to a bounded steering PWM value."""
    if frame_width <= 0:
        raise ValueError("frame_width must be positive")
    if not PWM_MIN <= center_pwm <= PWM_MAX:
        raise ValueError("center_pwm must be between 1000 and 2000")
    if max_delta < 0:
        raise ValueError("max_delta must be non-negative")
    if gain < 0:
        raise ValueError("gain must be non-negative")

    image_center = frame_width / 2.0
    normalized_error = (target_x - image_center) / image_center
    correction = clamp(normalized_error * gain, -1.0, 1.0)
    if invert:
        correction = -correction

    pwm = center_pwm + correction * max_delta
    return int(round(clamp(pwm, PWM_MIN, PWM_MAX)))


@dataclass(frozen=True)
class ThrottleConfig:
    near_pwm: int = 1540
    cruise_pwm: int = 1560
    far_pwm: int = 1600
    far_area_ratio: float = 0.03
    near_area_ratio: float = 0.15
    steering_boost_threshold_pwm: int = 200
    steering_boost_pwm: int = 25
    hold_s: float = 0.8
    ramp_pwm_per_s: float = 200.0

    def __post_init__(self) -> None:
        if not (
            NEUTRAL_PWM < self.near_pwm
            <= self.cruise_pwm
            <= self.far_pwm
            <= 1700
        ):
            raise ValueError(
                "near_pwm, cruise_pwm, and far_pwm must be ordered above neutral and <= 1700"
            )
        if not 0.0 <= self.far_area_ratio < self.near_area_ratio <= 1.0:
            raise ValueError(
                "far_area_ratio must be >= 0 and less than near_area_ratio <= 1"
            )
        if self.steering_boost_threshold_pwm < 0:
            raise ValueError("steering_boost_threshold_pwm must be non-negative")
        if self.steering_boost_pwm < 0:
            raise ValueError("steering_boost_pwm must be non-negative")
        if self.hold_s < 0.0:
            raise ValueError("hold_s must be non-negative")
        if self.ramp_pwm_per_s <= 0.0:
            raise ValueError("ramp_pwm_per_s must be positive")


def compute_visual_throttle_pwm(
    detections: Sequence[Detection],
    frame_width: int,
    frame_height: int,
    steering_pwm: int,
    *,
    config: ThrottleConfig = ThrottleConfig(),
) -> int:
    """Map buoy size and steering demand to a bounded throttle PWM."""
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("frame dimensions must be positive")
    if not PWM_MIN <= steering_pwm <= PWM_MAX:
        raise ValueError("steering_pwm must be between 1000 and 2000")

    relevant = [detection for detection in detections if detection.label in TARGET_LABELS]
    if not relevant:
        return NEUTRAL_PWM

    area_ratio = max(detection.area for detection in relevant) / (
        frame_width * frame_height
    )
    if area_ratio <= config.far_area_ratio:
        pwm = config.far_pwm
    elif area_ratio >= config.near_area_ratio:
        pwm = config.near_pwm
    else:
        pwm = config.cruise_pwm

    if abs(steering_pwm - NEUTRAL_PWM) > config.steering_boost_threshold_pwm:
        pwm += config.steering_boost_pwm
    return int(round(clamp(pwm, PWM_MIN, PWM_MAX)))


class VisualThrottleController:
    """Apply visual throttle targets with hold and rate-limited transitions."""

    def __init__(self, config: ThrottleConfig = ThrottleConfig()) -> None:
        self.config = config
        self._current_pwm = NEUTRAL_PWM
        self._last_target_pwm: int | None = None
        self._last_target_at: float | None = None
        self._last_update_at: float | None = None

    def reset(self, now: float | None = None) -> int:
        """Clear target state and return neutral throttle."""
        self._current_pwm = NEUTRAL_PWM
        self._last_target_pwm = None
        self._last_target_at = None
        self._last_update_at = now
        return NEUTRAL_PWM

    def update(
        self,
        detections: Sequence[Detection],
        *,
        frame_width: int,
        frame_height: int,
        steering_pwm: int,
        now: float,
    ) -> int:
        """Return the next smoothed throttle command."""
        desired_pwm = compute_visual_throttle_pwm(
            detections,
            frame_width,
            frame_height,
            steering_pwm,
            config=self.config,
        )
        has_target = any(
            detection.label in TARGET_LABELS for detection in detections
        )

        elapsed = (
            0.0
            if self._last_update_at is None
            else max(0.0, now - self._last_update_at)
        )
        self._last_update_at = now

        if has_target:
            self._last_target_at = now
            self._last_target_pwm = desired_pwm
            target_pwm = desired_pwm
        elif (
            self._last_target_at is not None
            and now - self._last_target_at <= self.config.hold_s
        ):
            target_pwm = (
                self._last_target_pwm
                if self._last_target_pwm is not None
                else self._current_pwm
            )
        else:
            target_pwm = NEUTRAL_PWM

        max_step = self.config.ramp_pwm_per_s * elapsed
        if self._current_pwm < target_pwm:
            self._current_pwm = min(target_pwm, self._current_pwm + max_step)
        elif self._current_pwm > target_pwm:
            self._current_pwm = max(target_pwm, self._current_pwm - max_step)
        self._current_pwm = clamp(self._current_pwm, PWM_MIN, PWM_MAX)
        return int(round(self._current_pwm))


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
    match_mode: str = "sequence"

    def __post_init__(self) -> None:
        if not self.required_features:
            raise ValueError("required_features must not be empty")
        if self.tolerance <= 0.0:
            raise ValueError("tolerance must be positive")
        if self.match_mode not in {"sequence", "geometry"}:
            raise ValueError("match_mode must be sequence or geometry")


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

    def feature_for_gate(
        self,
        gate_index: int,
        center_x_norm: float,
        center_y_norm: float,
    ) -> GateFeature:
        if self.signature.match_mode == "sequence" and gate_index < len(
            self.signature.required_features
        ):
            expected = self.signature.required_features[gate_index]
            return GateFeature(expected.name, center_x_norm, center_y_norm)
        return self.classify(center_x_norm, center_y_norm)

    def observe(self, feature: GateFeature) -> str | None:
        self._features.append(feature)
        expected = self.signature.required_features
        window = self._features[-len(expected):]
        if len(window) != len(expected):
            return None
        matches = all(
            actual.name == wanted.name
            and (
                self.signature.match_mode == "sequence"
                or (
                    abs(actual.center_x_norm - wanted.center_x_norm)
                    <= self.signature.tolerance
                    and abs(actual.center_y_norm - wanted.center_y_norm)
                    <= self.signature.tolerance
                )
            )
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
        if not 0.0 < crossing_y < 1.0:
            raise ValueError("crossing_y must be between 0 and 1")
        if cooldown_s < 0.0:
            raise ValueError("cooldown_s must be non-negative")
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
            self.pattern_matcher.feature_for_gate(
                self.gate_count - 1,
                center_x_norm,
                center_y_norm,
            )
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

class RouteState(str, Enum):
    VISUAL_TRACK = "VISUAL_TRACK"
    BLIND_TURN = "BLIND_TURN"
    SURVEY_SEARCH = "SURVEY_SEARCH"
    FAILSAFE = "FAILSAFE"


def normalize_heading(value: float) -> float:
    return value % 360.0


def signed_heading_error(target_deg: float, current_deg: float) -> float:
    return normalize_heading(target_deg - current_deg + 180.0) - 180.0


def compute_heading_steering_pwm(
    heading_error_deg: float,
    *,
    center_pwm: int = NEUTRAL_PWM,
    max_delta: int = STEERING_MAX_DELTA,
) -> int:
    correction = clamp(heading_error_deg / 90.0, -1.0, 1.0)
    return int(round(clamp(center_pwm + correction * max_delta, PWM_MIN, PWM_MAX)))



@dataclass(frozen=True)
class RouteConfig:
    turn_angle_deg: float = 90.0
    turn_direction: int = 1
    heading_tolerance_deg: float = 8.0
    visual_throttle_pwm: int = 1560
    blind_turn_throttle_pwm: int = 1500
    survey_throttle_pwm: int = 1500
    survey_sweep_deg: float = 35.0
    survey_sweep_rate_deg_s: float = 12.0
    blind_turn_timeout_s: float = 20.0
    survey_timeout_s: float = 20.0
    reacquire_frames: int = 3
    reacquire_confidence: float = 0.35

    def __post_init__(self) -> None:
        if self.turn_direction not in (-1, 1):
            raise ValueError("turn_direction must be -1 or 1")
        if self.turn_angle_deg <= 0.0 or self.turn_angle_deg > 180.0:
            raise ValueError("turn_angle_deg must be between 0 and 180")
        if self.heading_tolerance_deg <= 0.0 or self.heading_tolerance_deg >= 180.0:
            raise ValueError("heading_tolerance_deg must be between 0 and 180")
        if self.survey_sweep_deg <= 0.0 or self.survey_sweep_deg > 180.0:
            raise ValueError("survey_sweep_deg must be between 0 and 180")
        if self.survey_sweep_rate_deg_s <= 0.0:
            raise ValueError("survey_sweep_rate_deg_s must be positive")
        if self.blind_turn_timeout_s <= 0.0 or self.survey_timeout_s <= 0.0:
            raise ValueError("route timeouts must be positive")
        if self.reacquire_frames <= 0:
            raise ValueError("reacquire_frames must be positive")
        if not 0.0 < self.reacquire_confidence <= 1.0:
            raise ValueError("reacquire_confidence must be between 0 and 1")
        for name, value in (
            ("visual_throttle_pwm", self.visual_throttle_pwm),
            ("blind_turn_throttle_pwm", self.blind_turn_throttle_pwm),
            ("survey_throttle_pwm", self.survey_throttle_pwm),
        ):
            if not PWM_MIN <= value <= PWM_MAX:
                raise ValueError(f"{name} must be between 1000 and 2000")


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
        self._target_heading_deg: float | None = None
        self._blind_started_at: float | None = None
        self._survey_started_at: float | None = None
        self._survey_origin_heading: float | None = None
        self._reacquire_count = 0
        self._checkpoint_confirmed = False
        self._gate_count = 0

    def _decision(
        self,
        *,
        steering_pwm: int = NEUTRAL_PWM,
        throttle_pwm: int = NEUTRAL_PWM,
        target_x: float | None = None,
        event: str | None = None,
    ) -> RouteDecision:
        return RouteDecision(
            state=self.state,
            steering_pwm=steering_pwm,
            throttle_pwm=throttle_pwm,
            target_x=target_x,
            target_heading_deg=self._target_heading_deg,
            event=event,
            gate_count=self._gate_count,
            checkpoint_confirmed=self._checkpoint_confirmed,
        )

    def _enter_failsafe(self, event: str) -> RouteDecision:
        self.state = RouteState.FAILSAFE
        return self._decision(event=event)

    def step(
        self,
        detections: Sequence[Detection],
        *,
        frame_width: int,
        heading_deg: float | None,
        now: float,
        checkpoint_name: str | None = None,
        gate_count: int = 0,
    ) -> RouteDecision:
        if frame_width <= 0:
            raise ValueError("frame_width must be positive")
        self._gate_count = gate_count

        if self.state is RouteState.FAILSAFE:
            return self._decision()

        if self.state is RouteState.VISUAL_TRACK:
            if checkpoint_name == "first_3x3" and not self._checkpoint_confirmed:
                if heading_deg is None:
                    return self._enter_failsafe("heading_unavailable")
                self._checkpoint_confirmed = True
                self._target_heading_deg = normalize_heading(
                    heading_deg
                    + self.config.turn_direction * self.config.turn_angle_deg
                )
                self._blind_started_at = now
                self.state = RouteState.BLIND_TURN
                error = signed_heading_error(self._target_heading_deg, heading_deg)
                return self._decision(
                    steering_pwm=compute_heading_steering_pwm(error),
                    throttle_pwm=self.config.blind_turn_throttle_pwm,
                    event="checkpoint_first_3x3",
                )

            target_x = select_target_x(detections)
            steering_pwm = (
                compute_steering_pwm(target_x, frame_width)
                if target_x is not None
                else NEUTRAL_PWM
            )
            throttle_pwm = (
                self.config.visual_throttle_pwm
                if target_x is not None
                else NEUTRAL_PWM
            )
            return self._decision(
                steering_pwm=steering_pwm,
                throttle_pwm=throttle_pwm,
                target_x=target_x,
            )

        if heading_deg is None:
            return self._enter_failsafe("heading_unavailable")

        if self.state is RouteState.BLIND_TURN:
            if (
                self._blind_started_at is None
                or now - self._blind_started_at > self.config.blind_turn_timeout_s
            ):
                return self._enter_failsafe("blind_turn_timeout")
            assert self._target_heading_deg is not None
            error = signed_heading_error(self._target_heading_deg, heading_deg)
            if abs(error) <= self.config.heading_tolerance_deg:
                self.state = RouteState.SURVEY_SEARCH
                self._survey_started_at = now
                self._survey_origin_heading = heading_deg
                self._reacquire_count = 0
                return self._decision(
                    throttle_pwm=self.config.survey_throttle_pwm,
                    event="target_heading_reached",
                )
            return self._decision(
                steering_pwm=compute_heading_steering_pwm(error),
                throttle_pwm=self.config.blind_turn_throttle_pwm,
            )

        if self.state is RouteState.SURVEY_SEARCH:
            if (
                self._survey_started_at is None
                or now - self._survey_started_at > self.config.survey_timeout_s
            ):
                return self._enter_failsafe("survey_timeout")

            target_x = select_target_x(
                [d for d in detections if d.confidence >= self.config.reacquire_confidence]
            )
            if target_x is None:
                self._reacquire_count = 0
            else:
                self._reacquire_count += 1
                if self._reacquire_count >= self.config.reacquire_frames:
                    self.state = RouteState.VISUAL_TRACK
                    return self._decision(
                        steering_pwm=compute_steering_pwm(target_x, frame_width),
                        throttle_pwm=self.config.visual_throttle_pwm,
                        target_x=target_x,
                        event="buoy_reacquired",
                    )

            assert self._survey_origin_heading is not None
            elapsed = max(0.0, now - self._survey_started_at)
            sweep_phase = int(
                elapsed * self.config.survey_sweep_rate_deg_s
                / self.config.survey_sweep_deg
            )
            sweep_direction = 1 if sweep_phase % 2 == 0 else -1
            survey_target = normalize_heading(
                self._survey_origin_heading
                + sweep_direction * self.config.survey_sweep_deg
            )
            error = signed_heading_error(survey_target, heading_deg)
            return self._decision(
                steering_pwm=compute_heading_steering_pwm(error),
                throttle_pwm=self.config.survey_throttle_pwm,
            )

        raise RuntimeError(f"unknown route state: {self.state}")
