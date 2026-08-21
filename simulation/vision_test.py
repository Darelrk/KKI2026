"""YOLO gate perception plus MAVLink control for hardware and Webots.

In simulator mode, ``CourseAutopilot`` runs heading/speed control at 20 Hz,
uses fresh red-green pairs for bounded local gate centering, and gives obstacle
priority to the five ultrasonic channels.  The inference/UI loop may run more
slowly without starving RC overrides.  The script never arms the vehicle.

When simulator ``gate_count`` telemetry is unavailable, ``--sensor-only`` uses
local GPS gate-plane crossing and the same camera/ultrasonic layers as a real
hardware run.
"""

from __future__ import annotations

import argparse
import math
import json
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from vision_route import (
    CourseDecision,
    CoursePhase,
    CourseRouteConfig,
    CourseRouteController,
    Detection,
    GateFeature,
    GateTracker,
    NEUTRAL_PWM,
    PWM_MAX,
    PWM_MIN,
    ThrottleConfig,
    VisualTargetTracker,
    VisualThrottleController,
    VisualSearchController,
    VisualGateCentering,
    VisualGateCorrection,
    VisualGateCorrectionConfig,
    SearchConfig,
    ccw,
    clamp,
    compute_sector_target_heading,
    max_buoy_area_ratio,
    PatternMatcher,
    PatternSignature,
    RouteConfig,
    RouteController,
    RouteDecision,
    RouteState,
    STEERING_MAX_DELTA,
    compute_steering_pwm,
)
from asv_dashboard_backend.vision_publisher import BridgeFramePublisher


# The trained YOLO model intentionally remains a buoy detector.  The floating
# marker boxes are large, mostly planar colour patches and are better handled
# by a lightweight geometric detector than by silently treating them as buoys.
MARKER_DETECTION_LABELS = frozenset({"blue_marker", "green_marker"})
_MARKER_HSV_RANGES: tuple[tuple[str, tuple[int, int, int], tuple[int, int, int]], ...] = (
    # OpenCV HSV hue is 0..179.  The high saturation threshold keeps the blue
    # box separate from the Webots water/background, which is a paler blue.
    ("blue_marker", (98, 145, 35), (132, 255, 255)),
    ("green_marker", (38, 105, 35), (88, 255, 255)),
)


def detect_marker_boxes(
    frame: Any,
    *,
    min_area_ratio: float = 0.0012,
    max_area_ratio: float = 0.22,
) -> list[Detection]:
    """Detect blue/green floating boxes from one BGR camera frame.

    ``best.pt`` has no marker classes, so this deliberately does not call the
    neural model.  It segments the distinctive marker colour and then keeps
    contours that look like a rectangle rather than a buoy (minimum aspect
    ratio, rectangularity and solidity).  The result uses the existing
    :class:`Detection` shape so it can be logged, drawn and consumed by the
    course controller without changing the buoy matcher.

    The detector is conservative: no candidate is returned when the frame is
    too small or a colour region touches the image border (usually the water or
    wall background).  ``confidence`` is a geometric quality score, not a
    probability from YOLO.
    """

    if frame is None or getattr(frame, "ndim", 0) < 2:
        return []
    height, width = frame.shape[:2]
    if width <= 0 or height <= 0:
        return []
    if not 0.0 < min_area_ratio < max_area_ratio <= 1.0:
        raise ValueError("marker area ratios must satisfy 0 < min < max <= 1")

    import cv2
    import numpy as np

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    frame_area = float(width * height)
    min_area = max(40.0, frame_area * float(min_area_ratio))
    max_area = frame_area * float(max_area_ratio)
    # A small opening removes single-pixel model/camera noise; closing joins
    # anti-aliased edges of a marker into one connected rectangle.
    kernel = np.ones((3, 3), dtype=np.uint8)
    detections: list[Detection] = []

    for label, lower, upper in _MARKER_HSV_RANGES:
        mask = cv2.inRange(
            hsv,
            np.asarray(lower, dtype=np.uint8),
            np.asarray(upper, dtype=np.uint8),
        )
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        candidates: list[tuple[float, Detection]] = []
        for contour in contours:
            contour_area = float(cv2.contourArea(contour))
            if contour_area < min_area or contour_area > max_area:
                continue
            x, y, box_width, box_height = cv2.boundingRect(contour)
            # Border-connected regions are commonly the pool/wall background,
            # not a floating marker.  Keeping a one-pixel margin also avoids
            # an unstable bounding box while the target enters the image.
            if x <= 0 or y <= 0 or x + box_width >= width - 1 or y + box_height >= height - 1:
                continue
            rotated = cv2.minAreaRect(contour)
            rotated_width, rotated_height = rotated[1]
            short_side = min(rotated_width, rotated_height)
            long_side = max(rotated_width, rotated_height)
            if short_side < max(5.0, min(width, height) * 0.012):
                continue
            aspect_ratio = long_side / max(short_side, 1e-6)
            # A buoy/ellipse tends to have an aspect ratio close to 1.0;
            # perspective-distorted marker rectangles in this arena remain
            # wider than 1.35 even at the far end of the course.
            if not 1.35 <= aspect_ratio <= 8.0:
                continue
            rotated_area = max(rotated_width * rotated_height, 1.0)
            rectangularity = contour_area / rotated_area
            hull_area = max(float(cv2.contourArea(cv2.convexHull(contour))), 1.0)
            solidity = contour_area / hull_area
            bbox_fill = contour_area / max(float(box_width * box_height), 1.0)
            # Perspective, the box shadow and water gaps can reduce solidity
            # below a perfect rectangle; buoy blobs still fail the aspect and
            # bounding-box tests above.
            if rectangularity < 0.52 or solidity < 0.65 or bbox_fill < 0.40:
                continue

            area_ratio = contour_area / frame_area
            # This score is only used for ranking and telemetry.  It combines
            # shape quality with visible size and is intentionally capped.
            quality = clamp(
                0.45
                + 0.25 * clamp(rectangularity, 0.0, 1.0)
                + 0.20 * clamp(solidity, 0.0, 1.0)
                + 0.10 * clamp(area_ratio / 0.02, 0.0, 1.0),
                0.0,
                0.99,
            )
            detection = Detection(
                label=label,
                confidence=float(quality),
                x_center=float(x + box_width / 2.0),
                y_center=float(y + box_height / 2.0),
                width=float(box_width),
                height=float(box_height),
            )
            candidates.append((contour_area, detection))

        # Only the largest plausible region of each marker colour is used for
        # steering.  Other coloured regions (for example a distant buoy) stay
        # out of the obstacle channel and cannot make the boat oscillate.
        if candidates:
            detections.append(max(candidates, key=lambda item: item[0])[1])

    return detections


def vfr_hud_heading(message: Any) -> float | None:
    """Return normalized heading from one MAVLink VFR_HUD message."""
    value = getattr(message, "heading", None)
    if value is None:
        return None
    return float(value) % 360.0




def _result_label(result: Any, class_index: int) -> str:
    names = result.names
    if isinstance(names, dict):
        return str(names.get(class_index, class_index))
    return str(names[class_index])


def detections_from_result(result: Any) -> list[Detection]:
    """Convert one Ultralytics result into project Detection objects."""
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return []

    xyxy = boxes.xyxy.cpu().numpy()
    confidences = boxes.conf.cpu().numpy()
    class_ids = boxes.cls.cpu().numpy().astype(int)
    detections: list[Detection] = []

    for (x1, y1, x2, y2), confidence, class_id in zip(
        xyxy, confidences, class_ids
    ):
        detections.append(
            Detection(
                label=_result_label(result, int(class_id)),
                confidence=float(confidence),
                x_center=float((x1 + x2) / 2.0),
                y_center=float((y1 + y2) / 2.0),
                width=float(x2 - x1),
                height=float(y2 - y1),
            )
        )
    return detections


@dataclass(frozen=True)
class CapturedFrame:
    frame: Any
    frame_id: int
    captured_at: datetime


class LatestFrameQueue:
    """Bounded handoff that always exposes the newest captured frame."""

    def __init__(self) -> None:
        self._items: deque[CapturedFrame] = deque(maxlen=1)
        self._condition = threading.Condition()
        self._closed = False

    def put_latest(self, item: CapturedFrame) -> None:
        with self._condition:
            if self._closed:
                return
            self._items.clear()
            self._items.append(item)
            self._condition.notify()

    def get(self, timeout: float | None = None) -> CapturedFrame | None:
        with self._condition:
            deadline = None if timeout is None else time.monotonic() + timeout
            while not self._items and not self._closed:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._condition.wait(remaining)
            if self._items:
                return self._items.popleft()
            return None

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


def detection_metadata_from_result(
    detections: Sequence[Detection],
    *,
    asv_id: str,
    frame_id: int,
    captured_at: datetime,
    source_width: int,
    source_height: int,
) -> dict[str, Any]:
    if source_width <= 0 or source_height <= 0:
        raise ValueError("source dimensions must be positive")

    formatted_detections: list[dict[str, Any]] = []
    for detection in detections:
        raw_x = (detection.x_center - detection.width / 2.0) / source_width
        raw_y = (detection.y_center - detection.height / 2.0) / source_height
        raw_w = detection.width / source_width
        raw_h = detection.height / source_height

        x = max(0.0, min(1.0, raw_x))
        y = max(0.0, min(1.0, raw_y))
        width = max(0.0, min(1.0 - x, raw_w))
        height = max(0.0, min(1.0 - y, raw_h))

        if width <= 0.0 or height <= 0.0:
            continue

        formatted_detections.append(
            {
                "track_id": None,
                "label": detection.label,
                "confidence": detection.confidence,
                "x": round(x, 6),
                "y": round(y, 6),
                "width": round(width, 6),
                "height": round(height, 6),
            }
        )

    return {
        "schema_version": 1,
        "asv_id": asv_id,
        "frame_id": frame_id,
        "captured_at": captured_at.isoformat(),
        "source_width": source_width,
        "source_height": source_height,
        "detections": formatted_detections,
    }


class JsonlLogger:
    """Append one valid JSON object per line for crash-safe telemetry logs."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8")

    def write(self, record: dict[str, Any]) -> None:
        json.dump(record, self._file, ensure_ascii=False, separators=(",", ":"))
        self._file.write("\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def resolve_pixhawk_endpoint(endpoint: str) -> str:
    """Auto-detect Pixhawk serial device if the specified endpoint does not exist."""
    if endpoint.startswith("tcp:") or endpoint.startswith("udp:"):
        return endpoint

    import sys
    if sys.platform == "win32":
        if endpoint.upper().startswith("COM"):
            return endpoint.upper()
        if endpoint.startswith("/dev/"):
            return "COM5"
        try:
            import serial.tools.list_ports
            ports = list(serial.tools.list_ports.comports())
            for p in ports:
                desc = (p.description or "").lower()
                if any(k in desc for k in ["pixhawk", "ardupilot", "px4", "stm", "ch340", "silicon"]):
                    return p.device
            if ports:
                return ports[0].device
        except Exception:
            pass
        return "COM5"
    import glob
    if Path(endpoint).exists():
        return endpoint
    by_id = glob.glob("/dev/serial/by-id/*ArduPilot*") + glob.glob("/dev/serial/by-id/*Pixhawk*")
    if by_id:
        return by_id[0]
    for candidate in ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyUSB0", "/dev/ttyUSB1"]:
        if Path(candidate).exists():
            return candidate
    return endpoint
class PixhawkLink:
    """Minimal MAVLink connection for ArduRover RC overrides.

    ``origin_lat``/``origin_lon`` define the local ENU frame consumed by the
    course controller. The simulator uses its fixed origin by default; a
    real deployment should set these to the surveyed course reference point.
    """
    def __init__(
        self,
        endpoint: str,
        heartbeat_timeout: float = 5.0,
        *,
        origin_lat: float = -6.200000,
        origin_lon: float = 106.816666,
    ) -> None:
        try:
            from pymavlink import mavutil
            import serial
        except ImportError as exc:
            raise RuntimeError(
                "Dependensi MAVLink serial belum lengkap. Jalankan: "
                "python -m pip install pymavlink pyserial"
            ) from exc
        self._mavutil = mavutil
        self._endpoint = endpoint
        self._heartbeat_timeout = heartbeat_timeout
        self._origin_lat = float(origin_lat)
        self._origin_lon = float(origin_lon)
        self.connection = None
        self._lock = threading.Lock()
        self._mav_lock = threading.RLock()
        self._target_steering = NEUTRAL_PWM
        self._target_throttle = NEUTRAL_PWM
        self._override_active = False
        self._running = True
        self._last_servo_output = None
        self._last_rc_channels = None
        self._last_vfr_hud = None
        self._last_global_pos = None
        self._last_heading_update_s = 0.0
        self._last_position_update_s = 0.0
        self._last_gate_count: int | None = None
        self._last_marker_count: int | None = None
        self._last_arena_id: int | None = None
        self._last_ultrasonic: dict[str, float] = {
            "front_left": 5.0,
            "front": 5.0,
            "front_right": 5.0,
            "left": 5.0,
            "right": 5.0,
        }
        self._last_yaw_rate_dps: float | None = None
        self._last_azimuth_angle_deg: float | None = None

        with self._mav_lock:
            connected = self._try_connect(endpoint)

        if not connected or self.connection is None:
            raise TimeoutError(
                f"Tidak menerima heartbeat Pixhawk dari {endpoint}. "
                "Pastikan Pixhawk terhubung dan port tidak dikunci oleh QGroundControl/Mission Planner."
            )

        self._stream_thread = threading.Thread(target=self._override_loop, daemon=True)
        self._stream_thread.start()

    def _try_connect(self, endpoint: str) -> bool:
        """Internal helper to connect to Pixhawk endpoints under _mav_lock."""
        resolved_endpoint = resolve_pixhawk_endpoint(endpoint)
        endpoints_to_try = [resolved_endpoint]
        import sys
        if sys.platform == "win32":
            for com in ["COM5", "COM3", "COM4", "COM6", "COM7", "COM8"]:
                if com not in endpoints_to_try:
                    endpoints_to_try.append(com)
        else:
            for alt in ["/dev/ttyACM1", "/dev/ttyACM0", "/dev/ttyUSB0", "/dev/ttyUSB1"]:
                if alt not in endpoints_to_try and Path(alt).exists():
                    endpoints_to_try.append(alt)

        for ep in endpoints_to_try:
            for baud in [115200, 57600, 38400, 9600]:
                conn = None
                try:
                    conn = self._mavutil.mavlink_connection(
                        ep,
                        baud=baud,
                        source_system=255,
                        source_component=190,
                    )
                    hb = conn.wait_heartbeat(timeout=2.5)
                    if hb is not None:
                        if getattr(self, "connection", None) is not None:
                            try:
                                self.connection.close()
                            except Exception:
                                pass
                        self.connection = conn
                        self._last_heartbeat = hb
                        self._last_heartbeat_time = time.monotonic()
                        print(
                            f"Pixhawk terhubung: endpoint={ep} ({baud} baud), system={conn.target_system}, "
                            f"component={conn.target_component}, mode={str(conn.flightmode or 'UNKNOWN').upper()}"
                        )
                        return True
                except Exception as exc:
                    print(f"Percobaan {ep} ({baud} baud) -> {exc}")
                finally:
                    if conn is not None and getattr(self, "connection", None) != conn:
                        try:
                            conn.close()
                        except Exception:
                            pass

    def reconnect(self) -> bool:
        """Attempt to recover lost Pixhawk connection dynamically."""
        with self._mav_lock:
            print(f"Mencoba menyambungkan ulang MAVLink ke {self._endpoint}...")
            return self._try_connect(self._endpoint)

    def mode(self) -> str:
        """Read and cache the latest heartbeat mode."""
        if self.connection is None:
            return "UNKNOWN"
        with self._mav_lock:
            try:
                heartbeat = self.connection.recv_match(
                    type="HEARTBEAT", blocking=False, timeout=0.01
                )
                if heartbeat is not None:
                    self._last_heartbeat = heartbeat
                    self._last_heartbeat_time = time.monotonic()
            except Exception:
                pass
            return str(self.connection.flightmode or "UNKNOWN").upper()

    def is_manual(self) -> bool:
        return self.mode() == "MANUAL"

    def telemetry(self) -> dict[str, Any]:
        """Return latest ArduPilot heartbeat, RC input, and PWM output."""
        if self.connection is None:
            return {
                "mode": "UNKNOWN",
                "armed": False,
                "base_mode": None,
                "system_status": None,
                "heading_deg": None,
                "rc1": None,
                "rc3": None,
                "servo1": None,
                "servo3": None,
                "arena": None,
                "marker_count": None,
                "ultrasonic": dict(self._last_ultrasonic),
                "sonar": dict(self._last_ultrasonic),
                "yaw_rate_dps": self._last_yaw_rate_dps,
                "azimuth_angle_deg": self._last_azimuth_angle_deg,
                "telemetry_age_s": float("inf"),
                "position_age_s": float("inf"),
                "heading_age_s": float("inf"),
            }
        with self._mav_lock:
            try:
                while True:
                    message = self.connection.recv_match(
                        type=[
                            "HEARTBEAT",
                            "RC_CHANNELS",
                            "SERVO_OUTPUT_RAW",
                            "VFR_HUD",
                            "GLOBAL_POSITION_INT",
                            "NAMED_VALUE_INT",
                            "NAMED_VALUE_FLOAT",
                        ],
                        blocking=False,
                    )
                    if message is None:
                        break
                    message_type = message.get_type()
                    if message_type == "HEARTBEAT":
                        self._last_heartbeat = message
                        self._last_heartbeat_time = time.monotonic()
                    elif message_type == "RC_CHANNELS":
                        self._last_rc_channels = message
                    elif message_type == "SERVO_OUTPUT_RAW":
                        self._last_servo_output = message
                    elif message_type == "VFR_HUD":
                        self._last_vfr_hud = message
                        self._last_heading_update_s = time.monotonic()
                    elif message_type == "GLOBAL_POSITION_INT":
                        self._last_global_pos = message
                        self._last_position_update_s = time.monotonic()
                    elif message_type == "NAMED_VALUE_INT":
                        raw_name = getattr(message, "name", b"")
                        if isinstance(raw_name, bytes):
                            name = raw_name.split(b"\0", 1)[0].decode("ascii", errors="ignore")
                        else:
                            name = str(raw_name).split("\0", 1)[0]
                        if name == "gate_count":
                            self._last_gate_count = max(
                                0, min(10, int(getattr(message, "value", 0)))
                            )
                        elif name == "mark_count":
                            self._last_marker_count = max(
                                0, min(2, int(getattr(message, "value", 0)))
                            )
                        elif name == "arena_id":
                            self._last_arena_id = 1 if int(getattr(message, "value", 0)) else 0
                    elif message_type == "NAMED_VALUE_FLOAT":
                        raw_name = getattr(message, "name", b"")
                        if isinstance(raw_name, bytes):
                            name = raw_name.split(b"\0", 1)[0].decode("ascii", errors="ignore")
                        else:
                            name = str(raw_name).split("\0", 1)[0]
                        ultrasonic_names = {
                            "ultra_fl": "front_left",
                            "ultra_f": "front",
                            "ultra_fr": "front_right",
                            "ultra_l": "left",
                            "ultra_r": "right",
                            # Compatibility with older simulator packets.
                            "son_fl": "front_left",
                            "son_f": "front",
                            "son_fr": "front_right",
                            "son_l": "left",
                            "son_r": "right",
                        }
                        ultrasonic_key = ultrasonic_names.get(name)
                        if ultrasonic_key is not None:
                            self._last_ultrasonic[ultrasonic_key] = max(
                                0.05,
                                min(5.0, float(getattr(message, "value", 5.0))),
                            )
                        elif name == "yaw_rate":
                            self._last_yaw_rate_dps = float(
                                getattr(message, "value", 0.0)
                            )
                        elif name == "azimuth":
                            self._last_azimuth_angle_deg = float(
                                getattr(message, "value", 0.0)
                            )
            except Exception:
                self._last_heartbeat = None
                self._last_rc_channels = None
                self._last_servo_output = None
                self._last_vfr_hud = None
                self._last_global_pos = None
                self._last_heading_update_s = 0.0
                self._last_position_update_s = 0.0
                self._last_gate_count = None
                self._last_marker_count = None
                self._last_arena_id = None
        heartbeat = self._last_heartbeat
        armed = False
        base_mode = None
        system_status = None
        if heartbeat is not None:
            base_mode = getattr(heartbeat, "base_mode", None)
            if base_mode is not None:
                armed = bool(
                    base_mode & self._mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                )
            system_status = getattr(heartbeat, "system_status", None)
        rc = self._last_rc_channels
        servo = self._last_servo_output
        pos_x = None
        pos_y = None
        spd = None
        if self._last_global_pos is not None:
            lat = self._last_global_pos.lat / 1e7
            lon = self._last_global_pos.lon / 1e7
            base_lat = self._origin_lat
            base_lon = self._origin_lon
            meters_per_deg = 111319.5
            pos_y = (lat - base_lat) * meters_per_deg
            pos_x = (lon - base_lon) * (meters_per_deg * math.cos(math.radians(base_lat)))
            vx = getattr(self._last_global_pos, "vx", 0) / 100.0
            vy = getattr(self._last_global_pos, "vy", 0) / 100.0
            spd = math.sqrt(vx * vx + vy * vy)
        now = time.monotonic()
        position_age_s = (
            now - self._last_position_update_s
            if self._last_position_update_s > 0.0
            else float("inf")
        )
        heading_age_s = (
            now - self._last_heading_update_s
            if self._last_heading_update_s > 0.0
            else float("inf")
        )
        telemetry_age_s = max(position_age_s, heading_age_s)
        return {
            "mode": self.mode(),
            "armed": armed,
            "base_mode": base_mode,
            "system_status": system_status,
            "heading_deg": vfr_hud_heading(self._last_vfr_hud),
            "x": pos_x,
            "y": pos_y,
            "speed_mps": spd,
            "gate_count": self._last_gate_count,
            "marker_count": self._last_marker_count,
            "arena": (
                None
                if self._last_arena_id is None
                else "B"
                if self._last_arena_id == 1
                else "A"
            ),
                "ultrasonic": dict(self._last_ultrasonic),
                "sonar": dict(self._last_ultrasonic),
                "yaw_rate_dps": self._last_yaw_rate_dps,
                "azimuth_angle_deg": self._last_azimuth_angle_deg,
                "telemetry_age_s": telemetry_age_s,
            "position_age_s": position_age_s,
            "heading_age_s": heading_age_s,
            "rc1": getattr(rc, "chan1_raw", None),
            "rc3": getattr(rc, "chan3_raw", None),
            "servo1": getattr(servo, "servo1_raw", None),
            "servo3": getattr(servo, "servo3_raw", None),
        }

    def send_override(self, steering_pwm: int, throttle_pwm: int) -> None:
        """Set target steering and throttle for 20Hz stream thread."""
        with self._lock:
            self._target_steering = int(clamp(steering_pwm, PWM_MIN, PWM_MAX))
            self._target_throttle = int(clamp(throttle_pwm, PWM_MIN, PWM_MAX))
            self._override_active = True

    def release_override(self) -> None:
        """Release RC1 and RC3 overrides back to neutral."""
        with self._lock:
            self._target_steering = NEUTRAL_PWM
            self._target_throttle = NEUTRAL_PWM
            self._override_active = False

    def _override_loop(self) -> None:
        unused = 65535
        while self._running:
            with self._lock:
                steer = self._target_steering
                thr = self._target_throttle

            if self.connection is not None:
                now = time.monotonic()
                if self._last_heartbeat_time > 0 and (now - self._last_heartbeat_time > self._heartbeat_timeout):
                    self.reconnect()

                with self._mav_lock:
                    try:
                        self.connection.mav.rc_channels_override_send(
                            self.connection.target_system,
                            self.connection.target_component,
                            steer,
                            unused,
                            thr,
                            unused, unused, unused, unused, unused
                        )
                    except Exception:
                        pass
            time.sleep(0.05)
    def close(self) -> None:
        self._running = False
        self.release_override()
        unused = 65535
        if self.connection is not None:
            with self._mav_lock:
                try:
                    self.connection.mav.rc_channels_override_send(
                        self.connection.target_system,
                        self.connection.target_component,
                        0, unused, 0, unused, unused, unused, unused, unused
                    )
                    self.connection.close()
                except Exception:
                    pass


class CourseAutopilot:
    """Run simulator course control at 20 Hz, independent of YOLO latency."""

    def __init__(
        self,
        link: PixhawkLink,
        arena: str = "A",
        control_hz: float = 20.0,
        *,
        sensor_only: bool = False,
        telemetry_timeout_s: float = 0.75,
    ) -> None:
        self.link = link
        self.control_hz = max(5.0, float(control_hz))
        self.sensor_only = bool(sensor_only)
        self.telemetry_timeout_s = max(0.2, float(telemetry_timeout_s))
        self.controller = CourseRouteController(CourseRouteConfig(arena=arena))
        self._visual_arena = str(arena).upper()
        self.visual_centering = VisualGateCentering(
            VisualGateCorrectionConfig(red_on_left=self._visual_arena == "A")
        )
        self._lock = threading.Lock()
        self._running = False
        self._active = False
        self._telemetry: dict[str, Any] = {}
        self._decision: CourseDecision | None = None
        self._visual_correction: VisualGateCorrection | None = None
        self._buoy_detections: tuple[Detection, ...] = ()
        self._buoy_frame_width = 0
        self._buoy_frame_height = 0
        self._buoy_observed_at_s: float | None = None
        self._marker_detections: tuple[Detection, ...] = ()
        self._marker_frame_width = 0
        self._marker_frame_height = 0
        self._marker_observed_at_s: float | None = None
        self._error: str | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="asv-course-control-20hz",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._active:
            self.link.send_override(NEUTRAL_PWM, NEUTRAL_PWM)

    def snapshot(self) -> tuple[bool, dict[str, Any], CourseDecision | None, str | None]:
        with self._lock:
            return self._active, dict(self._telemetry), self._decision, self._error

    def update_visual(
        self,
        detections: Sequence[Detection],
        *,
        frame_width: int,
        frame_height: int,
        now_s: float | None = None,
    ) -> VisualGateCorrection | None:
        """Publish buoy and marker observations to the 20 Hz control loop.

        Marker detections are kept separately from the buoy pair matcher.  A
        marker box is an obstacle to avoid, not a gate buoy to centre on.
        """

        now = time.monotonic() if now_s is None else float(now_s)
        with self._lock:
            self._buoy_detections = tuple(
                detection
                for detection in detections
                if detection.label in {"red_buoy", "green_buoy"}
            )
            self._buoy_frame_width = int(frame_width)
            self._buoy_frame_height = int(frame_height)
            self._buoy_observed_at_s = now
            self._marker_detections = tuple(
                detection
                for detection in detections
                if detection.label in MARKER_DETECTION_LABELS
            )
            self._marker_frame_width = int(frame_width)
            self._marker_frame_height = int(frame_height)
            self._marker_observed_at_s = now
            self._visual_correction = self.visual_centering.update(
                detections,
                frame_width=frame_width,
                frame_height=frame_height,
                now_s=now,
            )
            return self._visual_correction

    def _apply_single_buoy_obstacle_correction(
        self,
        decision: CourseDecision,
        *,
        now_s: float,
    ) -> CourseDecision:
        """Use a close, single YOLO buoy as a last-metre avoidance guard.

        The pair-centering layer intentionally needs red *and* green from one
        gate.  In the real camera view the nearer buoy is often visible alone
        (the second buoy is hidden by the bow, glare, or the gate geometry).
        Previously that frame produced no visual command at all, so the boat
        continued into the detected buoy.  A lone, sufficiently large/low
        detection is therefore treated as an obstacle: turn away from its
        image side and reduce thrust.  It never replaces the route waypoint.
        """

        if decision.finished or decision.phase not in {
            CoursePhase.APPROACH,
            CoursePhase.TURN,
            CoursePhase.CORRIDOR,
        }:
            return decision
        with self._lock:
            observed_at = self._buoy_observed_at_s
            frame_width = self._buoy_frame_width
            frame_height = self._buoy_frame_height
            detections = tuple(self._buoy_detections)
            pair_correction = self.visual_centering.current(now_s=now_s)
        if (
            pair_correction is not None
            or observed_at is None
            or now_s - observed_at > 0.35
            or frame_width <= 0
            or frame_height <= 0
            or not detections
        ):
            return decision

        # If both colours are present but the pair matcher rejected them, the
        # geometry is ambiguous; do not steer at an arbitrary buoy from the
        # next gate.  A lone colour is the safe, actionable case.
        if len({detection.label for detection in detections}) != 1:
            return decision
        obstacle = max(detections, key=lambda item: (item.area, item.y_center))
        if obstacle.confidence < 0.45:
            return decision
        image_center = frame_width / 2.0
        normalized_error = clamp(
            (obstacle.x_center - image_center) / max(image_center, 1.0),
            -1.0,
            1.0,
        )
        depth_ratio = clamp(obstacle.y_center / float(frame_height), 0.0, 1.0)
        area_ratio = obstacle.area / float(frame_width * frame_height)
        # Small/high detections are usually a distant gate and should not
        # perturb the local route.  The thresholds accept the gate-6 failure
        # case (green buoy at y~=0.55, area~=1.4% of the frame).
        if depth_ratio < 0.42 or area_ratio < 0.006:
            return decision
        proximity = clamp((depth_ratio - 0.42) / 0.40, 0.0, 1.0)
        steer_limit = 45.0 + 75.0 * proximity
        steer_delta = int(
            round(
                clamp(
                    -normalized_error * steer_limit,
                    -90.0,
                    90.0,
                )
            )
        )
        throttle_cap = int(round(1550.0 - 18.0 * proximity))
        return replace(
            decision,
            steering_pwm=int(
                round(
                    clamp(
                        decision.steering_pwm + steer_delta,
                        NEUTRAL_PWM - self.controller.config.max_steering_delta,
                        NEUTRAL_PWM + self.controller.config.max_steering_delta,
                    )
                )
            ),
            throttle_pwm=min(decision.throttle_pwm, throttle_cap),
            obstacle_avoidance=True,
            avoidance_reason="VISION_SINGLE_BUOY",
            visual_correction_active=True,
            visual_correction_pwm=steer_delta,
            visual_target_error=normalized_error,
        )

    def _set_visual_arena(self, arena: object) -> None:
        selected = str(arena or self._visual_arena).upper()
        if selected not in {"A", "B"}:
            return
        with self._lock:
            if selected == self._visual_arena:
                return
            self._visual_arena = selected
            self.visual_centering = VisualGateCentering(
                VisualGateCorrectionConfig(red_on_left=selected == "A")
            )
            self._visual_correction = None

    def _apply_marker_obstacle_correction(
        self,
        decision: CourseDecision,
        *,
        now_s: float,
    ) -> CourseDecision:
        """Use the colour detector as a bounded last-metre obstacle layer.

        The route waypoint remains the primary guidance.  When the active blue
        or green box is visible, this layer only steers away from its image
        centre and caps thrust while the box occupies a meaningful part of the
        frame.  It expires quickly so stale camera frames cannot keep turning
        the vessel after the box has passed.
        """

        if decision.finished or decision.phase not in {
            CoursePhase.MARKER_BLUE,
            CoursePhase.MARKER_GREEN,
        }:
            return decision
        active_label = (
            "blue_marker"
            if decision.marker_count <= 0
            else "green_marker"
        )
        with self._lock:
            observed_at = self._marker_observed_at_s
            frame_width = self._marker_frame_width
            frame_height = self._marker_frame_height
            detections = tuple(
                detection
                for detection in self._marker_detections
                if detection.label == active_label
            )
        if (
            observed_at is None
            or now_s - observed_at > 0.65
            or frame_width <= 0
            or frame_height <= 0
            or not detections
        ):
            return decision

        # The largest candidate is the closest/most relevant one.  Its
        # normalized horizontal error has the opposite sign for avoidance:
        # obstacle right -> turn left, obstacle left -> turn right.
        obstacle = max(detections, key=lambda item: (item.area, item.y_center))
        image_center = frame_width / 2.0
        normalized_error = clamp(
            (obstacle.x_center - image_center) / max(image_center, 1.0),
            -1.0,
            1.0,
        )
        area_ratio = obstacle.area / float(frame_width * frame_height)
        # A centred box is handled by the safe-side GPS waypoint.  The visual
        # layer supplies a modest counter-steer only when lateral separation is
        # observable, avoiding left/right oscillation at the marker plane.
        steer_delta = int(
            round(
                clamp(
                    -normalized_error * 150.0,
                    -150.0,
                    150.0,
                )
            )
        )
        # The GPS route already supplies the safe-side pass point.  Use the
        # colour detector as a last-metre guard, not as a full stop: the old
        # 1510 PWM cap made a visible box slow the hull several metres before
        # the pass plane.  Reserve the stronger cap for a genuinely close
        # rectangle and let normal marker speed continue at a distance.
        if area_ratio >= 0.040:
            throttle_cap = 1524
        elif area_ratio >= 0.018:
            throttle_cap = 1534
        else:
            throttle_cap = 1542
        return replace(
            decision,
            steering_pwm=int(
                round(
                    clamp(
                        decision.steering_pwm + steer_delta,
                        NEUTRAL_PWM - self.controller.config.max_steering_delta,
                        NEUTRAL_PWM + self.controller.config.max_steering_delta,
                    )
                )
            ),
            throttle_pwm=min(decision.throttle_pwm, throttle_cap),
            obstacle_avoidance=True,
            avoidance_reason="VISION_MARKER_BOX",
        )

    def _apply_visual_correction(
        self,
        decision: CourseDecision,
        *,
        now_s: float,
    ) -> CourseDecision:
        decision = self._apply_marker_obstacle_correction(decision, now_s=now_s)
        if decision.avoidance_reason == "VISION_MARKER_BOX":
            return decision
        decision = self._apply_single_buoy_obstacle_correction(decision, now_s=now_s)
        if decision.avoidance_reason == "VISION_SINGLE_BUOY":
            return decision
        # The blind corner is a deterministic three-state manoeuvre.  Camera
        # trim is intentionally disabled during the brake and hard-left pulse;
        # a stale pair from the previous/next gate must not dilute the pivot.
        if decision.avoidance_reason in {
            "BLIND_LEFT_BRAKE",
            "BLIND_LEFT_PIVOT",
            "CORRIDOR_CENTER_BRAKE",
            "CORRIDOR_CENTER_KICK",
            "CORRIDOR_NORTH_RECAPTURE",
        }:
            return decision
        blind_visual_phase = (
            decision.phase is CoursePhase.TURN
            and decision.gate_count in {3, 7}
        )
        with self._lock:
            correction = self.visual_centering.current(now_s=now_s)
        if (
            correction is None
            or decision.finished
            or decision.phase in {CoursePhase.DOCK, CoursePhase.FINISH}
            or decision.obstacle_avoidance
            or not 0 <= decision.gate_count < len(self.controller.waypoints)
        ):
            return decision

        # The simulator exposes a scored GPS/gate route, so the waypoint
        # controller is the primary authority.  YOLO can occasionally pair a
        # buoy from the next gate with one from the current gate while two
        # gates are visible; allowing that raw image error to command a full
        # 160-PWM turn is what previously sent the hull outside Gate 3.  Keep
        # camera input as a small, bounded cross-track trim so modest arena
        # offsets are corrected without overriding the deterministic route.
        lookahead_m = self.controller.gate_lookahead_distance(decision.gate_count)
        authority = clamp(
            decision.waypoint_distance_m / max(lookahead_m, 0.1),
            0.0,
            # The blind maneuver is only a short peek. Once a valid pair is
            # reacquired, the camera gets a smaller trim authority; it must
            # never reinstate a fixed hard-left turn.
            0.10 if blind_visual_phase else 0.18,
        )
        visual_delta = int(
            round(
                clamp(
                    correction.steering_delta_pwm * authority,
                    -30.0,
                    30.0,
                )
            )
        )
        steering_pwm = int(
            round(
                clamp(
                    decision.steering_pwm + visual_delta,
                    NEUTRAL_PWM - self.controller.config.max_steering_delta,
                    NEUTRAL_PWM + self.controller.config.max_steering_delta,
                )
            )
        )
        return replace(
            decision,
            steering_pwm=steering_pwm,
            visual_correction_active=True,
            visual_correction_pwm=visual_delta,
            visual_target_error=correction.normalized_error,
        )

    def _loop(self) -> None:
        period_s = 1.0 / self.control_hz
        next_tick = time.monotonic()
        while self._running:
            now = time.monotonic()
            if now < next_tick:
                time.sleep(min(0.01, next_tick - now))
                continue
            next_tick = now + period_s
            try:
                telemetry = self.link.telemetry()
                required = (
                    telemetry.get("x"),
                    telemetry.get("y"),
                    telemetry.get("heading_deg"),
                )
                if any(value is None for value in required):
                    try:
                        self.link.send_override(NEUTRAL_PWM, NEUTRAL_PWM)
                    except Exception:
                        pass
                    with self._lock:
                        self._active = False
                        self._telemetry = telemetry
                        self._error = "Telemetri posisi/heading belum tersedia; PWM dinetralkan."
                    continue
                telemetry_age = telemetry.get("telemetry_age_s")
                if telemetry_age is not None:
                    try:
                        telemetry_age = float(telemetry_age)
                    except (TypeError, ValueError):
                        telemetry_age = float("inf")
                    if not math.isfinite(telemetry_age) or telemetry_age > self.telemetry_timeout_s:
                        try:
                            self.link.send_override(NEUTRAL_PWM, NEUTRAL_PWM)
                        except Exception:
                            pass
                        with self._lock:
                            self._active = False
                            self._telemetry = telemetry
                            self._error = (
                                f"Telemetri stale ({telemetry_age:.2f}s); PWM dinetralkan."
                            )
                        continue
                arena = telemetry.get("arena") or self.controller.arena
                self._set_visual_arena(arena)
                decision = self.controller.step(
                    gate_count=(
                        None
                        if self.sensor_only or telemetry.get("gate_count") is None
                        else int(telemetry["gate_count"])
                    ),
                    marker_count=(
                        None
                        if self.sensor_only
                        else telemetry.get("marker_count")
                    ),
                    x=float(telemetry["x"]),
                    y=float(telemetry["y"]),
                    heading_deg=float(telemetry["heading_deg"]),
                    speed_mps=float(telemetry.get("speed_mps") or 0.0),
                    yaw_rate_dps=telemetry.get("yaw_rate_dps"),
                    ultrasonic=(
                        telemetry.get("ultrasonic") or telemetry.get("sonar")
                    ),
                    now_s=now,
                    arena=str(arena),
                )
                decision = self._apply_visual_correction(decision, now_s=now)
                self.link.send_override(decision.steering_pwm, decision.throttle_pwm)
                with self._lock:
                    self._active = True
                    self._telemetry = telemetry
                    self._decision = decision
                    self._error = None
            except Exception as exc:
                try:
                    self.link.send_override(NEUTRAL_PWM, NEUTRAL_PWM)
                except Exception:
                    pass
                with self._lock:
                    self._active = False
                    self._error = str(exc)


def create_pixhawk_link(
    *,
    manual_rc: bool,
    endpoint: str,
    origin_lat: float = -6.200000,
    origin_lon: float = 106.816666,
) -> PixhawkLink | None:
    """Create the control link only for the legacy control path."""
    if manual_rc:
        return None
    return PixhawkLink(endpoint, origin_lat=origin_lat, origin_lon=origin_lon)

def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Navigasi ASV dengan YOLO, MAVLink, dan opsi monitoring manual RC."
    )
    parser.add_argument(
        "--manual-rc",
        action="store_true",
        help="Model monitoring only; never open Pixhawk or send MAVLink commands",
    )
    parser.add_argument(
        "--model",
        default=str(repo_root / "model" / "best.pt"),
        help="Path model Ultralytics .pt",
    )
    parser.add_argument(
        "--endpoint",
        default="tcp:127.0.0.1:5762",
        help="Endpoint MAVLink; default TCP forwarding Mission Planner",
    )
    parser.add_argument(
        "--arena",
        choices=("A", "B", "a", "b"),
        default="A",
        help="Arena aktif A atau lintasan cermin B (default A)",
    )
    parser.add_argument(
        "--origin-lat",
        type=float,
        default=-6.200000,
        help="Latitude origin ENU lokal (default origin simulator)",
    )
    parser.add_argument(
        "--origin-lon",
        type=float,
        default=106.816666,
        help="Longitude origin ENU lokal (default origin simulator)",
    )
    parser.add_argument(
        "--telemetry-timeout-s",
        type=float,
        default=0.75,
        help="Netralisasi PWM jika posisi/heading stale lebih lama dari ini",
    )
    parser.add_argument(
        "--log",
        default=str(repo_root / "simulation" / "logs" / "vision_test_log.jsonl"),
        help="File JSON Lines untuk log vision, RC, dan output PWM",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Durasi uji dalam detik; 0 berarti berjalan sampai Q/ESC",
    )
    parser.add_argument(
        "--camera", default="0", help="Nomor webcam OpenCV atau URL stream"
    )
    parser.add_argument(
        "--conf", type=float, default=0.35, help="Confidence minimum deteksi"
    )
    parser.add_argument(
        "--vision-fps",
        type=float,
        default=4.0,
        help="Maksimum laju inferensi/model per detik",
    )
    parser.add_argument(
        "--gain", type=float, default=1.0, help="Gain steering"
    )
    parser.add_argument(
        "--invert-steering",
        action="store_true",
        help="Balik arah rudder jika gerak servo terbalik",
    )
    parser.add_argument(
        "--target-hold-s",
        type=float,
        default=0.5,
        help="Durasi tahan target visual setelah buoy hilang",
    )
    parser.add_argument(
        "--target-smoothing",
        type=float,
        default=0.5,
        help="Alpha smoothing target visual, 1 berarti tanpa smoothing",
    )
    parser.add_argument(
        "--throttle-pwm",
        type=int,
        default=1560,
        help="Throttle cruise saat jarak sedang; default 1560",
    )
    parser.add_argument(
        "--throttle-near-pwm",
        type=int,
        default=1540,
        help="Throttle saat buoy dekat",
    )
    parser.add_argument(
        "--throttle-far-pwm",
        type=int,
        default=1600,
        help="Throttle saat buoy jauh",
    )
    parser.add_argument(
        "--throttle-hold-s",
        type=float,
        default=0.8,
        help="Durasi tahan throttle setelah deteksi hilang",
    )
    parser.add_argument(
        "--throttle-ramp-pwm-per-s",
        type=float,
        default=200.0,
        help="Batas perubahan throttle PWM per detik",
    )
    parser.add_argument(
        "--throttle-steering-boost-pwm",
        type=int,
        default=25,
        help="Tambahan throttle saat belok tajam",
    )
    parser.add_argument(
        "--bridge-url",
        default=None,
        help="URL local ASV bridge, e.g. http://127.0.0.1:8080",
    )
    parser.add_argument(
        "--bridge-asv-id",
        default="default",
        help="ASV id yang dipublikasikan ke bridge",
    )
    parser.add_argument(
        "--bridge-stream-url",
        default=None,
        help="HTTPS URL raw surface stream yang ditampilkan dashboard",
    )
    parser.add_argument(
        "--bridge-surface-fps",
        type=float,
        default=5.0,
        help="Batas FPS upload frame surface ke bridge lokal",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Jalankan tanpa jendela GUI OpenCV (cocok untuk server/background)",
    )
    parser.add_argument(
        "--sensor-only",
        action="store_true",
        help=(
            "Abaikan gate_count/marker_count scorer Webots; infer progress "
            "dari GPS, heading, kamera, dan ultrasonik seperti mode kapal nyata"
        ),
    )
    return parser.parse_args()


def compute_pd_heading_pwm(target_hdg: float, current_hdg: float, last_err: float, dt: float, max_pwm_delta: float = 80.0) -> tuple[int, float]:
    """Compute PD heading steering PWM with dead-band and derivative damping to eliminate hunting."""
    err = ((target_hdg - current_hdg + 180.0) % 360.0) - 180.0
    if abs(err) < 8.0:
        return 1500, err
    d_err = (err - last_err) / max(0.01, dt) if dt > 0.0 else 0.0
    p_term = err * 1.5
    d_term = clamp(d_err * 0.10, -25.0, 25.0)
    steer_corr = clamp(p_term + d_term, -max_pwm_delta, max_pwm_delta)
    pwm = int(round(clamp(1500 + steer_corr, 1500 - max_pwm_delta, 1500 + max_pwm_delta)))
    return pwm, err
def draw_detections(frame: Any, detections: Sequence[Detection], target_x: float | None) -> Any:
    """Draw rich Google Maps / AR Lane Assist navigation overlay showing centerline between Red & Green buoys."""
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    overlay = frame.copy()

    # 1. Detect red and green buoy positions
    reds = [d for d in detections if d.label == "red_buoy"]
    greens = [d for d in detections if d.label == "green_buoy"]

    # 2. Draw Google Maps AR Lane Corridor & Centerline if Buoys are detected
    if reds and greens:
        # Sort closest buoys (largest area / y_center)
        red = max(reds, key=lambda d: (d.y_center, d.area))
        green = max(greens, key=lambda d: (d.y_center, d.area))

        rx, ry = int(red.x_center), int(red.y_center)
        gx, gy = int(green.x_center), int(green.y_center)
        mid_x = int((red.x_center + green.x_center) / 2.0)
        mid_y = int((red.y_center + green.y_center) / 2.0)

        # Translucent Blue/Cyan Navigation Corridor Polygon
        poly_pts = np.array([
            [max(0, rx - int(red.width)), h - 10],
            [rx, ry],
            [gx, gy],
            [min(w, gx + int(green.width)), h - 10],
        ], np.int32)
        cv2.fillPoly(overlay, [poly_pts], (235, 145, 10))

        # Lane Rails (Red on Left, Green on Right)
        cv2.line(overlay, (max(0, rx - int(red.width)), h - 10), (rx, ry), (0, 0, 255), 4, cv2.LINE_AA)
        cv2.line(overlay, (min(w, gx + int(green.width)), h - 10), (gx, gy), (0, 255, 0), 4, cv2.LINE_AA)

        # Centerline Path (Google Maps Glowing Cyan Line)
        cv2.line(overlay, (int(w / 2), h - 10), (mid_x, mid_y), (255, 230, 0), 4, cv2.LINE_AA)

        # Chevrons (>>>) along Centerline
        for t in [0.25, 0.50, 0.75]:
            cx = int(w / 2 + t * (mid_x - w / 2))
            cy = int(h - 10 + t * (mid_y - (h - 10)))
            wing_w = int(12 * (1.0 - t * 0.3))
            wing_h = int(9 * (1.0 - t * 0.3))
            cv2.line(overlay, (cx - wing_w, cy + wing_h), (cx, cy), (255, 255, 255), 3, cv2.LINE_AA)
            cv2.line(overlay, (cx + wing_w, cy + wing_h), (cx, cy), (255, 255, 255), 3, cv2.LINE_AA)

        # Google Maps Target Pin at Gate Midpoint
        cv2.circle(overlay, (mid_x, mid_y), 10, (0, 230, 255), -1, cv2.LINE_AA)
        cv2.circle(overlay, (mid_x, mid_y), 14, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(overlay, (mid_x, mid_y), 4, (0, 0, 255), -1, cv2.LINE_AA)

        # Label Pin
        cv2.putText(
            overlay,
            "GARIS TENGAH (MERAH - HIJAU)",
            (max(10, mid_x - 110), max(25, mid_y - 18)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            overlay,
            "GARIS TENGAH (MERAH - HIJAU)",
            (max(10, mid_x - 110), max(25, mid_y - 18)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 230, 255),
            1,
            cv2.LINE_AA,
        )

        cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

    elif target_x is not None:
        tx = int(target_x)
        ty = int(h * 0.45)
        # Single buoy target centerline projection
        cv2.line(overlay, (int(w / 2), h - 10), (tx, ty), (255, 230, 0), 3, cv2.LINE_AA)
        cv2.circle(overlay, (tx, ty), 8, (0, 230, 255), -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.35, frame, 0.65, 0, frame)

    # 3. Draw Bounding Boxes with Labels
    for detection in detections:
        x1 = int(detection.x_center - detection.width / 2.0)
        y1 = int(detection.y_center - detection.height / 2.0)
        x2 = int(detection.x_center + detection.width / 2.0)
        y2 = int(detection.y_center + detection.height / 2.0)
        if detection.label == "red_buoy":
            color = (0, 0, 255)
        elif detection.label == "green_buoy":
            color = (0, 255, 0)
        elif detection.label == "blue_marker":
            color = (255, 120, 0)
        else:  # green_marker
            color = (80, 255, 80)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            frame,
            f"{detection.label} {detection.confidence:.2f}",
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            color,
            2,
        )

    # Center Reference Guideline
    cv2.line(frame, (w // 2, 0), (w // 2, h), (255, 255, 255), 1, cv2.LINE_AA)
    return frame


def main() -> None:
    args = parse_args()
    args.arena = str(args.arena).upper()
    if not 0.0 < args.conf <= 1.0:
        raise ValueError("--conf harus berada di antara 0 dan 1")
    if not 0.0 < args.vision_fps:
        raise ValueError("--vision-fps harus positif")
    if args.duration < 0:
        raise ValueError("--duration tidak boleh negatif")
    throttle_config = ThrottleConfig(
        near_pwm=args.throttle_near_pwm,
        cruise_pwm=args.throttle_pwm,
        far_pwm=args.throttle_far_pwm,
        hold_s=args.throttle_hold_s,
        ramp_pwm_per_s=args.throttle_ramp_pwm_per_s,
        steering_boost_pwm=args.throttle_steering_boost_pwm,
    )
    throttle_controller = VisualThrottleController(throttle_config)
    search_controller = VisualSearchController(
        SearchConfig(center_pwm=1500, max_delta=40, period_s=5.0, throttle_pwm=1545)
    )
    target_tracker = VisualTargetTracker(
        hold_s=args.target_hold_s,
        smoothing_alpha=args.target_smoothing,
        red_on_left=str(args.arena).upper() == "A",
    )
    gate_tracker = GateTracker(crossing_y=0.65, cooldown_s=1.5)
    course_controller = CourseRouteController(CourseRouteConfig(arena=args.arena))
    last_hdg_err: float = 0.0
    last_hdg_now: float = 0.0
    unstuck_until: float = 0.0
    stuck_timer: float | None = None
    try:
        from ultralytics import YOLO
        import cv2
    except ImportError as exc:
        dependencies = "ultralytics opencv-python"
        if not args.manual_rc:
            dependencies += " pymavlink pyserial"
        raise RuntimeError(
            f"Dependensi belum lengkap. Jalankan: python -m pip install {dependencies}"
        ) from exc

    model_path = Path(args.model)
    if not model_path.is_file():
        raise FileNotFoundError(f"Model tidak ditemukan: {model_path}")

    print(f"Memuat model: {model_path}")
    model = YOLO(str(model_path))
    link = create_pixhawk_link(
        manual_rc=args.manual_rc,
        endpoint=args.endpoint,
        origin_lat=args.origin_lat,
        origin_lon=args.origin_lon,
    )
    course_autopilot: CourseAutopilot | None = None
    logger = JsonlLogger(args.log)
    run_id = datetime.now(timezone.utc).strftime("vision-%Y%m%dT%H%M%SZ")
    logger.write(
        {
            "event": "start",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "model": str(model_path),
            "endpoint": args.endpoint,
            "camera": args.camera,
            "run_id": run_id,
            "vision_fps": args.vision_fps,
            "arena": args.arena,
            "sensor_only": args.sensor_only,
            "origin_lat": args.origin_lat,
            "origin_lon": args.origin_lon,
            "telemetry_timeout_s": args.telemetry_timeout_s,
        }
    )
    camera_source = int(args.camera) if str(args.camera).isdigit() else args.camera
    camera = cv2.VideoCapture(camera_source)
    if not camera.isOpened():
        logger.close()
        if link is not None:
            link.close()
        raise RuntimeError(f"Webcam {args.camera} tidak dapat dibuka")

    if link is not None:
        course_autopilot = CourseAutopilot(
            link,
            arena=args.arena,
            control_hz=20.0,
            sensor_only=args.sensor_only,
            telemetry_timeout_s=args.telemetry_timeout_s,
        )
        course_autopilot.start()

    print("Tekan Q atau ESC untuk berhenti.")
    print(
        f"Throttle dinamis: near={throttle_config.near_pwm} "
        f"cruise={throttle_config.cruise_pwm} far={throttle_config.far_pwm} "
        f"hold={throttle_config.hold_s:.2f}s "
        f"ramp={throttle_config.ramp_pwm_per_s:.0f} PWM/s"
    )
    print(
        "Mode progres: FIXED-COURSE + CAMERA/YOLO + ULTRASONIC "
        "(tanpa scorer Webots)"
        if args.sensor_only
        else "Mode progres: SIM-SCORER + sensor"
    )
    bridge = (
        BridgeFramePublisher(
            args.bridge_url,
            asv_id=args.bridge_asv_id,
            stream_url=args.bridge_stream_url,
            max_surface_fps=args.bridge_surface_fps,
        )
        if args.bridge_url
        else None
    )
    if bridge is not None:
        bridge.publish_status(
            online=True,
            model_status="running",
            run_id=run_id,
        )

    capture_queue = LatestFrameQueue()
    capture_stop = threading.Event()
    capture_errors: list[BaseException] = []

    def capture_frames() -> None:
        nonlocal camera
        frame_id = 0
        fail_count = 0
        try:
            while not capture_stop.is_set():
                # MJPEG connections can raise a decoder/transport exception
                # when Webots refreshes the stream.  Treat that exactly like a
                # failed frame and reconnect below; allowing it to escape would
                # close the queue and silently stop the 20 Hz autopilot.
                try:
                    ok, frame = camera.read()
                except Exception:
                    ok, frame = False, None
                if not ok:
                    fail_count += 1
                    if fail_count >= 20:
                        time.sleep(0.5)
                        try:
                            camera.release()
                            camera = cv2.VideoCapture(camera_source)
                        except Exception:
                            pass
                        fail_count = 0
                    else:
                        time.sleep(0.04)
                    continue
                fail_count = 0
                frame_id += 1
                capture_queue.put_latest(
                    CapturedFrame(
                        frame=frame,
                        frame_id=frame_id,
                        captured_at=datetime.now(timezone.utc),
                    )
                )
        except BaseException as exc:
            capture_errors.append(exc)
        finally:
            capture_queue.close()

    producer = threading.Thread(
        target=capture_frames,
        name="asv-camera-capture",
        daemon=True,
    )
    producer.start()
    last_log = 0.0
    started_at = time.monotonic()
    next_inference_at = 0.0
    inference_interval = 1.0 / args.vision_fps
    last_detections: list[Detection] = []
    target_x: float | None = None
    steering_pwm = NEUTRAL_PWM
    throttle_pwm = NEUTRAL_PWM
    mode = "UNKNOWN"
    telemetry: dict[str, Any] = {}
    nav_state = "IDLE"
    nav_target_info = ""
    area_ratio = 0.0
    px: float | None = None
    py: float | None = None
    current_hdg: float | None = None
    course_active = False
    latest_course_decision: CourseDecision | None = None
    try:
        while True:
            now = time.monotonic()
            if args.duration and now - started_at >= args.duration:
                break
            if capture_errors:
                raise capture_errors[0]

            captured = capture_queue.get(timeout=0.1)
            if captured is None:
                if capture_errors:
                    raise capture_errors[0]
                if capture_stop.is_set():
                    break
                continue

            frame = captured.frame
            metadata_published: bool | None = None
            if now >= next_inference_at:
                result = model.predict(frame, conf=args.conf, verbose=False)[0]
                last_detections = detections_from_result(result)
                # YOLO is trained only on the red/green buoy classes.  Add the
                # independent geometric marker detector to the same frame
                # record so the route can avoid the blue/green floating boxes
                # and the dashboard can show why a correction was applied.
                last_detections.extend(detect_marker_boxes(frame))
                target_x = target_tracker.update(last_detections, now=now, frame_width=frame.shape[1], frame_height=frame.shape[0])
                if course_autopilot is not None:
                    course_autopilot.update_visual(
                        last_detections,
                        frame_width=frame.shape[1],
                        frame_height=frame.shape[0],
                        now_s=now,
                    )
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
                    # Simulator control runs at 20 Hz in CourseAutopilot, while
                    # this inference/UI loop remains limited by --vision-fps.
                    if course_autopilot is not None:
                        (
                            course_active,
                            course_telemetry,
                            latest_course_decision,
                            course_error,
                        ) = course_autopilot.snapshot()
                        if course_telemetry:
                            telemetry = course_telemetry
                        if course_error:
                            mode = "COURSE_RETRY"
                    if link is not None and not course_active:
                        try:
                            telemetry = link.telemetry()
                            px = telemetry.get("x")
                            py = telemetry.get("y")
                            current_hdg = telemetry.get("heading_deg")
                        except Exception:
                            pass

                    nav_state = "IDLE"
                    nav_target_info = ""
                    has_red = any(d.label == "red_buoy" for d in last_detections)
                    has_green = any(d.label == "green_buoy" for d in last_detections)
                    is_right_slalom_gate2_3 = (
                        px is not None and py is not None and 0.0 <= py < 6.0 and px >= 5.0
                    )
                    is_turn_sector_3_to_4 = (
                        px is not None
                        and py is not None
                        and current_hdg is not None
                        and py >= 6.0
                        and px >= 9.8
                        and not 260.0 <= current_hdg <= 320.0
                    )
                    is_top_corridor = (
                        px is not None and py is not None and py >= 7.0 and -6.0 < px < 9.5
                    )
                    is_turn_sector_7_to_8 = (
                        px is not None
                        and py is not None
                        and current_hdg is not None
                        and px <= -6.0
                        and py >= 5.0
                        and not 170.0 <= current_hdg <= 240.0
                    )
                    is_left_slalom_gate8_9 = (
                        px is not None and py is not None and px <= -5.0 and 0.0 <= py < 5.0
                    )
                    is_left_slalom_gate9_10 = (
                        px is not None and py is not None and px <= -5.0 and py < 0.0
                    )
                    sim_gate_count = telemetry.get("gate_count") if telemetry else None

                    if sim_gate_count is not None and px is not None and py is not None and current_hdg is not None:
                        course_decision = latest_course_decision
                        if course_decision is None:
                            course_decision = course_controller.step(
                                gate_count=int(sim_gate_count),
                                marker_count=telemetry.get("marker_count"),
                                x=float(px),
                                y=float(py),
                                heading_deg=float(current_hdg),
                                speed_mps=float(telemetry.get("speed_mps") or 0.0),
                                yaw_rate_dps=telemetry.get("yaw_rate_dps"),
                                ultrasonic=(
                                    telemetry.get("ultrasonic")
                                    or telemetry.get("sonar")
                                ),
                                now_s=now,
                                arena=str(telemetry.get("arena") or args.arena),
                            )
                        steering_pwm = course_decision.steering_pwm
                        throttle_pwm = course_decision.throttle_pwm
                        nav_state = f"COURSE_{course_decision.phase.value}"
                        target = course_decision.target_waypoint
                        if target:
                            if course_decision.gate_count < 10:
                                target_label = f"Gate {course_decision.gate_count + 1}/10"
                            elif course_decision.marker_count == 0:
                                target_label = "Marker Biru"
                            elif course_decision.marker_count == 1:
                                target_label = "Marker Hijau"
                            elif course_decision.phase is CoursePhase.DOCK_APPROACH:
                                target_label = "Masuk Dock"
                            else:
                                target_label = "Dock"
                            nav_target_info = (
                                f"{target_label} "
                                f"hdg {course_decision.target_heading_deg:.1f}° "
                                f"err {course_decision.heading_error_deg:+.1f}° "
                                f"v={course_decision.target_speed_mps:.2f}m/s "
                                f"target=({target[0]:.1f},{target[1]:.1f}) "
                                "ultrasonic="
                                f"{course_decision.ultrasonic_min_m:.2f}m"
                                + (
                                    " cv="
                                    f"{course_decision.visual_correction_pwm:+d}PWM"
                                    if course_decision.visual_correction_active
                                    else ""
                                )
                            )
                        else:
                            nav_target_info = "Docking selesai"
                    elif is_turn_sector_3_to_4:
                        dt_hdg = now - last_hdg_now
                        steering_pwm, last_hdg_err = compute_pd_heading_pwm(270.0, current_hdg, last_hdg_err, dt_hdg, max_pwm_delta=250.0)
                        last_hdg_now = now
                        throttle_pwm = 1555
                        search_controller.reset()
                        nav_state = "SECTOR_TURN_3_TO_4"
                        hdg_err = ((270.0 - current_hdg + 180.0) % 360.0) - 180.0 if current_hdg is not None else 0.0
                        nav_target_info = f"Belok West (270°) ke Gate 4 [Err: {hdg_err:+.1f}°]"
                    elif is_right_slalom_gate2_3:
                        # Slalom Kanan Gate 2->3: Arahkan ke Gate 3 (X=11.0) dengan heading 30° NNE
                        dt_hdg = now - last_hdg_now
                        pd_steer, last_hdg_err = compute_pd_heading_pwm(30.0, current_hdg, last_hdg_err, dt_hdg, max_pwm_delta=140.0)
                        last_hdg_now = now
                        steering_pwm = pd_steer
                        throttle_pwm = 1565
                        nav_state = "RIGHT_SLALOM_2_TO_3_BLEND"
                        nav_target_info = "Gate 3 (30.0°) [Compass NNE]"
                    elif is_turn_sector_7_to_8:
                        dt_hdg = now - last_hdg_now
                        steering_pwm, last_hdg_err = compute_pd_heading_pwm(195.0, current_hdg, last_hdg_err, dt_hdg, max_pwm_delta=250.0)
                        last_hdg_now = now
                        throttle_pwm = 1555
                        search_controller.reset()
                        nav_state = "SECTOR_TURN_7_TO_8"
                        hdg_err = ((195.0 - current_hdg + 180.0) % 360.0) - 180.0 if current_hdg is not None else 0.0
                        nav_target_info = f"Belok SW (195°) ke Gate 8 [Err: {hdg_err:+.1f}°]"
                    elif is_top_corridor:
                        # Koridor Atas: Blend vision midpoint + PD line hold ke Y=10.0m
                        y_err = 10.0 - py
                        corridor_hdg = 270.0 + clamp(y_err * 20.0, -30.0, 30.0)
                        dt_hdg = now - last_hdg_now
                        pd_steer, last_hdg_err = compute_pd_heading_pwm(corridor_hdg, current_hdg, last_hdg_err, dt_hdg, max_pwm_delta=120.0)
                        last_hdg_now = now
                        if target_x is not None:
                            search_controller.reset()
                            vis_steer = compute_steering_pwm(target_x, frame.shape[1], gain=0.90, max_delta=75, invert=args.invert_steering)
                            steering_pwm = int(round(0.60 * vis_steer + 0.40 * pd_steer))
                            nav_target_info = f"Hold Y=10.0m ({corridor_hdg:.1f}°) + Vision Target {target_x:.1f}px"
                        else:
                            steering_pwm = pd_steer
                            nav_target_info = f"Hold Y=10.0m ({corridor_hdg:.1f}°) [Compass]"
                        throttle_pwm = 1565
                        nav_state = "TOP_CORRIDOR_BLEND"
                    elif is_left_slalom_gate8_9 or is_left_slalom_gate9_10:
                        # Slalom Kiri: Blend vision midpoint + heading waypoint
                        tgt_hdg = 150.0 if is_left_slalom_gate8_9 else 205.0
                        dt_hdg = now - last_hdg_now
                        pd_steer, last_hdg_err = compute_pd_heading_pwm(tgt_hdg, current_hdg, last_hdg_err, dt_hdg, max_pwm_delta=120.0)
                        last_hdg_now = now
                        if target_x is not None:
                            search_controller.reset()
                            vis_steer = compute_steering_pwm(target_x, frame.shape[1], gain=0.90, max_delta=75, invert=args.invert_steering)
                            steering_pwm = int(round(0.55 * vis_steer + 0.45 * pd_steer))
                            nav_target_info = f"Waypoint ({tgt_hdg:.0f}°) + Vision Target {target_x:.1f}px"
                        else:
                            steering_pwm = pd_steer
                            nav_target_info = f"Waypoint ({tgt_hdg:.0f}°) [Compass]"
                        throttle_pwm = 1560
                        nav_state = "LEFT_SLALOM_BLEND"
                    elif target_x is not None:
                        search_controller.reset()
                        steering_pwm = compute_steering_pwm(
                            target_x,
                            frame.shape[1],
                            gain=0.90,
                            max_delta=75,
                            invert=args.invert_steering,
                        )
                        throttle_pwm = max(1560, throttle_controller.update(
                            last_detections,
                            frame_width=int(frame.shape[1]),
                            frame_height=int(frame.shape[0]),
                            steering_pwm=steering_pwm,
                            now=now,
                            heading_deg=current_hdg,
                        ))

                        if has_red and has_green:
                            nav_state = "VISION_GATE_MIDPOINT"
                            nav_target_info = f"Garis Tengah Gate Merah-Hijau [Target: {target_x:.1f}px]"
                        elif has_red:
                            nav_state = "VISION_RED_PASS_RIGHT"
                            nav_target_info = f"Buoy Merah -> Lewat Kanan [Target: {target_x:.1f}px]"
                        elif has_green:
                            nav_state = "VISION_GREEN_PASS_LEFT"
                            nav_target_info = f"Buoy Hijau -> Lewat Kiri [Target: {target_x:.1f}px]"
                        else:
                            nav_state = "VISION_TARGET_HOLD"
                            nav_target_info = f"Tahan Target Visual Terakhir [Target: {target_x:.1f}px]"
                    else:
                        # Jeda visual antar gate: Kunci lintasan sektor dengan PD compass hold
                        sector_hdg = 18.0 if is_right_slalom_gate2_3 else 345.0
                        if current_hdg is not None:
                            dt_hdg = now - last_hdg_now
                            steering_pwm, last_hdg_err = compute_pd_heading_pwm(sector_hdg, current_hdg, last_hdg_err, dt_hdg, max_pwm_delta=90.0)
                            last_hdg_now = now
                            throttle_pwm = 1565
                            hdg_err = ((sector_hdg - current_hdg + 180.0) % 360.0) - 180.0
                            nav_state = "SECTOR_COMPASS_HOLD"
                            nav_target_info = f"Kunci Lintasan Sektor ({sector_hdg:.0f}°) [Err: {hdg_err:+.1f}°]"
                        else:
                            steering_pwm, throttle_pwm = search_controller.update(now=now)
                            nav_state = "SEARCH_SCANNING"
                            nav_target_info = "Pencarian Visual: Memindai permukaan air"
                    # Anti-stuck: Hanya aktif setelah 5 detik berjalan dan kapal benar-benar macet > 4.0s
                    boat_speed = abs(float(telemetry.get("speed_mps", 1.0))) if telemetry and telemetry.get("speed_mps") is not None else 1.0
                    if (
                        not course_active
                        and now - started_at > 5.0
                        and boat_speed < 0.10
                        and throttle_pwm > 1520
                    ):
                        if stuck_timer is None:
                            stuck_timer = now
                        elif now - stuck_timer > 4.0:
                            unstuck_until = now + 1.5
                            stuck_timer = None
                    else:
                        stuck_timer = None

                    if not course_active and now < unstuck_until:
                        # Manuver mundur darurat untuk lepas dari rintangan/dinding
                        steering_pwm = 1200
                        throttle_pwm = 1420
                        nav_state = "UNSTUCK_REVERSE"
                        nav_target_info = "KAPAL TERJEBAK -> Manuver Mundur Darurat"
                    # Wall safety boundary & Immediate Stop
                    px = telemetry.get("x") if telemetry else None
                    py = telemetry.get("y") if telemetry else None
                    if px is not None and py is not None:
                        arena_center_x = 30.0 if str(telemetry.get("arena") or args.arena).upper() == "B" else 0.0
                        if abs(px - arena_center_x) >= 14.30 or abs(py) >= 14.30:
                            print("\n[E-STOP] Sensor pembatas kolam aktif: menutup script vision_test.py untuk hemat waktu.")
                            break
                        if (
                            not course_active
                            and (
                                px - arena_center_x > 11.5
                                or py > 11.5
                                or px - arena_center_x < -11.5
                                or py < -11.5
                            )
                        ):
                            steering_pwm = min(steering_pwm, 1280)
                            throttle_pwm = min(throttle_pwm, 1540)

                    try:
                        assert link is not None
                        if not course_active:
                            link.send_override(steering_pwm, throttle_pwm)
                            mode = link.mode()
                            telemetry = link.telemetry()
                        else:
                            mode = str(telemetry.get("mode") or "COURSE_AUTO")
                        px = telemetry.get("x")
                        py = telemetry.get("y")
                        current_hdg = telemetry.get("heading_deg")
                    except Exception as exc:
                        mode = "MAVLINK_RETRY"
                if bridge is not None:
                    metadata_published = bridge.publish_detection_metadata(
                        detection_metadata_from_result(
                            last_detections,
                            asv_id=args.bridge_asv_id,
                            frame_id=captured.frame_id,
                            captured_at=captured.captured_at,
                            source_width=int(frame.shape[1]),
                            source_height=int(frame.shape[0]),
                        )
                    )
                queue_age_ms = max(
                    0.0,
                    (
                        datetime.now(timezone.utc) - captured.captured_at
                    ).total_seconds()
                    * 1000,
                )
                if now - last_log >= 0.25:
                    labels = ",".join(
                        detection.label for detection in last_detections
                    ) or "none"
                    record = {
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "frame_id": captured.frame_id,
                        "captured_at": captured.captured_at.isoformat(),
                        "queue_age_ms": queue_age_ms,
                        "metadata_published": metadata_published,
                        "navigation": {
                            "state": nav_state,
                            "target_info": nav_target_info,
                            "px": px,
                            "py": py,
                            "heading_deg": current_hdg,
                        },
                        "vision": {
                            "detections": [
                                asdict(detection)
                                for detection in last_detections
                            ],
                            "target_x": target_x,
                            "buoy_area_ratio": area_ratio,
                            "frame_width": int(frame.shape[1]),
                        },
                        "command": {
                            "mode": mode,
                            "steering_pwm": steering_pwm,
                            "throttle_pwm": throttle_pwm,
                        },
                        "ardupilot": telemetry,
                    }
                    logger.write(record)
                    pos_str = f"({px:.1f}, {py:.1f})" if px is not None and py is not None else "(-, -)"
                    hdg_str = f"{current_hdg:.0f}°" if current_hdg is not None else "-°"
                    print(
                        f"[{nav_state}] Pos={pos_str} Hdg={hdg_str} | {nav_target_info} | "
                        f"S={steering_pwm} T={throttle_pwm} | det={labels}"
                    )
                    last_log = now
                next_inference_at = now + inference_interval

            preview = draw_detections(frame.copy(), last_detections, target_x)
            cv2.putText(
                preview,
                f"MODE {mode}  STEER {steering_pwm}  THR {throttle_pwm}",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 255),
                2,
            )
            if bridge is not None:
                encoded_ok, encoded_frame = cv2.imencode(
                    ".jpg",
                    frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 80],
                )
                if encoded_ok:
                    bridge.publish_surface_frame(bytes(encoded_frame))
            if not args.headless:
                try:
                    cv2.imshow("Vision Test - tekan Q untuk berhenti", preview)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), 27):
                        break
                except Exception:
                    pass
    finally:
        capture_stop.set()
        capture_queue.close()
        producer.join()
        camera.release()
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        if course_autopilot is not None:
            course_autopilot.stop()
        if link is not None:
            try:
                link.send_override(NEUTRAL_PWM, NEUTRAL_PWM)
                time.sleep(0.1)
                link.release_override()
            finally:
                link.close()
        logger.write(
            {
                "event": "stop",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        logger.close()
        if bridge is not None:
            bridge.publish_status(
                online=False,
                model_status="offline",
                run_id=run_id,
            )
            bridge.close()
        if link is None:
            print("Model monitoring berhenti; Pixhawk tidak diakses.")
        else:
            print("Override dilepas; script berhenti dengan throttle netral.")


if __name__ == "__main__":
    main()
