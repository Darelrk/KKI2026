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
    PatternMatcher,
    PatternSignature,
    RouteConfig,
    RouteController,
    RouteDecision,
    RouteState,
    STEERING_MAX_DELTA,
    compute_steering_pwm,
    select_target_x,
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
    return {
        "schema_version": 1,
        "asv_id": asv_id,
        "frame_id": frame_id,
        "captured_at": captured_at.isoformat(),
        "source_width": source_width,
        "source_height": source_height,
        "detections": [
            {
                "track_id": None,
                "label": detection.label,
                "confidence": detection.confidence,
                "x": (detection.x_center - detection.width / 2) / source_width,
                "y": (detection.y_center - detection.height / 2) / source_height,
                "width": detection.width / source_width,
                "height": detection.height / source_height,
            }
            for detection in detections
        ],
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


class PixhawkLink:
    """Minimal MAVLink connection for ArduRover RC overrides."""

    def __init__(self, endpoint: str, heartbeat_timeout: float = 10.0) -> None:
        try:
            from pymavlink import mavutil
        except ImportError as exc:
            raise RuntimeError(
                "pymavlink belum terpasang. Jalankan: "
                "python -m pip install pymavlink"
            ) from exc

        self._mavutil = mavutil
        self.connection = mavutil.mavlink_connection(
            endpoint,
            source_system=255,
            source_component=190,
        )
        heartbeat = self.connection.wait_heartbeat(timeout=heartbeat_timeout)
        if heartbeat is None:
            self.connection.close()
            raise TimeoutError(
                f"Tidak menerima heartbeat Pixhawk dari {endpoint}. "
                "Pastikan Mission Planner MAVLink forwarding aktif."
            )
        self._last_heartbeat = heartbeat
        self._last_servo_output = None
        self._last_rc_channels = None
        self._last_vfr_hud = None

        print(
            f"Pixhawk terhubung: system={self.connection.target_system}, "
            f"component={self.connection.target_component}, "
            f"mode={self.mode()}"
        )

    def mode(self) -> str:
        """Read and cache the latest heartbeat mode."""
        heartbeat = self.connection.recv_match(
            type="HEARTBEAT", blocking=False, timeout=0.01
        )
        if heartbeat is not None:
            self._last_heartbeat = heartbeat
        return str(self.connection.flightmode or "UNKNOWN").upper()

    def is_manual(self) -> bool:
        return self.mode() == "MANUAL"

    def telemetry(self) -> dict[str, Any]:
        """Return latest ArduPilot heartbeat, RC input, and PWM output."""
        for _ in range(20):
            message = self.connection.recv_match(
                type=["HEARTBEAT", "RC_CHANNELS", "SERVO_OUTPUT_RAW", "VFR_HUD"],
                blocking=False,
            )
            if message is None:
                break
            message_type = message.get_type()
            if message_type == "HEARTBEAT":
                self._last_heartbeat = message
            elif message_type == "RC_CHANNELS":
                self._last_rc_channels = message
            elif message_type == "SERVO_OUTPUT_RAW":
                self._last_servo_output = message
            elif message_type == "VFR_HUD":
                self._last_vfr_hud = message

        heartbeat = self._last_heartbeat
        armed = None
        base_mode = None
        system_status = None
        if heartbeat is not None:
            base_mode = int(heartbeat.base_mode)
            armed = bool(
                base_mode & self._mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
            )
            system_status = int(heartbeat.system_status)

        rc = self._last_rc_channels
        servo = self._last_servo_output
        return {
            "mode": self.mode(),
            "armed": armed,
            "base_mode": base_mode,
            "system_status": system_status,
            "heading_deg": vfr_hud_heading(self._last_vfr_hud),
            "rc1": getattr(rc, "chan1_raw", None),
            "rc3": getattr(rc, "chan3_raw", None),
            "servo1": getattr(servo, "servo1_raw", None),
            "servo3": getattr(servo, "servo3_raw", None),
        }

    def send_override(self, steering_pwm: int, throttle_pwm: int) -> None:
        """Override only RC1 steering and RC3 throttle.

        65535 tells ArduPilot to ignore the untouched channels. The script
        never sends an arm command.
        """
        unused = 65535
        self.connection.mav.rc_channels_override_send(
            self.connection.target_system,
            self.connection.target_component,
            int(clamp(steering_pwm, PWM_MIN, PWM_MAX)),
            unused,
            int(clamp(throttle_pwm, PWM_MIN, PWM_MAX)),
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
        )

    def release_override(self) -> None:
        """Release RC1 and RC3 overrides back to the normal input source."""
        unused = 65535
        self.connection.mav.rc_channels_override_send(
            self.connection.target_system,
            self.connection.target_component,
            0,
            unused,
            0,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,
            unused,

        )
    def close(self) -> None:
        self.connection.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deteksi buoy webcam dan kirim steering ke Pixhawk."
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
        "--camera", type=int, default=0, help="Nomor webcam OpenCV"
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
        "--throttle-pwm",
        type=int,
        default=1520,
        help="Throttle saat buoy terdeteksi; default 1520 untuk uji aman",
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
    return parser.parse_args()


def draw_detections(frame: Any, detections: Sequence[Detection], target_x: float | None) -> Any:
    """Draw model output for visual confirmation."""
    import cv2

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
            0.55,
            color,
            2,
        )

    if target_x is not None:
        cv2.line(
            frame,
            (int(target_x), 0),
            (int(target_x), frame.shape[0]),
            (255, 255, 0),
            2,
        )
    cv2.line(
        frame,
        (frame.shape[1] // 2, 0),
        (frame.shape[1] // 2, frame.shape[0]),
        (255, 255, 255),
        1,
    )
    return frame


def main() -> None:
    args = parse_args()
    if not 0.0 < args.conf <= 1.0:
        raise ValueError("--conf harus berada di antara 0 dan 1")
    if not 0.0 < args.vision_fps:
        raise ValueError("--vision-fps harus positif")
    if not 1500 <= args.throttle_pwm <= 1700:
        raise ValueError("--throttle-pwm harus 1500..1700 untuk uji awal")
    if args.duration < 0:
        raise ValueError("--duration tidak boleh negatif")

    try:
        from ultralytics import YOLO
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "Dependensi belum lengkap. Jalankan: "
            "python -m pip install ultralytics opencv-python pymavlink"
        ) from exc

    model_path = Path(args.model)
    if not model_path.is_file():
        raise FileNotFoundError(f"Model tidak ditemukan: {model_path}")

    print(f"Memuat model: {model_path}")
    model = YOLO(str(model_path))
    link = PixhawkLink(args.endpoint)
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
    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        logger.close()
        link.close()
        raise RuntimeError(f"Webcam {args.camera} tidak dapat dibuka")

    print("Tekan Q atau ESC untuk berhenti.")
    print(
        f"Throttle aktif ({args.throttle_pwm}) saat buoy terdeteksi, "
        "netral saat tidak ada target."
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
        frame_id = 0
        try:
            while not capture_stop.is_set():
                ok, frame = camera.read()
                if not ok:
                    raise RuntimeError("Gagal membaca frame webcam")
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
                target_x = select_target_x(last_detections)
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
                target_found = target_x is not None
                throttle_pwm = args.throttle_pwm if target_found else NEUTRAL_PWM

                mode = link.mode()
                if mode == "MANUAL":
                    link.send_override(steering_pwm, throttle_pwm)
                else:
                    link.release_override()
                telemetry = link.telemetry()

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
                        "vision": {
                            "detections": [
                                asdict(detection)
                                for detection in last_detections
                            ],
                            "target_x": target_x,
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
                    print(
                        f"frame={captured.frame_id} mode={mode} "
                        f"detections={labels} "
                        f"target_x={target_x if target_x is not None else '-'} "
                        f"steering={steering_pwm} throttle={throttle_pwm} "
                        f"metadata={metadata_published} "
                        f"servo1={telemetry['servo1']} "
                        f"servo3={telemetry['servo3']} "
                        f"armed={telemetry['armed']}"
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
            cv2.imshow("Vision Test - tekan Q untuk berhenti", preview)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
    finally:
        capture_stop.set()
        capture_queue.close()
        producer.join()
        camera.release()
        cv2.destroyAllWindows()
        try:
            link.send_override(NEUTRAL_PWM, NEUTRAL_PWM)
            time.sleep(0.1)
            link.release_override()
            logger.write(
                {
                    "event": "stop",
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
        finally:
            link.close()
            logger.close()
            if bridge is not None:
                bridge.publish_status(
                    online=False,
                    model_status="offline",
                    run_id=run_id,
                )
                bridge.close()
        print("Override dilepas; script berhenti dengan throttle netral.")


if __name__ == "__main__":
    main()
