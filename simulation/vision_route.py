"""Pure computer-vision route control primitives for the ASV blind corner."""

from __future__ import annotations

import math
import time
import numpy as np
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence


NEUTRAL_PWM = 1500
PWM_MIN = 1000
PWM_MAX = 2000
STEERING_MAX_DELTA = 400
TARGET_LABELS = {"red_buoy", "green_buoy"}
# --- Geometry helpers (ported from Arcturus/all_seaing_vehicle) ---

def ccw(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
    """Return True if points a→b→c are in counter-clockwise order.
    Used for geometric gate-pass detection: if robot (c) is CCW of gate line (a→b),
    the robot has crossed through the gate.
    (From ArcturusNavigation/all_seaing_vehicle geometry_utils.py)
    """
    ax, ay = a
    bx, by = b
    cx, cy = c
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) > 0


def max_buoy_area_ratio(detections: Sequence["Detection"], frame_width: int, frame_height: int) -> float:
    """Return largest buoy area as fraction of frame. 0.0 if no detections.
    Used by dual-gain steering to reduce gain when buoy is close (large in frame).
    (Inspired by Crogued approach/positioning mode switch.)
    """
    if not detections or frame_width <= 0 or frame_height <= 0:
        return 0.0
    frame_area = frame_width * frame_height
    return max(d.area / frame_area for d in detections if d.label in TARGET_LABELS) if any(d.label in TARGET_LABELS for d in detections) else 0.0


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
    red_on_left: bool = True,
) -> float | None:
    """Return the gate midpoint, or steer toward the missing buoy's side."""
    relevant = [d for d in detections if d.label in TARGET_LABELS]
    if not relevant:
        return None

    # Pick closest buoys (largest y_center / area = closest in front of boat)
    reds = sorted(
        [d for d in relevant if d.label == "red_buoy"],
        key=lambda d: (d.y_center, d.area),
        reverse=True,
    )
    greens = sorted(
        [d for d in relevant if d.label == "green_buoy"],
        key=lambda d: (d.y_center, d.area),
        reverse=True,
    )

    red = reds[0] if reds else None
    green = greens[0] if greens else None

    if red is not None and green is not None:
        return (red.x_center + green.x_center) / 2.0

    if red is not None:
        offset = single_buoy_offset if single_buoy_offset > 0.0 else max(110.0, red.width * 2.5)
        return red.x_center + offset

    if green is not None:
        offset = single_buoy_offset if single_buoy_offset > 0.0 else max(110.0, green.width * 2.5)
        return max(0.0, green.x_center - offset)
    best = max(relevant, key=lambda d: (d.confidence, d.area))
    return best.x_center


@dataclass(frozen=True)
class VisualGatePair:
    """A geometrically plausible red-left/green-right gate observation."""

    target_x: float
    confidence: float
    area_ratio: float
    separation_ratio: float


def select_visual_gate_pair(
    detections: Sequence[Detection],
    frame_width: int,
    frame_height: int,
    *,
    min_confidence: float = 0.35,
    red_on_left: bool = True,
) -> VisualGatePair | None:
    """Select the most plausible same-gate buoy pair in one camera frame.

    Independent largest-red/largest-green selection can accidentally combine
    buoys from two successive gates.  This matcher rejects implausible colour
    order, separation, vertical alignment, and scale before ranking candidates.
    """

    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("frame dimensions must be positive")
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0 and 1")
    reds = [
        detection
        for detection in detections
        if detection.label == "red_buoy"
        and detection.confidence >= min_confidence
    ]
    greens = [
        detection
        for detection in detections
        if detection.label == "green_buoy"
        and detection.confidence >= min_confidence
    ]
    frame_area = float(frame_width * frame_height)
    image_center = frame_width / 2.0
    candidates: list[tuple[float, VisualGatePair]] = []
    for red in reds:
        for green in greens:
            colour_order_ok = red.x_center < green.x_center
            if not red_on_left:
                colour_order_ok = not colour_order_ok
            if not colour_order_ok:
                continue
            separation = abs(green.x_center - red.x_center)
            separation_ratio = separation / frame_width
            if not 0.03 <= separation_ratio <= 0.85:
                continue
            vertical_gap = abs(red.y_center - green.y_center)
            if vertical_gap > max(0.18 * frame_height, 2.5 * max(red.height, green.height)):
                continue
            larger_area = max(red.area, green.area, 1.0)
            size_similarity = min(red.area, green.area) / larger_area
            if size_similarity < 0.18:
                continue
            target_x = (red.x_center + green.x_center) / 2.0
            confidence = min(red.confidence, green.confidence)
            area_ratio = (red.area + green.area) / frame_area
            centre_score = 1.0 - min(1.0, abs(target_x - image_center) / image_center)
            depth_score = clamp(
                ((red.y_center + green.y_center) / 2.0) / frame_height,
                0.0,
                1.0,
            )
            score = (
                1.8 * depth_score
                + 1.0 * size_similarity
                + 0.8 * confidence
                + 0.2 * centre_score
            )
            candidates.append(
                (
                    score,
                    VisualGatePair(
                        target_x=target_x,
                        confidence=confidence,
                        area_ratio=area_ratio,
                        separation_ratio=separation_ratio,
                    ),
                )
            )
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


@dataclass(frozen=True)
class VisualGateCorrectionConfig:
    """Limits for camera-based local correction of the coarse route."""

    min_confidence: float = 0.35
    max_age_s: float = 0.55
    smoothing_alpha: float = 0.35
    deadband_ratio: float = 0.025
    max_delta_pwm: int = 160
    gain: float = 1.25
    red_on_left: bool = True
    # A camera can see two successive gates at once.  Do not let a newly
    # selected pair jump across most of the image in one frame; keep the last
    # stable correction briefly while the matcher reacquires the same gate.
    max_pair_target_jump_ratio: float = 0.32
    max_pair_separation_jump_ratio: float = 0.30

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        if self.max_age_s <= 0.0:
            raise ValueError("max_age_s must be positive")
        if not 0.0 < self.smoothing_alpha <= 1.0:
            raise ValueError("smoothing_alpha must be between 0 and 1")
        if not 0.0 <= self.deadband_ratio < 1.0:
            raise ValueError("deadband_ratio must be between 0 and 1")
        if not 0 <= self.max_delta_pwm <= STEERING_MAX_DELTA:
            raise ValueError("max_delta_pwm must be within steering limits")
        if self.gain <= 0.0:
            raise ValueError("gain must be positive")
        if not 0.0 < self.max_pair_target_jump_ratio <= 1.0:
            raise ValueError("max_pair_target_jump_ratio must be between 0 and 1")
        if not 0.0 < self.max_pair_separation_jump_ratio <= 1.0:
            raise ValueError("max_pair_separation_jump_ratio must be between 0 and 1")


@dataclass(frozen=True)
class VisualGateCorrection:
    steering_delta_pwm: int
    normalized_error: float
    target_x: float
    confidence: float
    observed_at_s: float
    area_ratio: float
    separation_ratio: float = 0.0


class VisualGateCentering:
    """Filter valid buoy pairs into a bounded, expiring steering correction."""

    def __init__(self, config: VisualGateCorrectionConfig | None = None) -> None:
        self.config = config or VisualGateCorrectionConfig()
        self._smoothed_error: float | None = None
        self._last_correction: VisualGateCorrection | None = None

    def reset(self) -> None:
        self._smoothed_error = None
        self._last_correction = None

    def update(
        self,
        detections: Sequence[Detection],
        *,
        frame_width: int,
        frame_height: int,
        now_s: float | None = None,
    ) -> VisualGateCorrection | None:
        now = time.monotonic() if now_s is None else float(now_s)
        pair = select_visual_gate_pair(
            detections,
            frame_width,
            frame_height,
            min_confidence=self.config.min_confidence,
            red_on_left=self.config.red_on_left,
        )
        if pair is None:
            return self.current(now_s=now)
        previous = self._last_correction
        if previous is not None and now - previous.observed_at_s <= self.config.max_age_s:
            target_jump = abs(pair.target_x - previous.target_x) / max(float(frame_width), 1.0)
            separation_jump = abs(pair.separation_ratio - previous.separation_ratio)
            if (
                target_jump > self.config.max_pair_target_jump_ratio
                or separation_jump > self.config.max_pair_separation_jump_ratio
            ):
                # This is usually a red buoy from one gate paired with a green
                # buoy from the next gate.  Returning the expiring correction
                # is safer than commanding a full turn from one bad frame.
                return self.current(now_s=now)
        image_center = frame_width / 2.0
        raw_error = clamp((pair.target_x - image_center) / image_center, -1.0, 1.0)
        if self._smoothed_error is None:
            smoothed_error = raw_error
        else:
            smoothed_error = self._smoothed_error + self.config.smoothing_alpha * (
                raw_error - self._smoothed_error
            )
        self._smoothed_error = smoothed_error
        effective_error = (
            0.0
            if abs(smoothed_error) <= self.config.deadband_ratio
            else smoothed_error
        )
        delta = int(
            round(
                clamp(
                    effective_error * self.config.gain,
                    -1.0,
                    1.0,
                )
                * self.config.max_delta_pwm
            )
        )
        self._last_correction = VisualGateCorrection(
            steering_delta_pwm=delta,
            normalized_error=smoothed_error,
            target_x=pair.target_x,
            confidence=pair.confidence,
            observed_at_s=now,
            area_ratio=pair.area_ratio,
            separation_ratio=pair.separation_ratio,
        )
        return self._last_correction

    def current(self, *, now_s: float | None = None) -> VisualGateCorrection | None:
        now = time.monotonic() if now_s is None else float(now_s)
        if (
            self._last_correction is None
            or now - self._last_correction.observed_at_s > self.config.max_age_s
        ):
            return None
        return self._last_correction


class VisualTargetTracker:
    """Stabilize buoy targets across brief one-buoy detection gaps.

    Enhancements from open-source repos:
    - EMA smoothing with configurable alpha (RoboBoat_SP25 history deque concept)
    - buoy_area_ratio tracking for dual-gain steering (Crogued approach/positioning)
    """

    def __init__(
        self,
        *,
        hold_s: float = 0.8,
        smoothing_alpha: float = 0.5,
        red_on_left: bool = True,
    ) -> None:
        if hold_s < 0.0:
            raise ValueError("hold_s must be non-negative")
        if not 0.0 < smoothing_alpha <= 1.0:
            raise ValueError("smoothing_alpha must be between 0 and 1")
        self.hold_s = hold_s
        self.smoothing_alpha = smoothing_alpha
        self.red_on_left = bool(red_on_left)
        self._last_pair_target_x: float | None = None
        self._last_pair_at: float | None = None
        self._last_target_x: float | None = None
        self._last_target_at: float | None = None
        self._buoy_area_ratio: float = 0.0

    @property
    def buoy_area_ratio(self) -> float:
        """Largest buoy area as fraction of frame from last update."""
        return self._buoy_area_ratio

    def reset(self) -> None:
        """Forget stale visual targets."""
        self._last_pair_target_x = None
        self._last_pair_at = None
        self._last_target_x = None
        self._last_target_at = None
        self._buoy_area_ratio = 0.0

    def update(
        self,
        detections: Sequence[Detection],
        *,
        now: float,
        frame_width: int = 0,
        frame_height: int = 0,
    ) -> float | None:
        """Return a smoothed target while tolerating brief detection gaps."""
        has_red = any(detection.label == "red_buoy" for detection in detections)
        has_green = any(detection.label == "green_buoy" for detection in detections)
        has_target = has_red or has_green
        target_x = select_target_x(detections)
        valid_pair = has_red and has_green
        if valid_pair and frame_width > 0 and frame_height > 0:
            pair = select_visual_gate_pair(
                detections,
                frame_width,
                frame_height,
                red_on_left=self.red_on_left,
            )
            if pair is None:
                # Multiple buoys are visible but none form one credible gate.
                # Hold the prior target briefly instead of combining two gates.
                valid_pair = False
                has_target = False
                target_x = None
            else:
                target_x = pair.target_x

        # Track buoy size for dual-gain steering
        if has_target and frame_width > 0 and frame_height > 0:
            self._buoy_area_ratio = max_buoy_area_ratio(detections, frame_width, frame_height)
        elif not has_target:
            self._buoy_area_ratio = 0.0

        if valid_pair:
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


@dataclass(frozen=True)
class SearchConfig:
    """Gentle visual recovery settings when no buoy is visible: forward advance with gentle scan."""

    center_pwm: int = NEUTRAL_PWM
    max_delta: int = 25
    period_s: float = 6.0
    throttle_pwm: int = 1555

    def __post_init__(self) -> None:
        if not PWM_MIN <= self.center_pwm <= PWM_MAX:
            raise ValueError("center_pwm must be between 1000 and 2000")
        if self.max_delta < 0 or self.center_pwm - self.max_delta < PWM_MIN:
            raise ValueError("max_delta drives steering below PWM_MIN")
        if self.center_pwm + self.max_delta > PWM_MAX:
            raise ValueError("max_delta drives steering above PWM_MAX")
        if self.period_s <= 0.0:
            raise ValueError("period_s must be positive")
        if not PWM_MIN <= self.throttle_pwm <= PWM_MAX:
            raise ValueError("throttle_pwm must be between 1000 and 2000")

class VisualSearchController:
    """Sweep steering inward (left-biased) while keeping slight throttle until buoy reacquisition."""

    def __init__(self, config: SearchConfig = SearchConfig()) -> None:
        self.config = config
        self._started_at: float | None = None

    @property
    def active(self) -> bool:
        return self._started_at is not None

    def reset(self) -> None:
        """Stop the sweep after a buoy is reacquired."""
        self._started_at = None

    def update(self, *, now: float) -> tuple[int, int]:
        """Return (steering_pwm, throttle_pwm) sweeping inward (left-first) with slight throttle."""
        if self._started_at is None:
            self._started_at = now
        elapsed = max(0.0, now - self._started_at)
        phase = 2.0 * math.pi * elapsed / self.config.period_s
        # Sweep left first (-sin), oscillating between sharp inward turn and gentle check
        steer_pwm = self.config.center_pwm - self.config.max_delta * math.sin(phase)
        return int(round(clamp(steer_pwm, PWM_MIN, PWM_MAX))), self.config.throttle_pwm
def compute_sector_target_heading(x: float | None, y: float | None) -> float:
    """Return the optimal sector waypoint heading (deg) for the current arena position."""
    if x is None or y is None:
        return 270.0

    # 1. Gate 1 -> Gate 2 (target X=9.0, Y=0.0): Heading 345 deg (North-North-West)
    if x >= 7.0 and y < 0.0:
        return 345.0

    # 2. Gate 2 -> Gate 3 (target X=11.0, Y=6.0): Heading 20 deg (North-North-East)
    if x >= 6.5 and 0.0 <= y < 6.0:
        return 20.0

    # 3. Gate 3 -> Gate 4 (target X=6.0, Y=10.0): Heading 310 deg (North-West into Gate 4)
    if x >= 4.0 and y >= 6.0:
        return 310.0

    # 4. Top Straight Corridor (Gate 4 -> 5 -> 6 -> 7 along Y=10.0): Heading 270 deg (West)
    if -6.0 <= x < 4.0 and y >= 7.0:
        return 270.0

    # 5. Gate 7 -> Gate 8 (turn South-West to X=-11.0, Y=6.0): Heading 230 deg (South-West)
    if x < -6.0 and y >= 5.5:
        return 230.0

    # 6. Gate 8 -> Gate 9 (target X=-9.0, Y=0.0): Heading 160 deg (South-South-East toward X=-9.0)
    if x < -5.0 and 0.0 <= y < 5.5:
        return 160.0

    # 7. Gate 9 -> Gate 10 (target X=-11.0, Y=-6.0): Heading 200 deg (South-South-West toward X=-11.0)
    if x < -5.0 and -6.2 <= y < 0.0:
        return 200.0
    if y < -6.2:
        return 90.0
    return 270.0

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
    straight_near_pwm: int = 1540
    straight_cruise_pwm: int = 1560
    straight_far_pwm: int = 1600
    far_area_ratio: float = 0.03
    near_area_ratio: float = 0.15
    steering_boost_threshold_pwm: int = 200
    steering_boost_pwm: int = 20
    hold_s: float = 1.2
    ramp_pwm_per_s: float = 150.0

    def __post_init__(self) -> None:
        if not (
            NEUTRAL_PWM < self.near_pwm
            <= self.cruise_pwm
            <= self.far_pwm
            <= 1600
        ):
            raise ValueError(
                "near_pwm, cruise_pwm, and far_pwm must be ordered above neutral and <= 1600"
            )
        if not (
            NEUTRAL_PWM < self.straight_near_pwm
            <= self.straight_cruise_pwm
            <= self.straight_far_pwm
            <= 1600
        ):
            raise ValueError(
                "straight throttle PWMs must be ordered above neutral and <= 1600"
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
    heading_deg: float | None = None,
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
    steering_delta = abs(steering_pwm - NEUTRAL_PWM)

    # 4-buoy straight corridor: multiple buoys in line and low steering deflection
    is_straight_corridor = (
        (len(relevant) >= 3 and steering_delta <= 80)
        or (
            heading_deg is not None
            and 235.0 <= heading_deg <= 305.0
            and steering_delta <= 90
        )
    )

    if is_straight_corridor:
        # Max throttle 1700 ONLY on the 4-buoy straight corridor
        if area_ratio <= config.far_area_ratio:
            pwm = config.straight_far_pwm
        elif area_ratio >= config.near_area_ratio:
            pwm = config.straight_near_pwm
        else:
            pwm = config.straight_cruise_pwm
    else:
        # Capped at max 1600 on all other parts of the track
        if area_ratio <= config.far_area_ratio:
            pwm = config.far_pwm
        elif area_ratio >= config.near_area_ratio:
            pwm = config.near_pwm
        else:
            pwm = config.cruise_pwm

        if steering_delta > config.steering_boost_threshold_pwm:
            pwm = min(config.far_pwm, pwm + config.steering_boost_pwm)

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
        heading_deg: float | None = None,
    ) -> int:
        """Return the next smoothed throttle command."""
        desired_pwm = compute_visual_throttle_pwm(
            detections,
            frame_width,
            frame_height,
            steering_pwm,
            heading_deg=heading_deg,
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


COURSE_WAYPOINTS_A: tuple[tuple[float, float], ...] = (
    (11.0, -6.0),
    (9.0, 0.0),
    (11.0, 6.0),
    (6.0, 10.0),
    (2.0, 10.0),
    (-2.0, 10.0),
    (-6.0, 10.0),
    (-11.0, 6.0),
    (-9.0, 0.0),
    (-11.3, -6.0),
)
# Gate crossing geometry is kept separate from the guidance waypoints.  In
# sensor-only mode it prevents a GPS point that merely comes close to a
# midpoint from advancing the mission; progress must cross the physical gate
# plane inside its opening.  The 0.25 m margin mirrors the Webots scorer's
# hull-centre tolerance and is deliberately small enough to expose a missed
# gate during transfer testing.
COURSE_GATE_CROSSING_A: tuple[tuple[str, float, float, float], ...] = (
    ("y", -6.0, 10.0, 12.0),
    ("y", 0.0, 8.0, 10.0),
    ("y", 6.0, 10.0, 12.0),
    ("x", 6.0, 9.0, 11.0),
    ("x", 2.0, 9.0, 11.0),
    ("x", -2.0, 9.0, 11.0),
    ("x", -6.0, 9.0, 11.0),
    ("y", 6.0, -12.0, -10.0),
    ("y", 0.0, -10.0, -8.0),
    ("y", -6.0, -12.0, -10.0),
)
# Fixed headings for the two blind left turns in Arena A.  The first three
# buoy pairs are completed before the top-corridor turn; the second turn is
# only after the four vertical pairs.  These values are the centreline
# bearings from Gate 3 -> Gate 4 and Gate 7 -> Gate 8, not a generic 90-degree
# command: holding a more northerly heading would pass above the next opening
# before the boat could see the buoy pair.  Arena B mirrors these headings.
# The headings are deliberately independent of YOLO so a missing/ambiguous
# buoy frame cannot change the mission phase in a blind corner.
COURSE_BLIND_TURN_HEADINGS_A: dict[int, float] = {
    3: 309.0,  # Gate 3 -> Gate 4, northwest entry to the top corridor
    7: 231.0,  # Gate 7 -> Gate 8, southwest entry to the left slalom
}
# The lower buoy of the first vertical pair can sit directly in the forward
# ultrasonic cone if the hull turns toward the midpoint too early.  Stage a
# little to the open/east side first, then enter the physical midpoint from
# above the lower buoy.  Arena B mirrors the X coordinate automatically.
COURSE_BLIND_STAGING_A: dict[int, tuple[float, float]] = {
    3: (7.20, 9.50),
}
COURSE_BLIND_STAGING_RELEASE_Y_A: dict[int, float] = {
    3: 9.35,
}
# A single-thruster hull keeps lateral momentum while it changes heading.
# Apply only a bounded cross-track correction around the blind-leg centreline;
# this recentres the hull without resurrecting a continuous hard-left command.
# The nominal Gate-3->Gate-4 bearing is north-west, but the stern thruster
# carries the bow above that line while it yaws.  Allow a stronger bounded
# south-side correction so the hull reaches the vertical opening near its
# y=10.0 m midpoint instead of stopping against the green buoy at y=11.
COURSE_BLIND_CROSS_TRACK_GAIN_DEG_PER_M = 18.0
COURSE_BLIND_MAX_CROSS_TRACK_CORRECTION_DEG = 28.0
COURSE_MARKER_WAYPOINTS_A: tuple[tuple[float, float], ...] = (
    (-9.7, -8.7),  # Biru: checkpoint pertama, harus dilintasi.
    (-6.9, -11.9),  # Hijau: checkpoint kedua, harus dilintasi.
)
# The rectangles are physical floating obstacles in the competition layout,
# not targets to drive through.  The deterministic route deliberately keeps
# the hull centre on the safe side of each rectangle: west/left of the first
# blue box, then east/right (with a small north lead) of the second green box.
# Scoring remains tied to the measured marker centres and the same offsets are
# mirrored for Arena B.
COURSE_MARKER_GUIDANCE_OFFSETS_A: tuple[tuple[float, float], ...] = (
    (-1.50, -0.50),
    (1.35, 0.65),
)
# After the right-side green pass, use a short north-east staging leg before
# the longer return.  This keeps the single-thruster hull away from the south
# wall while it rotates toward the dock.
COURSE_DOCK_RETURN_WAYPOINTS_A: tuple[tuple[float, float], ...] = (
    (-4.8, -10.8),
    (1.0, -8.5),
    (7.0, -8.3),
)
# The final dock is the blue vertical box with three blue buoys at the original
# start/finish area.  A short northern entry makes the final southbound berth
# approach reproducible with the single steerable thruster.
COURSE_DOCK_ENTRY_WAYPOINT_A: tuple[float, float] = (11.5, -10.45)
COURSE_DOCK_WAYPOINT_A: tuple[float, float] = (11.5, -13.0)
COURSE_DOCK_HEADING_A_DEG = 180.0
COURSE_MARKER_CORRIDOR_HALF_WIDTH_M = 0.75
COURSE_START_WAYPOINT_A: tuple[float, float] = (11.1, -11.5)
COURSE_ARENA_MIRROR_X = 15.0
COURSE_WALL_LIMIT_Y_M = 14.3
# Keep a generous margin for the hull's residual momentum near the lower
# marker basin.  The Webots wall body is reached at 14.3 m, while a 2.4 m
# recovery margin still leaves room to approach the green marker's safe plane.
COURSE_SOUTH_RECOVERY_Y_M = -(COURSE_WALL_LIMIT_Y_M - 2.4)
COURSE_LATERAL_RECOVERY_X_A = -(COURSE_WALL_LIMIT_Y_M - 2.4)
# Turn anticipation is intentionally asymmetric.  The ordinary S-turn gates
# can blend into their outgoing leg, but the two blind corners must not: the
# boat has to pass the last visible buoy pair on a straight heading first,
# then make one deliberate left pivot.  Values are metres remaining along each
# incoming leg, indexed by target gate (Gate 1 .. Gate 10).
COURSE_GATE_LOOKAHEAD_M: tuple[float, ...] = (
    5.0,
    2.0,
    0.35,
    2.0,
    3.0,
    1.0,
    0.35,
    2.0,
    6.0,
    5.0,
)
# Optional feed-forward Y offsets are kept at zero for the scored gates.  The
# upper buoy pairs are centred on y=10 m; asking the controller to aim at a
# point 0.8 m south of that line makes the single-thruster hull enter the red
# row before it has crossed the opening.  The small X leads below are retained
# for the existing right-hand slalom; correction for upper-corridor sway
# belongs to the closed-loop bearing controller, not a shifted Y waypoint.
COURSE_GATE_GUIDANCE_X_OFFSET_A: tuple[float, ...] = (
    0.0,
    0.60,
    # Keep the Gate-3 entry on the inside half of the opening so the outside
    # green buoy has clearance when the post-crossing pivot starts.
    -0.35,
    0.20,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
)
COURSE_GATE_GUIDANCE_Y_OFFSET: tuple[float, ...] = (
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
)


def normalize_course_arena(value: object) -> str:
    arena = str(value or "A").strip().upper()
    if arena not in {"A", "B"}:
        raise ValueError("arena must be 'A' or 'B'")
    return arena


def course_point_for_arena(point: tuple[float, float], arena: str) -> tuple[float, float]:
    selected = normalize_course_arena(arena)
    if selected == "A":
        return point
    return ((2.0 * COURSE_ARENA_MIRROR_X) - point[0], point[1])


def course_heading_for_arena(heading_a_deg: float, arena: str) -> float:
    selected = normalize_course_arena(arena)
    return heading_a_deg % 360.0 if selected == "A" else (-heading_a_deg) % 360.0


class CoursePhase(str, Enum):
    APPROACH = "APPROACH"
    TURN = "TURN"
    CORRIDOR = "CORRIDOR"
    MARKER_BLUE = "MARKER_BLUE"
    MARKER_GREEN = "MARKER_GREEN"
    DOCK_RETURN = "DOCK_RETURN"
    DOCK_APPROACH = "DOCK_APPROACH"
    DOCK = "DOCK"
    FINISH = "FINISH"


@dataclass(frozen=True)
class CourseRouteConfig:
    arena: str = "A"
    # Feed-forward commands are calibrated for the 9.5 kg monohull model.
    # Values around 1540 PWM produced only ~0.4 m/s in Webots, which made a
    # complete lap unnecessarily long.  The controller still closes the loop
    # on measured speed and applies the capture/braking envelope near gates.
    cruise_pwm: int = 1580
    approach_pwm: int = 1570
    turn_pwm: int = 1560
    # A blind gate turn needs a short, high-authority forward pulse.  It is
    # applied only after the last visible gate has actually been crossed; the
    # approach remains straight so the boat reaches the blind spot first.
    # Once the hull has entered the corner, use a lower yaw-capture thrust so
    # it does not build 0.5 m/s of north-east momentum while still 60+ degrees
    # off the Gate-4 bearing.  The separate kick PWM below is only for the
    # brief lateral impulse that cancels the incoming eastward velocity.
    blind_turn_pwm: int = 1560
    blind_turn_kick_pwm: int = 1580
    # Gate 3 needs a short high-authority pivot because 1580 PWM produces only
    # a small force on the 9.5 kg hull.  This is a burst, not the cruise
    # command; it is released on heading capture or at the bounded timeout.
    blind_pivot_pwm: int = 1780
    blind_pivot_duration_s: float = 0.45
    blind_pivot_max_duration_s: float = 0.75
    blind_pivot_extension_step_s: float = 0.05
    blind_pivot_yaw_rate_target_dps: float = 25.0
    blind_pivot_error_deg: float = 28.0
    # Gate 3's green buoy is on the outside of the Arena-A left pivot.  A
    # high-thrust burst is safe only while the hull still has this much room
    # on that side; otherwise use the bounded low pivot thrust and let yaw
    # capture finish without pressing the hull into the buoy.
    blind_pivot_green_side_margin_m: float = 0.25
    # The blind corner only needs a short lateral peek to expose the next
    # buoy pair.  After that pulse, the normal heading controller owns RC1;
    # holding a fixed lateral command until the gate line makes the hull turn
    # continuously and miss the vertical opening.
    blind_pre_turn_distance_m: float = 1.20
    blind_turn_kick_duration_s: float = 0.85
    # Gate 3 is a known blind corner.  The vessel may use cruise thrust only
    # after both its heading and projected path have captured the Gate-4
    # centreline; this prevents a sharp turn from turning into a long arc.
    blind_lane_heading_tolerance_deg: float = 12.0
    blind_lane_cross_track_m: float = 0.35
    blind_lane_release_cross_track_m: float = 0.65
    # If the hull has drifted north of the Gate-4 opening, recapture the
    # opening from the approach side before the green buoy enters the bow
    # envelope.  The south bias is deliberately small: it keeps the track in
    # the 9--11 m aperture without aiming at the red buoy.
    blind_entry_recovery_y_margin_m: float = 0.25
    blind_entry_recovery_x_margin_m: float = 0.05
    blind_entry_recovery_south_bias_m: float = 0.30
    blind_entry_recovery_open_side_m: float = 0.80
    # Once the bow is inside the last 1.45 m before Gate 4, a saturated
    # azimuth command can keep translating the hull into the north/green buoy
    # even though the requested bearing points south.  Preserve the already
    # captured body heading and use a short positive pulse to cross the
    # opening; the position envelope ends as soon as the gate is crossed.
    blind_green_clearance_start_m: float = 1.45
    blind_green_clearance_y_margin_m: float = 0.45
    blind_green_clearance_pwm: int = 1560
    corridor_pwm: int = 1570
    # Kept as bounded compatibility knobs for older callers; the current
    # corridor controller uses ``corridor_pwm`` rather than a high kick.
    corridor_turn_pwm: int = 1590
    corridor_recapture_pwm: int = 1580
    marker_pwm: int = 1555
    dock_return_pwm: int = 1555
    dock_approach_pwm: int = 1535
    dock_turn_pwm: int = 1540
    dock_pwm: int = 1508
    finish_pwm: int = NEUTRAL_PWM
    cruise_speed_mps: float = 0.95
    approach_speed_mps: float = 0.80
    slalom_speed_mps: float = 0.68
    turn_speed_mps: float = 0.56
    left_turn_capture_speed_mps: float = 0.22
    left_turn_brake_error_deg: float = 45.0
    left_turn_brake_pwm: int = 1300
    corridor_speed_mps: float = 0.70
    marker_speed_mps: float = 0.35
    dock_return_speed_mps: float = 0.42
    dock_approach_speed_mps: float = 0.20
    dock_speed_mps: float = 0.12
    speed_kp_pwm_per_mps: float = 65.0
    overspeed_deadband_mps: float = 0.08
    max_forward_pwm: int = 1620
    # Do not carry forward speed while the bow is still pointed far away from
    # the next leg. A single-thruster hull gets only a small creep pulse until
    # its heading is recovered, then accelerates again on a clear leg.
    heading_slow_error_deg: float = 35.0
    heading_hold_error_deg: float = 60.0
    heading_slow_speed_mps: float = 0.24
    heading_hold_speed_mps: float = 0.12
    heading_slow_pwm: int = 1524
    heading_creep_pwm: int = 1512
    braking_deceleration_mps2: float = 0.55
    # A short capture envelope around each buoy line keeps the centreline
    # crossing accurate.  Cruise/approach speed is unchanged several metres
    # away from a gate.
    waypoint_stop_margin_m: float = 0.85
    marker_stop_margin_m: float = 1.10
    reverse_brake_pwm: int = 1400
    reverse_turn_pwm: int = 1320
    reverse_turn_heading_error_deg: float = 48.0
    marker_reverse_turn_heading_error_deg: float = 62.0
    marker_lookahead_m: float = 1.00
    marker_turn_blend_limit: float = 0.30
    marker_green_lookahead_m: float = 1.40
    marker_green_turn_blend_limit: float = 0.45
    dock_return_waypoint_tolerance_m: float = 1.00
    dock_return_progress_ratio: float = 0.90
    dock_return_max_cross_track_m: float = 2.00
    heading_tolerance_deg: float = 4.0
    turn_error_deg: float = 28.0
    course_turn_brake_error_deg: float = 60.0
    # Gate 3 always gets a short pivot-brake window.  It is immediately
    # followed by the forward left pulse; this is a yaw aid, not a long stop.
    course_turn_brake_speed_mps: float = 0.30
    # A 1200 PWM reverse pulse only shaved ~0.15 m/s from the latest run.
    # Use a short, stronger brake so the hull enters the sharp pivot with
    # near-zero forward momentum instead of carrying east into the corridor.
    course_turn_brake_duration_s: float = 0.25
    course_turn_brake_pwm: int = 1050
    max_steering_delta: int = 400
    # PWM steering is already normalised by compute_heading_steering_pwm
    # (degrees/90 * max_delta). Gains above one saturate the azimuth too early
    # on this monohull; a small error then creates a large sideways component.
    # The bounded gain keeps travel aligned with the requested leg while the
    # explicit pivot/reverse pulses handle genuinely large turns.
    heading_control_gain: float = 2.0
    heading_derivative_damping_s: float = 0.08
    slalom_heading_gain: float = 3.5
    heading_slew_deg_per_step: float = 8.0
    # The four vertical pairs are centred exactly on y=10.0 m (buoys at y=9
    # and y=11).  Keep the nominal corridor on that line; cross-track trim
    # below moves only as much as needed to recover from hull sway.
    corridor_center_y_m: float = 10.0
    # Retained for configuration-file compatibility.  Midpoint bearing is
    # now the primary cross-track correction, so these are deliberately small
    # if a legacy caller enables the optional lane trim.
    corridor_heading_gain_deg_per_m: float = 18.0
    corridor_heading_limit_deg: float = 20.0
    # Hold the centreline with a moderate proportional gain.
    corridor_steering_gain: float = 2.5
    dock_tolerance_m: float = 0.75
    dock_heading_tolerance_deg: float = 15.0
    dock_max_speed_mps: float = 0.15
    dock_stable_time_s: float = 3.0
    dock_capture_radius_m: float = 1.50
    dock_capture_speed_mps: float = 0.06
    dock_creep_pwm: int = 1506
    dock_entry_alignment_radius_m: float = 2.60
    dock_entry_position_tolerance_m: float = 0.65
    dock_entry_heading_tolerance_deg: float = 18.0
    dock_entry_alignment_error_deg: float = 25.0
    dock_turn_error_deg: float = 20.0
    dock_turn_speed_ceiling_mps: float = 0.22
    dock_steering_max_delta: int = 260
    ultrasonic_slow_distance_m: float = 1.20
    ultrasonic_stop_distance_m: float = 0.55
    ultrasonic_release_distance_m: float = 0.85
    ultrasonic_side_clearance_m: float = 0.90
    ultrasonic_steering_delta: int = 260
    ultrasonic_escape_pwm: int = 1518
    path_lookahead_m: float = 5.00
    gate_exit_hold_m: float = 0.0

    def __post_init__(self) -> None:
        normalize_course_arena(self.arena)
        for name in (
            "cruise_pwm",
            "approach_pwm",
            "turn_pwm",
            "blind_turn_pwm",
            "blind_turn_kick_pwm",
            "blind_pivot_pwm",
            "corridor_pwm",
            "corridor_turn_pwm",
            "corridor_recapture_pwm",
            "marker_pwm",
            "dock_return_pwm",
            "dock_approach_pwm",
            "dock_turn_pwm",
            "reverse_brake_pwm",
            "reverse_turn_pwm",
            "left_turn_brake_pwm",
            "course_turn_brake_pwm",
            "heading_slow_pwm",
            "heading_creep_pwm",
            "dock_pwm",
            "finish_pwm",
        ):
            value = getattr(self, name)
            if not PWM_MIN <= value <= PWM_MAX:
                raise ValueError(f"{name} must be between 1000 and 2000")
        if self.heading_tolerance_deg <= 0.0:
            raise ValueError("heading_tolerance_deg must be positive")
        if self.turn_error_deg <= self.heading_tolerance_deg:
            raise ValueError("turn_error_deg must exceed heading_tolerance_deg")
        if not 0 <= self.max_steering_delta <= STEERING_MAX_DELTA:
            raise ValueError("max_steering_delta must be within steering limits")
        if not 0 <= self.dock_steering_max_delta <= STEERING_MAX_DELTA:
            raise ValueError("dock_steering_max_delta must be within steering limits")
        if self.heading_control_gain <= 0.0:
            raise ValueError("heading_control_gain must be positive")
        if self.heading_derivative_damping_s < 0.0:
            raise ValueError("heading_derivative_damping_s must be non-negative")
        if self.slalom_heading_gain <= 0.0:
            raise ValueError("slalom_heading_gain must be positive")
        if self.heading_slew_deg_per_step <= 0.0:
            raise ValueError("heading_slew_deg_per_step must be positive")
        if not self.heading_slow_error_deg < self.heading_hold_error_deg:
            raise ValueError("heading_slow_error_deg must be below heading_hold_error_deg")
        if not 0.0 < self.heading_hold_speed_mps <= self.heading_slow_speed_mps:
            raise ValueError("heading hold speeds must be positive and ordered")
        if self.corridor_heading_gain_deg_per_m <= 0.0:
            raise ValueError("corridor_heading_gain_deg_per_m must be positive")
        if not 0.0 < self.corridor_heading_limit_deg < 90.0:
            raise ValueError("corridor_heading_limit_deg must be between 0 and 90")
        if self.corridor_steering_gain <= 0.0:
            raise ValueError("corridor_steering_gain must be positive")
        if not 0.0 < self.blind_lane_heading_tolerance_deg < 45.0:
            raise ValueError("blind_lane_heading_tolerance_deg must be between 0 and 45")
        if not 0.0 < self.blind_lane_cross_track_m < self.blind_lane_release_cross_track_m:
            raise ValueError("blind lane cross-track thresholds must be ordered")
        if self.dock_tolerance_m <= 0.0:
            raise ValueError("dock_tolerance_m must be positive")
        for name in (
            "cruise_speed_mps",
            "approach_speed_mps",
            "slalom_speed_mps",
            "turn_speed_mps",
            "left_turn_capture_speed_mps",
            "left_turn_brake_error_deg",
            "corridor_speed_mps",
            "marker_speed_mps",
            "dock_return_speed_mps",
            "dock_approach_speed_mps",
            "dock_speed_mps",
            "speed_kp_pwm_per_mps",
            "braking_deceleration_mps2",
            "waypoint_stop_margin_m",
            "marker_stop_margin_m",
            "marker_lookahead_m",
            "marker_turn_blend_limit",
            "marker_green_lookahead_m",
            "marker_green_turn_blend_limit",
            "reverse_turn_heading_error_deg",
            "marker_reverse_turn_heading_error_deg",
            "dock_return_waypoint_tolerance_m",
            "dock_return_progress_ratio",
            "dock_return_max_cross_track_m",
            "dock_heading_tolerance_deg",
            "dock_max_speed_mps",
            "dock_stable_time_s",
            "dock_capture_radius_m",
            "dock_capture_speed_mps",
            "dock_entry_alignment_radius_m",
            "dock_entry_position_tolerance_m",
            "dock_entry_heading_tolerance_deg",
            "dock_entry_alignment_error_deg",
            "dock_turn_error_deg",
            "dock_turn_speed_ceiling_mps",
            "course_turn_brake_error_deg",
            "course_turn_brake_speed_mps",
            "course_turn_brake_duration_s",
            "blind_pre_turn_distance_m",
            "blind_turn_kick_duration_s",
            "blind_pivot_duration_s",
            "blind_pivot_max_duration_s",
            "blind_pivot_extension_step_s",
            "blind_pivot_yaw_rate_target_dps",
            "blind_pivot_error_deg",
            "blind_pivot_green_side_margin_m",
            "blind_entry_recovery_y_margin_m",
            "blind_entry_recovery_x_margin_m",
            "blind_entry_recovery_south_bias_m",
            "blind_entry_recovery_open_side_m",
            "blind_green_clearance_start_m",
            "blind_green_clearance_y_margin_m",
            "blind_green_clearance_pwm",
            "ultrasonic_slow_distance_m",
            "ultrasonic_stop_distance_m",
            "ultrasonic_release_distance_m",
            "ultrasonic_side_clearance_m",
            "path_lookahead_m",
        ):
            if float(getattr(self, name)) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if self.gate_exit_hold_m < 0.0:
            raise ValueError("gate_exit_hold_m must be non-negative")
        if self.blind_pivot_max_duration_s < self.blind_pivot_duration_s:
            raise ValueError(
                "blind_pivot_max_duration_s must be at least blind_pivot_duration_s"
            )
        if not 0.0 < self.marker_turn_blend_limit <= 1.0:
            raise ValueError("marker_turn_blend_limit must be within (0, 1]")
        if not 0.0 < self.marker_green_turn_blend_limit <= 1.0:
            raise ValueError("marker_green_turn_blend_limit must be within (0, 1]")
        if not 0.0 < self.dock_return_progress_ratio <= 1.0:
            raise ValueError("dock_return_progress_ratio must be within (0, 1]")
        if self.ultrasonic_stop_distance_m >= self.ultrasonic_slow_distance_m:
            raise ValueError(
                "ultrasonic_stop_distance_m must be below ultrasonic_slow_distance_m"
            )
        if self.ultrasonic_release_distance_m <= self.ultrasonic_stop_distance_m:
            raise ValueError(
                "ultrasonic_release_distance_m must exceed ultrasonic_stop_distance_m"
            )
        if not NEUTRAL_PWM <= self.max_forward_pwm <= PWM_MAX:
            raise ValueError("max_forward_pwm must be within forward PWM limits")
        if not NEUTRAL_PWM <= self.heading_slow_pwm <= self.max_forward_pwm:
            raise ValueError("heading_slow_pwm must be within forward PWM limits")
        if not NEUTRAL_PWM <= self.heading_creep_pwm <= self.max_forward_pwm:
            raise ValueError("heading_creep_pwm must be within forward PWM limits")
        if not PWM_MIN <= self.reverse_brake_pwm < NEUTRAL_PWM:
            raise ValueError("reverse_brake_pwm must be a reverse PWM")
        if not PWM_MIN <= self.reverse_turn_pwm < NEUTRAL_PWM:
            raise ValueError("reverse_turn_pwm must be a reverse PWM")
        if not PWM_MIN <= self.left_turn_brake_pwm < NEUTRAL_PWM:
            raise ValueError("left_turn_brake_pwm must be a reverse PWM")
        if not PWM_MIN <= self.course_turn_brake_pwm < NEUTRAL_PWM:
            raise ValueError("course_turn_brake_pwm must be a reverse PWM")
        if not 0 <= self.ultrasonic_steering_delta <= STEERING_MAX_DELTA:
            raise ValueError("ultrasonic_steering_delta must be within steering limits")
        if not NEUTRAL_PWM < self.ultrasonic_escape_pwm <= self.max_forward_pwm:
            raise ValueError("ultrasonic_escape_pwm must be low forward thrust")
        if not NEUTRAL_PWM < self.dock_creep_pwm <= self.dock_pwm:
            raise ValueError("dock_creep_pwm must be low forward thrust")


@dataclass(frozen=True)
class CourseDecision:
    phase: CoursePhase
    steering_pwm: int
    throttle_pwm: int
    target_waypoint: tuple[float, float] | None
    target_heading_deg: float | None
    heading_error_deg: float
    gate_count: int
    marker_count: int = 0
    finished: bool = False
    target_speed_mps: float = 0.0
    waypoint_distance_m: float = 0.0
    ultrasonic_min_m: float | None = None
    obstacle_avoidance: bool = False
    avoidance_reason: str = ""
    visual_correction_active: bool = False
    visual_correction_pwm: int = 0
    visual_target_error: float | None = None

    @property
    def sonar_min_m(self) -> float | None:
        """Deprecated alias retained for old dashboard integrations."""
        return self.ultrasonic_min_m


def _heading_to_point(
    x: float,
    y: float,
    target_x: float,
    target_y: float,
) -> float:
    """Return compass heading: 0° north, 90° east."""
    return normalize_heading(math.degrees(math.atan2(target_x - x, target_y - y)))


class CourseRouteController:
    """20 Hz speed/heading controller for a single steerable-thruster ASV."""

    def __init__(self, config: CourseRouteConfig | None = None) -> None:
        self.config = config or CourseRouteConfig()
        self._arena = normalize_course_arena(self.config.arena)
        self._gate_count = 0
        self._marker_count = 0
        self._target_heading_deg: float | None = None
        self._docked = False
        self._dock_entry_reached = False
        self._dock_return_index = 0
        self._dock_stable_since: float | None = None
        self._obstacle_latched = False
        self._gate_exit_origin: tuple[float, float] | None = None
        self._gate_exit_heading_deg: float | None = None
        self._last_heading_error_deg: float | None = None
        self._last_control_time_s: float | None = None
        self._last_position: tuple[float, float] | None = None
        self._obstacle_latched_since_s: float | None = None
        self._obstacle_reverse_used = False
        self._course_turn_brake_until_s = 0.0
        self._course_turn_brake_used = False
        self._blind_turn_kick_until_s = 0.0
        self._blind_pivot_max_until_s = 0.0
        self._blind_lane_aligned = False
        self._corridor_recenter_brake_until_s = 0.0
        self._corridor_recenter_kick_until_s = 0.0
        self._corridor_recenter_used = False

    @property
    def gate_count(self) -> int:
        return self._gate_count

    @property
    def marker_count(self) -> int:
        return self._marker_count

    @property
    def arena(self) -> str:
        return self._arena

    @property
    def waypoints(self) -> tuple[tuple[float, float], ...]:
        return tuple(course_point_for_arena(point, self._arena) for point in COURSE_WAYPOINTS_A)

    @property
    def start_waypoint(self) -> tuple[float, float]:
        return course_point_for_arena(COURSE_START_WAYPOINT_A, self._arena)

    @property
    def dock_waypoint(self) -> tuple[float, float]:
        return course_point_for_arena(COURSE_DOCK_WAYPOINT_A, self._arena)

    @property
    def dock_entry_waypoint(self) -> tuple[float, float]:
        return course_point_for_arena(COURSE_DOCK_ENTRY_WAYPOINT_A, self._arena)

    @property
    def marker_waypoints(self) -> tuple[tuple[float, float], ...]:
        return tuple(
            course_point_for_arena(point, self._arena)
            for point in COURSE_MARKER_WAYPOINTS_A
        )

    @property
    def marker_guidance_waypoints(self) -> tuple[tuple[float, float], ...]:
        points: list[tuple[float, float]] = []
        for index, marker in enumerate(self.marker_waypoints):
            offset_x_a, offset_y = COURSE_MARKER_GUIDANCE_OFFSETS_A[index]
            offset_x = offset_x_a if self._arena == "A" else -offset_x_a
            points.append((marker[0] + offset_x, marker[1] + offset_y))
        return tuple(points)

    @property
    def dock_return_waypoints(self) -> tuple[tuple[float, float], ...]:
        return tuple(
            course_point_for_arena(point, self._arena)
            for point in COURSE_DOCK_RETURN_WAYPOINTS_A
        )

    @property
    def dock_heading_deg(self) -> float:
        return course_heading_for_arena(COURSE_DOCK_HEADING_A_DEG, self._arena)

    def navigation_desired_heading(
        self,
        gate_index: int,
        x: float,
        y: float,
    ) -> float:
        """Blend gate-centering into the outgoing leg before the crossing.

        Far from the gate, direct bearing keeps the boat centred between its
        two buoys.  Inside the look-ahead radius, the desired heading follows
        the shortest angular interpolation toward the outgoing leg.  At the
        gate line it already equals the next leg's heading, which is important
        for cancelling the sway/yaw momentum of a single-thruster monohull.
        """
        waypoints = self.waypoints
        gate = waypoints[gate_index]
        lookahead_m = self.gate_lookahead_distance(gate_index)
        guidance_gate = self.guidance_waypoint(gate_index)
        direct_heading = _heading_to_point(x, y, *guidance_gate)
        if gate_index in {2, 6}:
            # Gate 3 and Gate 7 are the two known blind corners.  Do not blend
            # toward the outgoing leg while approaching their gate plane: the
            # hull must travel straight through the final visible buoy pair,
            # then pivot once after the scorer advances the gate.
            incoming_point = (
                self.start_waypoint if gate_index == 0 else waypoints[gate_index - 1]
            )
            blind_entry_target = (
                self.guidance_waypoint(gate_index)
                if gate_index == 2
                else gate
            )
            return _heading_to_point(
                incoming_point[0],
                incoming_point[1],
                blind_entry_target[0],
                blind_entry_target[1],
            )
        incoming_point = self.start_waypoint if gate_index == 0 else waypoints[gate_index - 1]
        incoming_dx = gate[0] - incoming_point[0]
        incoming_dy = gate[1] - incoming_point[1]
        incoming_length = max(0.001, math.hypot(incoming_dx, incoming_dy))
        # Along-track distance reaches zero at the gate line even if the hull
        # still has cross-track error.  Euclidean distance would keep steering
        # back toward the centre after the line and delay counter-steering.
        remaining_along_m = max(
            0.0,
            (gate[0] - x) * incoming_dx / incoming_length
            + (gate[1] - y) * incoming_dy / incoming_length,
        )
        if remaining_along_m >= lookahead_m:
            return direct_heading

        if gate_index + 1 < len(waypoints):
            next_point = self.guidance_waypoint(gate_index + 1)
        else:
            next_point = self.marker_guidance_waypoints[0]
        outgoing_heading = _heading_to_point(
            gate[0],
            gate[1],
            next_point[0],
            next_point[1],
        )
        blend = clamp(
            1.0 - remaining_along_m / lookahead_m,
            0.0,
            1.0,
        )
        # Smoothstep avoids a steering discontinuity at the look-ahead edge.
        blend = blend * blend * (3.0 - 2.0 * blend)
        heading_delta = signed_heading_error(outgoing_heading, direct_heading)
        return normalize_heading(direct_heading + blend * heading_delta)

    def gate_lookahead_distance(self, gate_index: int) -> float:
        if 0 <= gate_index < len(COURSE_GATE_LOOKAHEAD_M):
            return COURSE_GATE_LOOKAHEAD_M[gate_index]
        return self.config.path_lookahead_m

    def guidance_waypoint(self, gate_index: int) -> tuple[float, float]:
        gate = self.waypoints[gate_index]
        offset_x_a = COURSE_GATE_GUIDANCE_X_OFFSET_A[gate_index]
        offset_x = offset_x_a if self._arena == "A" else -offset_x_a
        offset_y = COURSE_GATE_GUIDANCE_Y_OFFSET[gate_index]
        return gate[0] + offset_x, gate[1] + offset_y

    def blind_turn_heading(self, gate_count: int) -> float | None:
        """Return the deterministic heading used in a blind left turn."""
        heading_a = COURSE_BLIND_TURN_HEADINGS_A.get(int(gate_count))
        if heading_a is None:
            return None
        return course_heading_for_arena(heading_a, self._arena)

    def blind_turn_center_target(
        self,
        gate_count: int,
        x: float,
        y: float,
    ) -> tuple[float, float]:
        """Return a safe staging target before the blind gate midpoint."""
        target = self.waypoints[gate_count]
        staging_a = COURSE_BLIND_STAGING_A.get(int(gate_count))
        release_y = COURSE_BLIND_STAGING_RELEASE_Y_A.get(int(gate_count))
        if staging_a is None or release_y is None:
            return target
        # Y is not mirrored between arenas; only the X coordinate changes.
        if y < release_y:
            return course_point_for_arena(staging_a, self._arena)
        return target

    def set_arena(self, arena: str) -> None:
        selected = normalize_course_arena(arena)
        if selected != self._arena:
            self._arena = selected
            self.reset()

    def reset(self) -> None:
        self._gate_count = 0
        self._marker_count = 0
        self._target_heading_deg = None
        self._docked = False
        self._dock_entry_reached = False
        self._dock_return_index = 0
        self._dock_stable_since = None
        self._obstacle_latched = False
        self._obstacle_latched_since_s = None
        self._obstacle_reverse_used = False
        self._gate_exit_origin = None
        self._gate_exit_heading_deg = None
        self._last_heading_error_deg = None
        self._last_control_time_s = None
        self._last_position = None
        self._course_turn_brake_until_s = 0.0
        self._course_turn_brake_used = False
        self._blind_turn_kick_until_s = 0.0
        self._blind_pivot_max_until_s = 0.0
        self._blind_lane_aligned = False
        self._corridor_recenter_brake_until_s = 0.0
        self._corridor_recenter_kick_until_s = 0.0
        self._corridor_recenter_used = False

    @staticmethod
    def _ultrasonic_readings(
        ultrasonic: Mapping[str, float] | None,
    ) -> dict[str, float]:
        values = {
            "front_left": 5.0,
            "front": 5.0,
            "front_right": 5.0,
            "left": 5.0,
            "right": 5.0,
        }
        if ultrasonic:
            for key in values:
                try:
                    reading = float(ultrasonic.get(key, values[key]))
                except (TypeError, ValueError):
                    continue
                if math.isfinite(reading):
                    values[key] = max(0.05, min(5.0, reading))
        return values

    def _obstacle_adjustment(
        self,
        ultrasonic: Mapping[str, float] | None,
        *,
        speed_mps: float = 0.0,
        now_s: float | None = None,
        gate_center_pass: bool = False,
    ) -> tuple[int, int | None, float, str]:
        now = time.monotonic() if now_s is None else float(now_s)
        readings = self._ultrasonic_readings(ultrasonic)
        front = readings["front"]
        # A vertical gate's lower buoy is intentionally in front of the bow
        # before the hull reaches the opening.  Near the known gate centre,
        # that return is not a collision threat: stopping at it would make
        # the boat fail just below the pair.  Keep the side envelope active,
        # but suspend only the front-stop latch for this bounded pass window.
        if gate_center_pass:
            self._obstacle_latched = False
            self._obstacle_latched_since_s = None
            self._obstacle_reverse_used = False
        elif front <= self.config.ultrasonic_stop_distance_m:
            if not self._obstacle_latched:
                self._obstacle_latched_since_s = now
                self._obstacle_reverse_used = False
            self._obstacle_latched = True
        elif (
            self._obstacle_latched
            and front >= self.config.ultrasonic_release_distance_m
        ):
            self._obstacle_latched = False
            self._obstacle_latched_since_s = None
            self._obstacle_reverse_used = False

        clearance = self.config.ultrasonic_side_clearance_m

        def danger(distance: float) -> float:
            return clamp((clearance - distance) / clearance, 0.0, 1.0)

        left_danger = 0.70 * danger(readings["front_left"]) + 0.30 * danger(readings["left"])
        right_danger = 0.70 * danger(readings["front_right"]) + 0.30 * danger(readings["right"])
        if self._obstacle_latched and abs(left_danger - right_danger) < 0.05:
            # Choose the side with more measured free space when directly blocked.
            if readings["front_left"] <= readings["front_right"]:
                left_danger += 0.35
            else:
                right_danger += 0.35
        steering_delta = int(
            round(
                clamp(
                    left_danger - right_danger,
                    -1.0,
                    1.0,
                )
                * self.config.ultrasonic_steering_delta
            )
        )
        throttle_cap: int | None = None
        reason = ""
        if self._obstacle_latched:
            # A single azimuth thruster cannot steer at zero thrust. Apply a
            # small escape pulse while vectoring toward the clearer side.
            throttle_cap = self.config.ultrasonic_escape_pwm
            reason = "ULTRASONIC_FRONT_STOP"
            # If the bow is already touching/blocked, another forward pulse
            # cannot create yaw authority and only presses the hull harder into
            # the buoy or box.  After a short persistence window, use one
            # bounded reverse pulse to create clearance; the next cycles return
            # to the normal forward escape until the release hysteresis opens.
            if (
                not self._obstacle_reverse_used
                and self._obstacle_latched_since_s is not None
                and now - self._obstacle_latched_since_s >= 0.80
                and abs(float(speed_mps)) <= 0.04
            ):
                self._obstacle_reverse_used = True
                throttle_cap = self.config.reverse_brake_pwm
                reason = "ULTRASONIC_REVERSE_ESCAPE"
        elif front < self.config.ultrasonic_slow_distance_m and not gate_center_pass:
            ratio = (front - self.config.ultrasonic_stop_distance_m) / (
                self.config.ultrasonic_slow_distance_m
                - self.config.ultrasonic_stop_distance_m
            )
            throttle_cap = int(round(NEUTRAL_PWM + clamp(ratio, 0.0, 1.0) * 20.0))
            reason = "ULTRASONIC_FRONT_SLOW"
        elif steering_delta:
            reason = "ULTRASONIC_SIDE_CLEARANCE"
        return steering_delta, throttle_cap, min(readings.values()), reason

    def _target_speed(self, phase: CoursePhase, heading_error_deg: float) -> float:
        if phase is CoursePhase.DOCK:
            target = self.config.dock_speed_mps
        elif phase is CoursePhase.DOCK_RETURN:
            target = self.config.dock_return_speed_mps
        elif phase is CoursePhase.DOCK_APPROACH:
            target = self.config.dock_approach_speed_mps
        elif phase in {CoursePhase.MARKER_BLUE, CoursePhase.MARKER_GREEN}:
            target = self.config.marker_speed_mps
        elif phase is CoursePhase.TURN:
            target = self.config.turn_speed_mps
        elif phase is CoursePhase.CORRIDOR:
            target = self.config.corridor_speed_mps
        elif phase is CoursePhase.APPROACH and self._gate_count in (1, 2, 7, 8, 9):
            target = self.config.slalom_speed_mps
        elif abs(heading_error_deg) > self.config.heading_tolerance_deg:
            target = self.config.approach_speed_mps
        else:
            target = self.config.cruise_speed_mps
        # A few degrees of heading error is normal while following the
        # centreline.  Do not turn every small correction into a low-speed
        # manoeuvre; reserve the turn ceiling for a genuinely large error.
        if abs(heading_error_deg) >= 20.0:
            target = min(target, self.config.turn_speed_mps)
        return target

    def _speed_throttle(
        self,
        phase: CoursePhase,
        target_speed_mps: float,
        speed_mps: float,
    ) -> int:
        if target_speed_mps <= 0.01:
            return NEUTRAL_PWM
        if speed_mps > target_speed_mps + self.config.overspeed_deadband_mps:
            if phase in {
                CoursePhase.MARKER_BLUE,
                CoursePhase.MARKER_GREEN,
            }:
                return self.config.reverse_brake_pwm
            return NEUTRAL_PWM
        feedforward = {
            CoursePhase.APPROACH: self.config.approach_pwm,
            CoursePhase.TURN: self.config.turn_pwm,
            CoursePhase.CORRIDOR: self.config.corridor_pwm,
            CoursePhase.MARKER_BLUE: self.config.marker_pwm,
            CoursePhase.MARKER_GREEN: self.config.marker_pwm,
            CoursePhase.DOCK_RETURN: self.config.dock_return_pwm,
            CoursePhase.DOCK_APPROACH: self.config.dock_approach_pwm,
            CoursePhase.DOCK: self.config.dock_pwm,
            CoursePhase.FINISH: self.config.finish_pwm,
        }[phase]
        pwm = feedforward + self.config.speed_kp_pwm_per_mps * (target_speed_mps - speed_mps)
        return int(round(clamp(pwm, NEUTRAL_PWM, self.config.max_forward_pwm)))

    def _advance_marker_from_position(
        self,
        previous_position: tuple[float, float] | None,
        x: float,
        y: float,
    ) -> None:
        """Fallback marker tracker for hardware without `mark_count` MAVLink.

        It mirrors the Webots scorer: the vessel crosses an ordered safe-side
        plane beside each physical marker within a bounded corridor.
        """
        if previous_position is None or self._marker_count >= len(self.marker_waypoints):
            return
        marker_index = self._marker_count
        # Marker scoring uses the safe-side crossing plane, not the centre of
        # the physical rectangle. This lets the hull pass the obstacle without
        # requiring its centreline to overlap the floating box.
        marker_x, marker_y = self.marker_guidance_waypoints[marker_index]
        if marker_index == 0:
            incoming_x, incoming_y = self.waypoints[-1]
        else:
            incoming_x, incoming_y = self.marker_guidance_waypoints[marker_index - 1]
        route_dx = marker_x - incoming_x
        route_dy = marker_y - incoming_y
        route_length = math.hypot(route_dx, route_dy)
        if route_length <= 1e-6:
            return
        prev_x, prev_y = previous_position
        previous_along = (
            (prev_x - marker_x) * route_dx + (prev_y - marker_y) * route_dy
        ) / route_length
        current_along = (
            (x - marker_x) * route_dx + (y - marker_y) * route_dy
        ) / route_length
        if not (previous_along < 0.0 <= current_along):
            return
        ratio = -previous_along / (current_along - previous_along)
        crossing_x = prev_x + ratio * (x - prev_x)
        crossing_y = prev_y + ratio * (y - prev_y)
        lateral_m = abs(
            route_dx * (crossing_y - marker_y)
            - route_dy * (crossing_x - marker_x)
        ) / route_length
        if lateral_m <= COURSE_MARKER_CORRIDOR_HALF_WIDTH_M:
            self._marker_count += 1

    def _gate_crossed_from_position(
        self,
        previous_position: tuple[float, float] | None,
        x: float,
        y: float,
    ) -> bool:
        """Return whether the next physical gate was crossed validly.

        The simulator's ``gate_count`` is intentionally not needed by the
        real control path.  This geometric fallback uses only consecutive
        local-position samples and the known gate opening, with Arena B
        mirrored about the course centreline.
        """
        if previous_position is None or self._gate_count >= len(COURSE_GATE_CROSSING_A):
            return False
        axis, line, lower, upper = COURSE_GATE_CROSSING_A[self._gate_count]
        if self._arena == "B":
            if axis == "x":
                line = 2.0 * COURSE_ARENA_MIRROR_X - line
            else:
                lower, upper = sorted(
                    (
                        2.0 * COURSE_ARENA_MIRROR_X - lower,
                        2.0 * COURSE_ARENA_MIRROR_X - upper,
                    )
                )
        previous_x, previous_y = previous_position
        if axis == "y":
            crossed = (previous_y < line <= y) or (previous_y > line >= y)
            if not crossed or y == previous_y:
                return False
            ratio = (line - previous_y) / (y - previous_y)
            crossing = previous_x + ratio * (x - previous_x)
        else:
            crossed = (previous_x > line >= x) or (previous_x < line <= x)
            if not crossed or x == previous_x:
                return False
            ratio = (line - previous_x) / (x - previous_x)
            crossing = previous_y + ratio * (y - previous_y)
        return lower - 0.25 <= crossing <= upper + 0.25

    def marker_navigation_desired_heading(
        self,
        marker_index: int,
        x: float,
        y: float,
    ) -> float:
        """Pass a marker on its safe side, then pre-turn into the next leg."""
        markers = self.marker_guidance_waypoints
        marker = markers[marker_index]
        guidance = self.marker_guidance_waypoints[marker_index]
        incoming = self.waypoints[-1] if marker_index == 0 else markers[marker_index - 1]
        incoming_dx = marker[0] - incoming[0]
        incoming_dy = marker[1] - incoming[1]
        incoming_length = max(0.001, math.hypot(incoming_dx, incoming_dy))
        is_green_exit = marker_index == len(markers) - 1
        lookahead_m = (
            self.config.marker_green_lookahead_m
            if is_green_exit
            else self.config.marker_lookahead_m
        )
        turn_blend_limit = (
            self.config.marker_green_turn_blend_limit
            if is_green_exit
            else self.config.marker_turn_blend_limit
        )
        remaining_along_m = max(
            0.0,
            (marker[0] - x) * incoming_dx / incoming_length
            + (marker[1] - y) * incoming_dy / incoming_length,
        )
        direct_heading = _heading_to_point(x, y, *guidance)
        if remaining_along_m >= lookahead_m:
            return direct_heading
        outgoing = (
            self.marker_guidance_waypoints[marker_index + 1]
            if marker_index + 1 < len(markers)
            else self.dock_return_waypoints[0]
        )
        outgoing_heading = _heading_to_point(marker[0], marker[1], *outgoing)
        blend = clamp(
            1.0 - remaining_along_m / lookahead_m,
            0.0,
            1.0,
        )
        blend = (
            blend
            * blend
            * (3.0 - 2.0 * blend)
            * turn_blend_limit
        )
        return normalize_heading(
            direct_heading
            + blend * signed_heading_error(outgoing_heading, direct_heading)
        )

    def _dock_return_waypoint_reached(
        self,
        waypoint_index: int,
        x: float,
        y: float,
        return_waypoints: tuple[tuple[float, float], ...],
    ) -> bool:
        """Advance lower-basin waypoints by radius *or* along-track progress.

        A displacement monohull can pass a waypoint slightly wide while still
        travelling correctly through the next leg.  Chasing that point behind
        the vessel creates a large recovery circle and is precisely what sent
        the prior route toward the east wall.  The plane test is standard
        waypoint-following behaviour: once 90% of a leg is completed, retain
        forward progress and use the next safe waypoint.
        """
        target_x, target_y = return_waypoints[waypoint_index]
        if math.hypot(target_x - x, target_y - y) <= (
            self.config.dock_return_waypoint_tolerance_m
        ):
            return True
        anchor_x, anchor_y = (
            self.marker_guidance_waypoints[-1]
            if waypoint_index == 0
            else return_waypoints[waypoint_index - 1]
        )
        leg_x = target_x - anchor_x
        leg_y = target_y - anchor_y
        leg_sq = leg_x * leg_x + leg_y * leg_y
        if leg_sq <= 1e-6:
            return False
        progress = (
            ((x - anchor_x) * leg_x + (y - anchor_y) * leg_y) / leg_sq
        )
        cross_track = abs(
            leg_x * (y - anchor_y) - leg_y * (x - anchor_x)
        ) / math.sqrt(leg_sq)
        return (
            progress >= self.config.dock_return_progress_ratio
            and cross_track <= self.config.dock_return_max_cross_track_m
        )


    def step(
        self,
        *,
        gate_count: int | None,
        marker_count: int | None = None,
        x: float,
        y: float,
        heading_deg: float | None,
        speed_mps: float = 0.0,
        yaw_rate_dps: float | None = None,
        ultrasonic: Mapping[str, float] | None = None,
        sonar: Mapping[str, float] | None = None,
        now_s: float | None = None,
        arena: str | None = None,
    ) -> CourseDecision:
        if arena is not None:
            self.set_arena(arena)
        now = time.monotonic() if now_s is None else float(now_s)
        waypoints = self.waypoints
        marker_waypoints = self.marker_waypoints
        start_waypoint = self.start_waypoint
        previous_position = self._last_position
        if gate_count is None:
            # Hardware does not publish the simulator's scoring counter. Use
            # consecutive local-position samples and advance only when the
            # next physical gate plane is crossed inside its opening. The
            # simulator may still provide gate_count and then remains the
            # authoritative scorer.
            reported_gate_count = self._gate_count
            if self._gate_crossed_from_position(previous_position, x, y):
                reported_gate_count += 1
        else:
            reported_gate_count = max(0, min(len(waypoints), int(gate_count)))
        reported_marker_count = (
            None
            if marker_count is None
            else max(0, min(len(marker_waypoints), int(marker_count)))
        )
        if (
            reported_gate_count == 0
            and self._gate_count > 0
            and math.hypot(x - start_waypoint[0], y - start_waypoint[1]) <= 1.0
        ):
            self.reset()
        previous_gate_count = self._gate_count
        self._gate_count = max(
            self._gate_count,
            reported_gate_count,
        )
        gate_advanced = self._gate_count > previous_gate_count
        if gate_advanced and self._gate_count > 0:
            # Gate 3 gets an explicit pivot sequence: remove the incoming
            # forward momentum with a short reverse-brake pulse, then apply a
            # bounded high-thrust hard-left burst.  Without that burst the
            # 9.5 kg hull keeps translating north while RC1 is already left.
            if self._gate_count == 3:
                # A new blind leg must earn cruise again after its pivot.
                self._blind_lane_aligned = False
                self._course_turn_brake_used = True
                self._course_turn_brake_until_s = (
                    now + self.config.course_turn_brake_duration_s
                )
                pivot_start_s = self._course_turn_brake_until_s
                self._blind_turn_kick_until_s = (
                    pivot_start_s + self.config.blind_pivot_duration_s
                )
                self._blind_pivot_max_until_s = (
                    pivot_start_s + self.config.blind_pivot_max_duration_s
                )
            elif self._gate_count == 5:
                # Gate 5 is a straight continuation of the upper corridor.
                # Do not insert a reverse-brake/kick sequence here: it makes
                # the vessel stop beside the first floating box and leaves
                # the next midpoint without forward progress.  The bearing
                # controller below recentres the hull continuously.
                self._corridor_recenter_used = False
                self._corridor_recenter_brake_until_s = 0.0
                self._corridor_recenter_kick_until_s = 0.0
            else:
                self._course_turn_brake_until_s = 0.0
                self._course_turn_brake_used = False
                self._blind_pivot_max_until_s = 0.0
                # Gate 7 still gets one short forward lateral peek; its
                # conditional momentum brake is armed below when needed.
                self._blind_turn_kick_until_s = (
                    now + self.config.blind_turn_kick_duration_s
                    if self._gate_count == 7
                    else 0.0
                )
            crossed_index = min(self._gate_count - 1, len(waypoints) - 1)
            crossed_gate = waypoints[crossed_index]
            incoming_point = (
                start_waypoint if crossed_index == 0 else waypoints[crossed_index - 1]
            )
            self._gate_exit_heading_deg = _heading_to_point(
                incoming_point[0],
                incoming_point[1],
                crossed_gate[0],
                crossed_gate[1],
            )
            self._gate_exit_origin = (x, y)
            self._last_heading_error_deg = None
            self._last_control_time_s = None
        previous_marker_count = self._marker_count
        if reported_marker_count is not None:
            self._marker_count = max(self._marker_count, reported_marker_count)
        if self._gate_count >= len(waypoints):
            self._advance_marker_from_position(previous_position, x, y)
        marker_advanced = self._marker_count > previous_marker_count
        self._last_position = (x, y)
        if self._docked:
            return CourseDecision(
                phase=CoursePhase.FINISH,
                steering_pwm=NEUTRAL_PWM,
                throttle_pwm=self.config.finish_pwm,
                target_waypoint=None,
                target_heading_deg=None,
                heading_error_deg=0.0,
                gate_count=self._gate_count,
                marker_count=self._marker_count,
                finished=True,
                target_speed_mps=0.0,
            )

        dock_entry_alignment_active = False
        if self._gate_count >= len(waypoints) and self._marker_count < len(marker_waypoints):
            if self._marker_count == 0:
                target_waypoint = self.marker_guidance_waypoints[0]
                phase = CoursePhase.MARKER_BLUE
            else:
                target_waypoint = self.marker_guidance_waypoints[1]
                phase = CoursePhase.MARKER_GREEN
        elif self._gate_count >= len(waypoints):
            dock_waypoint = self.dock_waypoint
            dock_entry = self.dock_entry_waypoint
            return_waypoints = self.dock_return_waypoints
            while self._dock_return_index < len(return_waypoints):
                if not self._dock_return_waypoint_reached(
                    self._dock_return_index,
                    x,
                    y,
                    return_waypoints,
                ):
                    break
                self._dock_return_index += 1
            if self._dock_return_index < len(return_waypoints):
                phase = CoursePhase.DOCK_RETURN
                target_waypoint = return_waypoints[self._dock_return_index]
            else:
                dock_entry_distance = math.hypot(
                    dock_entry[0] - x,
                    dock_entry[1] - y,
                )
                dock_entry_heading_error = (
                    180.0
                    if heading_deg is None
                    else abs(signed_heading_error(self.dock_heading_deg, heading_deg))
                )
                if (
                    dock_entry_distance <= self.config.dock_entry_position_tolerance_m
                    and dock_entry_heading_error
                    <= self.config.dock_entry_heading_tolerance_deg
                    and abs(speed_mps) <= self.config.dock_approach_speed_mps + 0.05
                ):
                    self._dock_entry_reached = True
                if not self._dock_entry_reached:
                    phase = CoursePhase.DOCK_APPROACH
                    target_waypoint = dock_entry
                    # Only hold the berth heading while a heading correction
                    # is actually needed. Once the bow is aligned, continue
                    # steering toward the entry point; holding 180 degrees
                    # for the whole radius otherwise carries the hull past
                    # the entry line before it can latch.
                    dock_entry_alignment_active = (
                        dock_entry_distance <= self.config.dock_entry_alignment_radius_m
                        and dock_entry_heading_error
                        > self.config.dock_entry_heading_tolerance_deg
                    )
                else:
                    phase = CoursePhase.DOCK
                    target_waypoint = dock_waypoint
            dock_distance = math.hypot(
                dock_waypoint[0] - x,
                dock_waypoint[1] - y,
            )
            dock_heading_error = (
                180.0
                if heading_deg is None
                else abs(signed_heading_error(self.dock_heading_deg, heading_deg))
            )
            stable = (
                phase is CoursePhase.DOCK
                and dock_distance <= self.config.dock_tolerance_m
                and dock_heading_error <= self.config.dock_heading_tolerance_deg
                and abs(speed_mps) <= self.config.dock_max_speed_mps
            )
            if stable and self._dock_stable_since is None:
                self._dock_stable_since = now
            elif not stable:
                self._dock_stable_since = None
            if (
                self._dock_stable_since is not None
                and now - self._dock_stable_since >= self.config.dock_stable_time_s
            ):
                self._docked = True
                return CourseDecision(
                    phase=CoursePhase.FINISH,
                    steering_pwm=NEUTRAL_PWM,
                    throttle_pwm=self.config.finish_pwm,
                    target_waypoint=None,
                    target_heading_deg=None,
                    heading_error_deg=0.0,
                    gate_count=self._gate_count,
                    marker_count=self._marker_count,
                    finished=True,
                    target_speed_mps=0.0,
                    waypoint_distance_m=dock_distance,
                )
        else:
            target_waypoint = waypoints[self._gate_count]
            if self._gate_count in (3, 7):
                phase = CoursePhase.TURN
            elif 3 < self._gate_count < 7:
                phase = CoursePhase.CORRIDOR
            else:
                phase = CoursePhase.APPROACH

        corridor_gate_staging_active = False
        blind_turn_heading = self.blind_turn_heading(self._gate_count)
        blind_turn_active = phase is CoursePhase.TURN and blind_turn_heading is not None
        blind_lane_capture_active = False
        blind_entry_recovery_active = False
        blind_cross_track_m: float | None = None
        corridor_recenter_brake_active = (
            phase is CoursePhase.CORRIDOR
            and self._gate_count == 5
            and now < self._corridor_recenter_brake_until_s
        )
        corridor_recenter_kick_active = (
            phase is CoursePhase.CORRIDOR
            and self._gate_count == 5
            and now < self._corridor_recenter_kick_until_s
            and not corridor_recenter_brake_active
        )
        # A known arena has a deterministic mission contract.  Entering Gate
        # 3 or Gate 7 is the exact moment to commit to the blind left turn;
        # do not let heading slew or a late camera frame postpone it.
        blind_turn_entry = gate_advanced and self._gate_count in (3, 7)
        gate_exit_active = (
            self._gate_exit_origin is not None
            and self._gate_exit_heading_deg is not None
            and math.hypot(x - self._gate_exit_origin[0], y - self._gate_exit_origin[1])
            < self.config.gate_exit_hold_m
        )
        if gate_exit_active:
            desired_heading = self._gate_exit_heading_deg
        elif blind_turn_active:
            # Keep one fixed outgoing bearing for the whole blind leg.  The
            # previous implementation switched from the left-turn heading to
            # a moving staging point; that made the desired bearing curve as
            # the hull approached Gate 4 and caused a second, unintended turn.
            # A fixed 309° bearing in Arena A is the straight centreline from
            # Gate 3 (11,6) to Gate 4 (6,10); Arena B mirrors it.
            desired_heading = blind_turn_heading
            if (
                self._gate_count in (3, 7)
                and now >= self._blind_turn_kick_until_s
            ):
                # Estimate signed cross-track error against the actual blind
                # segment.  A positive error is on the left/north side of the
                # segment and therefore receives a bounded opposite heading
                # correction; once centred, the requested blind bearing is
                # restored and the hull runs straight again.
                previous_gate = self.waypoints[self._gate_count - 1]
                next_gate = self.waypoints[self._gate_count]
                line_dx = next_gate[0] - previous_gate[0]
                line_dy = next_gate[1] - previous_gate[1]
                line_length = max(0.001, math.hypot(line_dx, line_dy))
                line_sq = line_length * line_length
                projection = clamp(
                    (
                        (x - previous_gate[0]) * line_dx
                        + (y - previous_gate[1]) * line_dy
                    )
                    / line_sq,
                    0.0,
                    1.0,
                )
                line_x = previous_gate[0] + projection * line_dx
                line_y = previous_gate[1] + projection * line_dy
                cross_track_m = (
                    line_dx * (y - line_y) - line_dy * (x - line_x)
                ) / line_length
                if self._gate_count == 3:
                    blind_cross_track_m = cross_track_m
                desired_heading = normalize_heading(
                    blind_turn_heading
                    + clamp(
                        cross_track_m * COURSE_BLIND_CROSS_TRACK_GAIN_DEG_PER_M,
                        -COURSE_BLIND_MAX_CROSS_TRACK_CORRECTION_DEG,
                        COURSE_BLIND_MAX_CROSS_TRACK_CORRECTION_DEG,
                    )
                )
            if self._gate_count == 3:
                # Gate 3 is a two-stage manoeuvre, matching the physical
                # course: first make the short left peek that reveals Gate 4,
                # then run straight along the y=10 m entry lane.  Holding the
                # 309-degree peek bearing all the way to x=6 lets residual
                # northward momentum carry the hull onto Gate 4's green buoy
                # (the latest log reached x=8, y=10.9 before the ultrasonic
                # stop).  The lane target supplies a south correction before
                # that buoy is in the front sensor cone.
                release_y = COURSE_BLIND_STAGING_RELEASE_Y_A[3]
                if y >= release_y:
                    gate_four = self.waypoints[3]
                    travel_sign = -1.0 if self._arena == "A" else 1.0
                    if abs(x - gate_four[0]) <= 1.5:
                        # In the final 1.5 m, aim directly at the physical
                        # opening rather than continuing a long look-ahead.
                        desired_heading = _heading_to_point(
                            x,
                            y,
                            gate_four[0],
                            self.config.corridor_center_y_m,
                        )
                    else:
                        desired_heading = _heading_to_point(
                            x,
                            y,
                            x + travel_sign * 3.0,
                            self.config.corridor_center_y_m,
                        )
                    # The transition from peek to lane must not wait through
                    # normal heading slew while the boat is still coasting.
                    blind_lane_capture_active = True
                    # Position is the last reliable guard in this blind leg.
                    # If the hull is already north of the Gate-4 aperture,
                    # waiting for the x=6 crossing is too late: the green
                    # buoy is then beside the bow and the heading controller
                    # can only coast past it. Aim at a point just south of
                    # the aperture centre while there is still lateral room
                    # on the approach side. Keep it active until the hull is
                    # almost at the gate plane; releasing at x=6.75 would
                    # still leave the bow beside the green buoy. Mirror the
                    # approach-side test and target x for Arena B.
                    approach_side_offset_m = (
                        (x - gate_four[0])
                        if self._arena == "A"
                        else (gate_four[0] - x)
                    )
                    if (
                        y >= (
                            self.config.corridor_center_y_m
                            + self.config.blind_entry_recovery_y_margin_m
                        )
                        and approach_side_offset_m
                        > self.config.blind_entry_recovery_x_margin_m
                    ):
                        desired_heading = _heading_to_point(
                            x,
                            y,
                            gate_four[0]
                            + (
                                self.config.blind_entry_recovery_open_side_m
                                if self._arena == "A"
                                else -self.config.blind_entry_recovery_open_side_m
                            ),
                            self.config.corridor_center_y_m
                            - self.config.blind_entry_recovery_south_bias_m,
                        )
                        blind_entry_recovery_active = True
        elif phase is CoursePhase.CORRIDOR:
            # The upper pairs are four consecutive gates on y=10 m.  Use the
            # bearing to the next midpoint, not a fixed lane heading plus a
            # large cross-track angle.  The latter turned y=10.4 into a
            # 248-degree southwest command and pushed the hull toward the red
            # row; the midpoint bearing only asks for the small correction
            # that the geometry actually needs.  It also mirrors naturally for
            # Arena B and remains valid if the arena is scaled slightly.
            desired_heading = self.navigation_desired_heading(
                self._gate_count,
                x,
                y,
            )
            corridor_gate_staging_active = (
                self._gate_count in (4, 5, 6)
                and abs(y - self.config.corridor_center_y_m) >= 0.20
            )
        elif phase is CoursePhase.DOCK and math.hypot(
            target_waypoint[0] - x,
            target_waypoint[1] - y,
        ) <= self.config.dock_capture_radius_m:
            desired_heading = self.dock_heading_deg
        elif phase is CoursePhase.DOCK_APPROACH and dock_entry_alignment_active:
            # Do not enter the final berth sideways.  Pause at the entry
            # envelope and align southbound before progressing to the blue
            # dock target.
            desired_heading = self.dock_heading_deg
        elif phase in {CoursePhase.MARKER_BLUE, CoursePhase.MARKER_GREEN}:
            desired_heading = self.marker_navigation_desired_heading(
                self._marker_count,
                x,
                y,
            )
        else:
            desired_heading = (
                self.navigation_desired_heading(self._gate_count, x, y)
                if phase in {CoursePhase.APPROACH, CoursePhase.TURN, CoursePhase.CORRIDOR}
                else _heading_to_point(x, y, *target_waypoint)
            )
        if not gate_exit_active:
            self._gate_exit_origin = None
            self._gate_exit_heading_deg = None
        if (
            self._target_heading_deg is None
            or corridor_gate_staging_active
            or blind_turn_entry
            or blind_lane_capture_active
            or (gate_advanced and self._gate_count in (4, 5, 6))
            or (
            (gate_advanced and self._gate_count >= 9)
            or marker_advanced
            or dock_entry_alignment_active
            )
        ):
            # Keep normal smoothing through the course, but update the two
            # final legs immediately. Carrying Gate 9's old heading for several
            # frames makes the boat overshoot toward Gate 10's red buoy.
            self._target_heading_deg = desired_heading
        else:
            heading_delta = signed_heading_error(
                desired_heading,
                self._target_heading_deg,
            )
            max_step = self.config.heading_slew_deg_per_step
            self._target_heading_deg = normalize_heading(
                self._target_heading_deg
                + max(-max_step, min(max_step, heading_delta))
            )
        target_heading = self._target_heading_deg
        if heading_deg is None:
            return CourseDecision(
                phase=phase,
                steering_pwm=NEUTRAL_PWM,
                throttle_pwm=NEUTRAL_PWM,
                target_waypoint=target_waypoint,
                target_heading_deg=target_heading,
                heading_error_deg=0.0,
                gate_count=self._gate_count,
                marker_count=self._marker_count,
                target_speed_mps=0.0,
                waypoint_distance_m=math.hypot(target_waypoint[0] - x, target_waypoint[1] - y),
            )

        error = signed_heading_error(target_heading, heading_deg)
        derivative = 0.0
        if self._last_heading_error_deg is not None and self._last_control_time_s is not None:
            dt = max(0.01, now - self._last_control_time_s)
            error_delta = ((error - self._last_heading_error_deg + 180.0) % 360.0) - 180.0
            derivative = clamp(error_delta / dt, -90.0, 90.0)
        self._last_heading_error_deg = error
        self._last_control_time_s = now
        waypoint_distance = math.hypot(target_waypoint[0] - x, target_waypoint[1] - y)
        # Never start the blind pivot before the visible gate plane.  The
        # fixed outgoing heading is armed only by ``gate_advanced`` above;
        # this explicit false value keeps the later steering override from
        # reintroducing a pre-turn through a stale camera frame.
        blind_pre_turn_active = False
        # Extend the Gate 3 pivot only when the simulator/vehicle reports that
        # the hull is still rotating below the calibrated response target.  A
        # missing yaw-rate sample never turns this into an open-ended throttle
        # latch: the nominal burst and its hard maximum remain in force.
        measured_yaw_rate_dps: float | None = None
        if yaw_rate_dps is not None:
            try:
                candidate_yaw_rate = float(yaw_rate_dps)
            except (TypeError, ValueError):
                candidate_yaw_rate = float("nan")
            if math.isfinite(candidate_yaw_rate):
                measured_yaw_rate_dps = candidate_yaw_rate
        if (
            phase is CoursePhase.TURN
            and self._gate_count == 3
            and now >= self._blind_turn_kick_until_s
            and now < self._blind_pivot_max_until_s
            and abs(error) >= self.config.blind_pivot_error_deg
            and measured_yaw_rate_dps is not None
            and abs(measured_yaw_rate_dps)
            < self.config.blind_pivot_yaw_rate_target_dps
        ):
            self._blind_turn_kick_until_s = min(
                self._blind_pivot_max_until_s,
                now + self.config.blind_pivot_extension_step_s,
            )
        blind_pivot_active = (
            phase is CoursePhase.TURN
            and self._gate_count == 3
            and now >= self._course_turn_brake_until_s
            and now < self._blind_turn_kick_until_s
            and abs(error) >= self.config.blind_pivot_error_deg
        )
        target_speed = self._target_speed(phase, error)
        throttle_phase = phase
        pre_turn_gate = self._gate_count in (1, 2, 7, 8, 9)
        if pre_turn_gate:
            throttle_phase = CoursePhase.TURN
        if (
            pre_turn_gate
            and waypoint_distance <= self.gate_lookahead_distance(self._gate_count)
            and abs(error) >= 18.0
        ):
            target_speed = min(target_speed, self.config.turn_speed_mps)
        # Gate 4 is a narrow vertical pair.  Slow only while the hull is still
        # materially misaligned; once the sharp pivot has captured the fixed
        # blind bearing, let the straight leg use its normal forward speed.
        if (
            self._gate_count == 3
            and waypoint_distance <= 3.5
            and abs(error) > 25.0
        ):
            target_speed = min(target_speed, 0.38)
        if phase is CoursePhase.TURN and self._gate_count == 7:
            # Gate 8 is the first left slalom turn.  At the Gate-7 crossing
            # the hull can still carry a large north-west velocity; keep the
            # turn in a low-speed capture envelope until the heading error is
            # reduced, otherwise the stern thrust translates into the north
            # wall before the azimuth can swing through 90 degrees.
            if abs(error) >= 35.0:
                target_speed = min(
                    target_speed,
                    self.config.left_turn_capture_speed_mps,
                )
        if phase is CoursePhase.CORRIDOR:
            # Do not keep westbound thrust at full corridor speed while the
            # hull is outside the safe vertical-gate band.  The single
            # azimuth thruster needs a short low-speed window to recover from
            # the Gate-4 turn; otherwise it can arrive at the next gate on
            # the red-buoy line (y=9 m) and the front range sensor quite
            # correctly latches a stop.  The north-biased heading lead above
            # then brings the boat back to the 10.30 m centreline before the
            # next crossing.
            corridor_cross_track_m = abs(y - self.config.corridor_center_y_m)
            if corridor_cross_track_m > 0.35:
                target_speed = min(target_speed, 0.46)
            if corridor_cross_track_m > 0.75:
                target_speed = min(target_speed, 0.32)
        braking_distance = (max(0.0, speed_mps) ** 2) / (
            2.0 * self.config.braking_deceleration_mps2
        )
        stop_margin = (
            self.config.marker_stop_margin_m
            if phase in {
                CoursePhase.MARKER_BLUE,
                CoursePhase.MARKER_GREEN,
            }
            else self.config.waypoint_stop_margin_m
        )
        if waypoint_distance <= braking_distance + stop_margin:
            if phase is CoursePhase.DOCK:
                minimum_speed = 0.08
            elif phase in {
                CoursePhase.MARKER_BLUE,
                CoursePhase.MARKER_GREEN,
            }:
                minimum_speed = 0.06
            elif phase in {CoursePhase.DOCK_RETURN, CoursePhase.DOCK_APPROACH}:
                minimum_speed = 0.10
            else:
                # Do not carry full turn speed across the buoy line.  A
                # single stern thruster needs a small capture window to settle
                # on the midpoint, otherwise lateral inertia can put the hull
                # within the 0.40 m touch radius even when the crossing is
                # scored valid.
                minimum_speed = min(self.config.turn_speed_mps, 0.25)
            distance_scale = clamp(
                (waypoint_distance - 0.20) / max(0.1, braking_distance + stop_margin),
                0.0,
                1.0,
            )
            target_speed = min(target_speed, minimum_speed + (target_speed - minimum_speed) * distance_scale)
        dock_capture_active = (
            phase is CoursePhase.DOCK
            and waypoint_distance <= self.config.dock_capture_radius_m
        )
        if dock_capture_active:
            target_speed = (
                0.0
                if waypoint_distance <= self.config.dock_tolerance_m
                else self.config.dock_capture_speed_mps
            )
        throttle = self._speed_throttle(throttle_phase, target_speed, max(0.0, speed_mps))
        # Heading uncertainty is a hard throttle gate, not merely a lower
        # target speed.  With a single azimuth thruster, keeping 1560--1590
        # PWM while the bow is 60+ degrees off-course makes the boat translate
        # into the next buoy/wall before the yaw can catch up.  Let a moving
        # hull coast (or brake through the existing obstacle/turn logic) and
        # reserve only a tiny creep pulse for a nearly stationary hull.
        abs_heading_error = abs(error)
        # A sharp left pivot merely reveals the upper lane. It is not enough
        # to allow cruise: Gate 3 must be facing the blind-leg bearing and be
        # close to its projected centreline. A wider drift revokes permission.
        blind_lane_alignment_active = (
            phase is CoursePhase.TURN
            and self._gate_count == 3
            and now >= self._course_turn_brake_until_s
        )
        if blind_lane_alignment_active and blind_cross_track_m is not None:
            if self._blind_lane_aligned:
                if abs(blind_cross_track_m) > self.config.blind_lane_release_cross_track_m:
                    self._blind_lane_aligned = False
            elif (
                abs_heading_error <= self.config.blind_lane_heading_tolerance_deg
                and abs(blind_cross_track_m) <= self.config.blind_lane_cross_track_m
            ):
                self._blind_lane_aligned = True
        if abs_heading_error >= self.config.heading_hold_error_deg:
            target_speed = min(target_speed, self.config.heading_hold_speed_mps)
            throttle = (
                NEUTRAL_PWM
                if abs(float(speed_mps)) > self.config.heading_hold_speed_mps
                else self.config.heading_creep_pwm
            )
        elif abs_heading_error >= self.config.heading_slow_error_deg:
            target_speed = min(target_speed, self.config.heading_slow_speed_mps)
            throttle = (
                NEUTRAL_PWM
                if abs(float(speed_mps)) > self.config.heading_slow_speed_mps
                else min(throttle, self.config.heading_slow_pwm)
            )
        # In the upper corridor, coasting while the bow is misaligned is not
        # safe: the hull then carries its previous north/south velocity across
        # the next buoy line.  Keep a bounded low forward pulse while there is
        # measurable cross-track error so the azimuth can actually create yaw.
        # The pulse is removed on the centreline and remains below cruise
        # thrust; it is not a permanent full-throttle command.
        if (
            phase is CoursePhase.CORRIDOR
            and abs(y - self.config.corridor_center_y_m) >= 0.20
            and abs(float(speed_mps)) <= 0.65
            and ultrasonic is not None
        ):
            # A steady 1570-ish pulse is enough to let the azimuth create yaw
            # while preserving west/east progress.  The old 1680 Gate-6 kick
            # accelerated the hull into the side buoy and then the ultrasonic
            # clearance latch quite correctly held it there.
            pulse_pwm = self.config.corridor_pwm
            throttle = max(throttle, pulse_pwm)
            target_speed = max(
                target_speed,
                min(
                    self.config.corridor_speed_mps,
                    0.55,
                ),
            )
        # A blind corner is different from ordinary heading correction.  The
        # stern-mounted azimuth thruster cannot create a useful yaw moment
        # while it is only receiving the 1512/1524 creep command above.  That
        # was the reason the boat crossed Gate 3 and then kept drifting
        # north-east in the simulator even though the target heading was
        # already committed to the next gate.  Once the one-shot reverse
        # brake has finished, keep a bounded forward turn pulse until the
        # blind heading is captured.  It is still below the normal cruise
        # command, so this does not become a permanent "gas terus" mode.
        blind_turn_capture_active = (
            blind_turn_active
            and abs_heading_error >= self.config.turn_error_deg
            and not (
                phase is CoursePhase.TURN
                and self._gate_count == 3
                and now < self._course_turn_brake_until_s
            )
        )
        if blind_turn_capture_active:
            throttle = max(throttle, self.config.blind_turn_pwm)
        blind_lane_correction_active = (
            phase is CoursePhase.TURN
            and self._gate_count == 3
            and not self._blind_lane_aligned
            and now >= self._blind_turn_kick_until_s
        )
        if blind_lane_correction_active:
            # Keep enough thrust for azimuth yaw, but never cruise before the
            # path is centred between the next buoy pair.
            throttle = max(throttle, self.config.blind_turn_pwm)
            target_speed = min(target_speed, self.config.turn_speed_mps)
        blind_straight_active = (
            phase is CoursePhase.TURN
            and self._gate_count == 3
            and now >= self._blind_turn_kick_until_s
            and self._blind_lane_aligned
            and abs_heading_error <= self.config.blind_lane_heading_tolerance_deg
        )
        if blind_straight_active:
            # The pivot is over: run forward on the captured 309° centreline
            # instead of leaving the hull at a low creep command.
            throttle = max(throttle, self.config.max_forward_pwm)
            target_speed = max(target_speed, self.config.turn_speed_mps)
        if blind_entry_recovery_active:
            # The recovery target is a safety manoeuvre, not a new cruise
            # leg. Keep the hull slow enough for the azimuth to cancel the
            # northward drift before it reaches the buoy line.
            throttle = min(throttle, self.config.turn_pwm)
            target_speed = min(target_speed, self.config.turn_speed_mps)
        reverse_turn_active = (
            phase is CoursePhase.DOCK_RETURN
            and abs(error) >= self.config.reverse_turn_heading_error_deg
        )
        marker_reverse_turn_active = (
            phase is CoursePhase.MARKER_GREEN
            and abs(error) >= self.config.marker_reverse_turn_heading_error_deg
            # Only brake when the hull is actually at the green pass plane.
            # The previous unconditional heading test caused a long reverse
            # pulse while still several metres away, which looked like the
            # controller was confused and made the boat crawl.
            and waypoint_distance <= self.config.marker_stop_margin_m + 0.35
            and speed_mps >= 0.12
        )
        marker_reverse_brake_active = marker_reverse_turn_active
        left_turn_reverse_brake_active = (
            phase is CoursePhase.TURN
            and self._gate_count == 7
            and (
                blind_turn_entry
                or abs(error) >= self.config.left_turn_brake_error_deg
            )
            and speed_mps >= 0.18
        )
        if (
            phase is CoursePhase.TURN
            and self._gate_count in (3, 7)
            and not self._course_turn_brake_used
            and (
                blind_turn_entry
                or abs(error) >= self.config.course_turn_brake_error_deg
            )
            # Gate 3 is armed explicitly at the gate transition above.  Keep
            # this fallback for an unusually high-speed re-entry; Gate 7 uses
            # the same conditional brake for its top-corridor momentum.
            and (
                self._gate_count == 7
                or speed_mps >= max(self.config.course_turn_brake_speed_mps, 0.65)
            )
        ):
            self._course_turn_brake_used = True
            self._course_turn_brake_until_s = now + self.config.course_turn_brake_duration_s
            # Start the lateral capture kick after the reverse pulse rather
            # than letting the one-shot brake consume its entire window.
            self._blind_turn_kick_until_s = (
                self._course_turn_brake_until_s
                + self.config.blind_turn_kick_duration_s
            )
        course_turn_reverse_brake_active = (
            phase is CoursePhase.TURN
            and self._gate_count == 3
            and now < self._course_turn_brake_until_s
        )
        blind_turn_kick_active = (
            phase is CoursePhase.TURN
            and self._gate_count == 7
            and now < self._blind_turn_kick_until_s
            and not course_turn_reverse_brake_active
        )
        dock_alignment_reverse_active = (
            phase is CoursePhase.DOCK_APPROACH
            and dock_entry_alignment_active
            and abs(error) >= self.config.dock_entry_alignment_error_deg
        )
        if reverse_turn_active or dock_alignment_reverse_active:
            # The green marker sits close to the south wall.  If the hull
            # still has a large exit-heading error, use the reversible
            # azimuth thruster to remove that momentum before travelling to
            # the next leg.  The same bounded manoeuvre aligns the hull at
            # the dock entry rather than allowing it to slide sideways.
            throttle = self.config.reverse_turn_pwm
            target_speed = 0.0
        elif marker_reverse_turn_active:
            # At the blue-to-green transition the hull still has southbound
            # momentum. A straight reverse brake removes that momentum without
            # the lateral kick produced by mirroring the azimuth on this
            # physical thruster model; heading correction resumes once speed
            # falls below the guard above.
            throttle = self.config.reverse_brake_pwm
            target_speed = 0.0
        elif left_turn_reverse_brake_active:
            # Brake the incoming Gate-7 momentum before asking the azimuth to
            # make the large left turn.  Steering is neutralised below during
            # this reverse pulse so the reversible thrust only removes speed.
            throttle = self.config.left_turn_brake_pwm
            target_speed = 0.0
        elif course_turn_reverse_brake_active:
            # Gate 4 is the first 90-degree turn into the narrow top corridor.
            # If the bow is still more than a half-turn quadrant away while it
            # is translating, a forward pulse carries the hull to the north
            # wall before the azimuth can swing. One bounded reverse pulse
            # both removes momentum and gives the stern-mounted azimuth a
            # stronger yaw moment; reverse steering is mirrored below so the
            # rotation continues toward the requested heading.
            throttle = self.config.course_turn_brake_pwm
            target_speed = 0.0
            if self._gate_count == 3:
                avoidance_reason = "BLIND_LEFT_BRAKE"
        dock_turn_boost_active = (
            phase is CoursePhase.DOCK_APPROACH
            and not dock_alignment_reverse_active
            and abs(error) >= self.config.dock_turn_error_deg
            and speed_mps <= self.config.dock_turn_speed_ceiling_mps
        )
        if dock_turn_boost_active:
            # A low creep command cannot generate enough stern moment to
            # pull a 9.5 kg monohull onto the narrow dock-entry line.  This
            # short, bounded boost adds yaw authority only while it is slow
            # and still materially misaligned; normal approach speed resumes
            # immediately once the error is reduced.
            throttle = max(throttle, self.config.dock_turn_pwm)
        docking_phase = phase in {
            CoursePhase.DOCK_RETURN,
            CoursePhase.DOCK_APPROACH,
            CoursePhase.DOCK,
        }
        steering_gain = (
            self.config.corridor_steering_gain
            if phase is CoursePhase.CORRIDOR
            else self.config.heading_control_gain
        )
        # Short S-turn legs need more azimuth authority to cancel momentum
        # from the previous leg. Keep the stronger gain local to the slalom;
        # the top corridor and vertical-gate turn retain the gentle base gain
        # so a small heading error cannot saturate the servo.
        if phase is CoursePhase.APPROACH and self._gate_count in (1, 2, 7, 8, 9):
            steering_gain = self.config.slalom_heading_gain
        if docking_phase:
            steering_gain = 1.6
        # The derivative term is useful in the buoy slalom, but a slow
        # single-thruster hull keeps rotating after a large transient.  A
        # bounded proportional-only command is more predictable in the
        # lower-basin return and final entry.
        steering_error = error if docking_phase else error + self.config.heading_derivative_damping_s * derivative
        steering_limit = (
            self.config.dock_steering_max_delta
            if docking_phase
            else self.config.max_steering_delta
        )
        steering = compute_heading_steering_pwm(
            steering_error * steering_gain,
            max_delta=steering_limit,
        )
        # The Webots thruster/steering sign is opposite to the compass
        # convention used by the route planner: 1100 is the physical left
        # impulse in Arena A (1900 is right).  The blind leg must therefore
        # use the calibrated body-frame command, while Arena B remains a
        # mirror of Arena A.
        blind_lateral_steering = 1100 if self._arena == "A" else 1900
        # This is deliberately a short peek only.  Once the pre-turn/kick
        # timer expires, the heading controller (and then the visual layer)
        # is allowed to straighten the hull instead of continuing to force a
        # left arc all the way to Gate 4's x-line.
        if blind_pivot_active:
            steering = blind_lateral_steering
            pivot_throttle = self.config.blind_pivot_pwm
            if self._gate_count == 3:
                gate_center_x = self.waypoints[2][0]
                green_side_offset_m = (
                    (x - gate_center_x)
                    if self._arena == "A"
                    else (gate_center_x - x)
                )
                if green_side_offset_m > self.config.blind_pivot_green_side_margin_m:
                    pivot_throttle = min(
                        pivot_throttle,
                        self.config.blind_turn_kick_pwm,
                    )
            throttle = max(throttle, pivot_throttle)
            avoidance_reason = "BLIND_LEFT_PIVOT"
        elif blind_pre_turn_active or blind_turn_kick_active:
            steering = blind_lateral_steering
            throttle = max(throttle, self.config.blind_turn_kick_pwm)
            if blind_turn_kick_active:
                avoidance_reason = "BLIND_LEFT_PIVOT"
        # ``sonar`` remains accepted as a deprecated keyword so saved scripts
        # continue to run while the project adopts the accurate terminology.
        ultrasonic_readings = ultrasonic if ultrasonic is not None else sonar
        sensor_values_for_gate = self._ultrasonic_readings(ultrasonic_readings)
        # Pass the buoy pair through its centre only in the last ~2.25 m of a
        # blind turn.  The 0.18 m front floor is the sensor-surface margin for
        # the 0.40 m buoy-touch radius; a nearer return remains an emergency
        # stop.  Outside this window the normal ultrasonic stop is unchanged.
        gate_center_pass_active = (
            phase is CoursePhase.TURN
            and self._gate_count in (3, 7)
            and waypoint_distance <= 2.25
            and not (
                self._gate_count == 3
                and y < COURSE_BLIND_STAGING_RELEASE_Y_A[3]
            )
            # Gate 4's expected buoy return can be below the ordinary front
            # stop threshold while the hull is still centred between y=9 and
            # y=11.  Allow the bounded pass down to the sensor floor; the
            # position/heading envelope remains active and any return outside
            # it still invokes the normal ultrasonic stop.
            and sensor_values_for_gate["front"] >= 0.05
        )
        avoidance_delta, throttle_cap, ultrasonic_min, avoidance_reason = (
            self._obstacle_adjustment(
                ultrasonic_readings,
                speed_mps=speed_mps,
                now_s=now,
                gate_center_pass=gate_center_pass_active,
            )
        )
        # The deterministic blind manoeuvre owns the azimuth for these
        # bounded windows.  Preserve its reason even when an ultrasonic side
        # ray also reports a nearby buoy; otherwise the vision layer can
        # mistake that secondary reason for permission to trim the pivot.
        if blind_pivot_active:
            avoidance_reason = "BLIND_LEFT_PIVOT"
        elif course_turn_reverse_brake_active:
            avoidance_reason = "BLIND_LEFT_BRAKE"
        elif blind_turn_kick_active:
            avoidance_reason = "BLIND_LEFT_PIVOT"
        elif blind_entry_recovery_active:
            avoidance_reason = "BLIND_ENTRY_RECOVERY"
        if corridor_recenter_brake_active:
            steering = NEUTRAL_PWM
            throttle = self.config.course_turn_brake_pwm
            target_speed = 0.0
            avoidance_reason = "CORRIDOR_CENTER_BRAKE"
        elif corridor_recenter_kick_active:
            throttle = max(throttle, self.config.turn_pwm)
            target_speed = max(target_speed, self.config.turn_speed_mps)
            avoidance_reason = "CORRIDOR_CENTER_KICK"
        # No one-sided north recapture is needed here.  It fought the direct
        # midpoint bearing whenever the hull stopped near y=10.2 and could
        # turn a harmless correction into a side-clearance latch.  If the
        # legacy recenter timers are ever populated by an old caller, the
        # bounded brake/kick branches above still remain deterministic.
        steering = int(
            round(
                clamp(
                    steering + avoidance_delta,
                    NEUTRAL_PWM - self.config.max_steering_delta,
                    NEUTRAL_PWM + self.config.max_steering_delta,
                )
            )
        )
        if throttle_cap is not None:
            throttle = min(throttle, throttle_cap)
            if throttle <= NEUTRAL_PWM:
                target_speed = 0.0
        if avoidance_reason == "ULTRASONIC_SIDE_CLEARANCE":
            # Side-range avoidance owns the escape envelope.  Do not let the
            # corridor recapture pulse press the hull harder into a buoy that
            # is already inside the lateral clearance radius.
            throttle = min(throttle, self.config.ultrasonic_escape_pwm)
        if gate_center_pass_active:
            # Keep a bounded positive creep so the azimuth can translate the
            # hull through the opening.  The override ends as soon as the
            # scorer advances to the next gate or the 0.18 m safety floor is
            # reached; it is not a cruise/throttle latch.
            throttle = max(throttle, self.config.blind_turn_pwm)
            target_speed = max(target_speed, self.config.turn_speed_mps)
            if not avoidance_reason:
                avoidance_reason = "GATE_CENTER_PASS"
        # Once the one-shot left pivot has finished, the fixed blind heading
        # itself is the centreline.  Do not reapply a second hard-left command
        # near x=6: that old staging override was the source of the boat
        # continuing to turn instead of travelling through the opening.
        gate4_crossing_active = (
            phase is CoursePhase.TURN
            and self._gate_count == 3
            and x > 6.0
            and 9.25 <= y <= 10.90
            and gate_center_pass_active
        )
        if gate4_crossing_active:
            # Keep forward thrust through the physical opening.  Leave the
            # bounded heading controller in charge of small counter-steering
            # corrections; forcing neutral here lets residual yaw carry the
            # hull toward the upper buoy before it reaches x=6.
            throttle = max(throttle, self.config.blind_turn_pwm)
            target_speed = max(target_speed, self.config.turn_speed_mps)
            avoidance_reason = "GATE4_STRAIGHT"
        gate_four = self.waypoints[3]
        gate_four_approach_offset_m = (
            (x - gate_four[0])
            if self._arena == "A"
            else (gate_four[0] - x)
        )
        blind_green_clearance_active = (
            phase is CoursePhase.TURN
            and self._gate_count == 3
            and -0.25 <= gate_four_approach_offset_m
            <= self.config.blind_green_clearance_start_m
            and y >= (
                self.config.corridor_center_y_m
                + self.config.blind_green_clearance_y_margin_m
            )
        )
        if blind_green_clearance_active:
            # At the recorded failure point the hull was already pointing
            # southwest, which is the safe escape vector for Arena A (and its
            # mirrored equivalent in Arena B).  Reasserting hard-left here
            # made the stern azimuth crab west while the bow stayed beside the
            # green buoy.  Neutral steering preserves the captured heading;
            # the bounded pulse supplies only enough thrust to cross the
            # vertical opening before normal corridor control resumes.
            steering = NEUTRAL_PWM
            throttle = self.config.blind_green_clearance_pwm
            target_speed = min(target_speed, self.config.turn_speed_mps)
            avoidance_reason = "BLIND_GREEN_CLEARANCE"
        # Once Gate 4 is scored, the normal midpoint heading controller owns
        # the westbound corridor.  There is no special hard-steer or reverse
        # latch here: the bounded cross-track correction above is what keeps
        # the hull between the red and green rows.
        sensor_values = self._ultrasonic_readings(
            ultrasonic if ultrasonic is not None else sonar
        )
        forward_clear = min(
            sensor_values["front_left"],
            sensor_values["front"],
            sensor_values["front_right"],
        ) >= self.config.ultrasonic_slow_distance_m
        side_obstacle = min(sensor_values["left"], sensor_values["right"]) < (
            self.config.ultrasonic_side_clearance_m
        )
        # Once the reverse brake pulse has finished, a stationary hull still
        # needs enough thrust to generate yaw.  Permit a bounded turn pulse
        # only when the ultrasonic envelope is clear; this is not a cruise
        # command and is suppressed again as soon as the hull accelerates.
        heading_pivot_active = (
            phase is CoursePhase.TURN
            and (
                abs_heading_error >= self.config.heading_hold_error_deg
                or (
                    blind_turn_active
                    and abs_heading_error >= self.config.turn_error_deg
                )
            )
            and abs(float(speed_mps)) <= self.config.heading_hold_speed_mps + 0.05
            and ultrasonic_min >= self.config.ultrasonic_slow_distance_m
            and not course_turn_reverse_brake_active
            and not left_turn_reverse_brake_active
            and not reverse_turn_active
            and not dock_alignment_reverse_active
        )
        if heading_pivot_active:
            throttle = max(throttle, self.config.turn_pwm)
        side_escape_active = (
            phase is CoursePhase.TURN
            and abs_heading_error >= self.config.heading_hold_error_deg
            and abs(float(speed_mps)) <= self.config.heading_hold_speed_mps + 0.05
            and forward_clear
            and side_obstacle
            and not course_turn_reverse_brake_active
            and not left_turn_reverse_brake_active
            and not reverse_turn_active
            and not dock_alignment_reverse_active
        )
        if side_escape_active:
            # A buoy on the side is not a reason to coast forever: with the
            # bow clear, a short turn pulse translates the hull away from that
            # side. The speed gate removes the pulse again once the hull moves.
            throttle = max(throttle, self.config.turn_pwm)
        # The Webots wall is a physical body, while the five ultrasonic rays
        # can miss a shallow corner approach. Keep a GPS/geofence backup in
        # the lower basin so a momentum overshoot cannot turn into a south-wall
        # contact. The final DOCK phase is exempt because its target is
        # intentionally near the south boundary.
        south_boundary_recovery = (
            phase is not CoursePhase.DOCK
            and phase is not CoursePhase.DOCK_RETURN
            and self._gate_count >= len(self.waypoints)
            and y <= COURSE_SOUTH_RECOVERY_Y_M
        )
        if south_boundary_recovery and heading_deg is not None:
            recovery_heading = 45.0 if self._arena == "A" else 315.0
            recovery_error = signed_heading_error(recovery_heading, heading_deg)
            steering = compute_heading_steering_pwm(
                recovery_error * 1.6,
                max_delta=self.config.dock_steering_max_delta,
            )
            throttle = self.config.reverse_turn_pwm
            target_speed = 0.0
            avoidance_reason = "BOUNDARY_SOUTH_RECOVERY"
            ultrasonic_min = min(ultrasonic_min, max(0.05, COURSE_WALL_LIMIT_Y_M + y))
        lateral_boundary_recovery = (
            phase is not CoursePhase.DOCK
            and self._gate_count >= len(self.waypoints)
            and (
                (self._arena == "A" and x <= COURSE_LATERAL_RECOVERY_X_A)
                or (self._arena == "B" and x >= 2.0 * COURSE_ARENA_MIRROR_X - COURSE_LATERAL_RECOVERY_X_A)
            )
        )
        if lateral_boundary_recovery and heading_deg is not None:
            # Arena A's lower return basin must move east away from the west
            # wall; Arena B is the mirrored westbound manoeuvre. Preserve the
            # commanded azimuth during reverse so the escape turn is not
            # accidentally mirrored a second time by the negative throttle.
            recovery_heading = 90.0 if self._arena == "A" else 270.0
            recovery_error = signed_heading_error(recovery_heading, heading_deg)
            steering = compute_heading_steering_pwm(
                recovery_error * 1.8,
                max_delta=self.config.dock_steering_max_delta,
            )
            throttle = self.config.reverse_turn_pwm
            target_speed = 0.0
            avoidance_reason = "BOUNDARY_LATERAL_RECOVERY"
            ultrasonic_min = min(ultrasonic_min, max(0.05, abs(COURSE_LATERAL_RECOVERY_X_A - x)))
        if dock_capture_active and target_speed > 0.0:
            throttle = min(throttle, self.config.dock_creep_pwm)
        if phase is CoursePhase.DOCK and waypoint_distance <= self.config.dock_tolerance_m:
            # A single thruster cannot yaw in place without translating the
            # hull. Coast inside the capture circle instead of chasing heading.
            throttle = NEUTRAL_PWM
            target_speed = 0.0
            if abs(error) <= self.config.dock_heading_tolerance_deg:
                steering = NEUTRAL_PWM
        reverse_escape_active = avoidance_reason == "ULTRASONIC_REVERSE_ESCAPE"
        preserve_reverse_steering = (
            avoidance_reason.startswith("BOUNDARY_")
        )
        if throttle < NEUTRAL_PWM:
            # A negative force at the stern reverses the yaw moment generated
            # by an azimuth angle. Mirror the commanded azimuth so a reverse
            # brake/turn continues rotating toward, rather than away from,
            # the requested heading.
            if (
                marker_reverse_brake_active
                or left_turn_reverse_brake_active
                or reverse_escape_active
            ):
                steering = NEUTRAL_PWM
            elif not preserve_reverse_steering:
                steering = int(
                    round(
                        clamp(
                            (2 * NEUTRAL_PWM) - steering,
                            NEUTRAL_PWM - self.config.max_steering_delta,
                            NEUTRAL_PWM + self.config.max_steering_delta,
                        )
                    )
                )
        return CourseDecision(
            phase=phase,
            steering_pwm=steering,
            throttle_pwm=throttle,
            target_waypoint=target_waypoint,
            target_heading_deg=target_heading,
            heading_error_deg=error,
            gate_count=self._gate_count,
            marker_count=self._marker_count,
            target_speed_mps=target_speed,
            waypoint_distance_m=waypoint_distance,
            ultrasonic_min_m=ultrasonic_min,
            obstacle_avoidance=bool(avoidance_reason),
            avoidance_reason=avoidance_reason,
        )
