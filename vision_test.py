"""Laptop webcam -> YOLO buoy detector -> ArduRover RC override.

The script keeps ArduRover in MANUAL mode and sends steering/throttle as
MAVLink RC_CHANNELS_OVERRIDE messages. It never arms the vehicle.

Default safety behavior:
- steering follows the detected buoy target;
- throttle is set to --throttle-pwm when a buoy target is detected;
- throttle returns to neutral (1500) when no target is visible.

With Mission Planner connected on COM5, enable MAVLink forwarding to TCP
127.0.0.1:5762 and run this script using the default endpoint.
"""

from __future__ import annotations

import argparse
import math
import json
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from vision_route import (
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
    """Minimal MAVLink connection for ArduRover RC overrides."""
    def __init__(self, endpoint: str, heartbeat_timeout: float = 5.0) -> None:
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
        self.connection = None
        self._lock = threading.Lock()
        self._mav_lock = threading.RLock()
        self._target_steering = NEUTRAL_PWM
        self._target_throttle = NEUTRAL_PWM
        self._override_active = False
        self._running = True
        self._last_heartbeat = None
        self._last_heartbeat_time = 0.0
        self._last_servo_output = None
        self._last_rc_channels = None
        self._last_vfr_hud = None
        self._last_global_pos = None

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
            }
        with self._mav_lock:
            try:
                while True:
                    message = self.connection.recv_match(
                        type=["HEARTBEAT", "RC_CHANNELS", "SERVO_OUTPUT_RAW", "VFR_HUD", "GLOBAL_POSITION_INT"],
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
                    elif message_type == "GLOBAL_POSITION_INT":
                        self._last_global_pos = message
            except Exception:
                pass
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
            base_lat = -6.200000
            base_lon = 106.816666
            meters_per_deg = 111319.5
            pos_y = (lat - base_lat) * meters_per_deg
            pos_x = (lon - base_lon) * (meters_per_deg * math.cos(math.radians(base_lat)))
            vx = getattr(self._last_global_pos, "vx", 0) / 100.0
            vy = getattr(self._last_global_pos, "vy", 0) / 100.0
            spd = math.sqrt(vx * vx + vy * vy)
        return {
            "mode": self.mode(),
            "armed": armed,
            "base_mode": base_mode,
            "system_status": system_status,
            "heading_deg": vfr_hud_heading(self._last_vfr_hud),
            "x": pos_x,
            "y": pos_y,
            "speed_mps": spd,
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

def create_pixhawk_link(
    *,
    manual_rc: bool,
    endpoint: str,
) -> PixhawkLink | None:
    """Create the control link only for the legacy control path."""
    if manual_rc:
        return None
    return PixhawkLink(endpoint)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deteksi buoy webcam dengan opsi model monitoring manual RC."
    )
    parser.add_argument(
        "--manual-rc",
        action="store_true",
        help="Model monitoring only; never open Pixhawk or send MAVLink commands",
    )
    parser.add_argument(
        "--model",
        default=r"D:\KKI2\model\best.pt",
        help="Path model Ultralytics .pt",
    )
    parser.add_argument(
        "--endpoint",
        default="tcp:127.0.0.1:5762",
        help="Endpoint MAVLink; default TCP forwarding Mission Planner",
    )
    parser.add_argument(
        "--log",
        default=r"D:\KKI2\vision_test_log.jsonl",
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
        color = (0, 0, 255) if detection.label == "red_buoy" else (0, 255, 0)
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
    )
    gate_tracker = GateTracker(crossing_y=0.65, cooldown_s=1.5)
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
    )
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
        }
    )
    camera_source = int(args.camera) if str(args.camera).isdigit() else args.camera
    camera = cv2.VideoCapture(camera_source)
    if not camera.isOpened():
        logger.close()
        if link is not None:
            link.close()
        raise RuntimeError(f"Webcam {args.camera} tidak dapat dibuka")

    print("Tekan Q atau ESC untuk berhenti.")
    print(
        f"Throttle dinamis: near={throttle_config.near_pwm} "
        f"cruise={throttle_config.cruise_pwm} far={throttle_config.far_pwm} "
        f"hold={throttle_config.hold_s:.2f}s "
        f"ramp={throttle_config.ramp_pwm_per_s:.0f} PWM/s"
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
                ok, frame = camera.read()
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
                target_x = target_tracker.update(last_detections, now=now, frame_width=frame.shape[1], frame_height=frame.shape[0])
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
                    # Update telemetri instrumen sebelum kalkulasi navigasi
                    if link is not None:
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

                    if is_turn_sector_3_to_4:
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
                    if now - started_at > 5.0 and boat_speed < 0.10 and throttle_pwm > 1520:
                        if stuck_timer is None:
                            stuck_timer = now
                        elif now - stuck_timer > 4.0:
                            unstuck_until = now + 1.5
                            stuck_timer = None
                    else:
                        stuck_timer = None

                    if now < unstuck_until:
                        # Manuver mundur darurat untuk lepas dari rintangan/dinding
                        steering_pwm = 1200
                        throttle_pwm = 1420
                        nav_state = "UNSTUCK_REVERSE"
                        nav_target_info = "KAPAL TERJEBAK -> Manuver Mundur Darurat"
                    # Wall safety boundary & Immediate Stop
                    px = telemetry.get("x") if telemetry else None
                    py = telemetry.get("y") if telemetry else None
                    if px is not None and py is not None:
                        if abs(px) >= 13.80 or abs(py) >= 13.80:
                            print("\n[E-STOP] Sensor pembatas kolam aktif: menutup script vision_test.py untuk hemat waktu.")
                            break
                        if px > 11.5 or py > 11.5 or px < -11.5 or py < -11.5:
                            steering_pwm = min(steering_pwm, 1280)
                            throttle_pwm = min(throttle_pwm, 1540)

                    try:
                        assert link is not None
                        link.send_override(steering_pwm, throttle_pwm)
                        mode = link.mode()
                        telemetry = link.telemetry()
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
