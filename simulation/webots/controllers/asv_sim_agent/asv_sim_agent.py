"""Webots ASV Supervisor Controller with Gate Sensors, Buoy Touch Collision Detection & Per-Run Logging for KKI2026.

- Automatically creates a new timestamped folder for every simulation run under:
  D:/KKI2/KKI2026/simulation/logs/run_YYYYMMDD_HHMMSS/
- Saves live telemetry_track.jsonl, gate_scoring.json, buoy_collisions.jsonl, and summary_report.md.
- Tracks boat position across all 10 track gates (3 right slalom, 4 top corridor, 3 left slalom).
- Detects buoy touch collisions (error/penalty if boat touches any buoy).
- Verifies if the boat passes cleanly between each pair of buoys (2.0m width) or misses.
- Serves virtual Logitech camera frames over HTTP (/frame.jpg and /stream.mjpg).
- Exposes /status, /gates, and /collisions endpoints with live scoring and penalty tracking.
"""

from __future__ import annotations

import json
import math
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from controller import Supervisor
except ImportError:
    Supervisor = None

try:
    from webots_mcp_kit.agent import ControllerAgent
except ImportError:
    ControllerAgent = None


NEUTRAL_PWM = 1500
PWM_MIN = 1000
PWM_MAX = 2000
TIME_STEP = 16  # ms
WATER_PLANE_Z = 0.04  # m

BASE_LAT = -6.200000
BASE_LON = 106.816666
METERS_PER_DEG_LAT = 111320.0

# Buoy & Wall Collision Sensor Thresholds
BUOY_TOUCH_RADIUS = 0.40  # meters (boat half-width 0.15m + buoy radius 0.22m)
WALL_LIMIT_X = 13.80  # meters (pool boundary at +/- 15.0m minus boat bow distance)
WALL_LIMIT_Y = 13.80  # meters (pool boundary at +/- 15.0m minus boat bow distance)
# 10 Track Gates based on official KKI 30x30m layout (2.0m buoy gap)
TRACK_GATES = [
    {
        "id": "gate_1",
        "name": "Gate 1 (Slalom Kanan 1)",
        "buoy_red": [10.0, -6.0],
        "buoy_green": [12.0, -6.0],
        "type": "horizontal",
        "sector": "right",
        "x_min": 10.0,
        "x_max": 12.0,
        "y": -6.0,
    },
    {
        "id": "gate_2",
        "name": "Gate 2 (Slalom Kanan 2)",
        "buoy_red": [8.0, 0.0],
        "buoy_green": [10.0, 0.0],
        "type": "horizontal",
        "sector": "right",
        "x_min": 8.0,
        "x_max": 10.0,
        "y": 0.0,
    },
    {
        "id": "gate_3",
        "name": "Gate 3 (Slalom Kanan 3)",
        "buoy_red": [10.0, 6.0],
        "buoy_green": [12.0, 6.0],
        "type": "horizontal",
        "sector": "right",
        "x_min": 10.0,
        "x_max": 12.0,
        "y": 6.0,
    },
    {
        "id": "gate_4",
        "name": "Gate 4 (Koridor Atas 1)",
        "buoy_red": [6.0, 9.0],
        "buoy_green": [6.0, 11.0],
        "type": "vertical",
        "sector": "top",
        "x": 6.0,
        "y_min": 9.0,
        "y_max": 11.0,
    },
    {
        "id": "gate_5",
        "name": "Gate 5 (Koridor Atas 2)",
        "buoy_red": [2.0, 9.0],
        "buoy_green": [2.0, 11.0],
        "type": "vertical",
        "sector": "top",
        "x": 2.0,
        "y_min": 9.0,
        "y_max": 11.0,
    },
    {
        "id": "gate_6",
        "name": "Gate 6 (Koridor Atas 3)",
        "buoy_red": [-2.0, 9.0],
        "buoy_green": [-2.0, 11.0],
        "type": "vertical",
        "sector": "top",
        "x": -2.0,
        "y_min": 9.0,
        "y_max": 11.0,
    },
    {
        "id": "gate_7",
        "name": "Gate 7 (Koridor Atas 4)",
        "buoy_red": [-6.0, 9.0],
        "buoy_green": [-6.0, 11.0],
        "type": "vertical",
        "sector": "top",
        "x": -6.0,
        "y_min": 9.0,
        "y_max": 11.0,
    },
    {
        "id": "gate_8",
        "name": "Gate 8 (Slalom Kiri 1)",
        "buoy_red": [-10.0, 6.0],
        "buoy_green": [-12.0, 6.0],
        "type": "horizontal",
        "sector": "left",
        "x_min": -12.0,
        "x_max": -10.0,
        "y": 6.0,
    },
    {
        "id": "gate_9",
        "name": "Gate 9 (Slalom Kiri 2)",
        "buoy_red": [-8.0, 0.0],
        "buoy_green": [-10.0, 0.0],
        "type": "horizontal",
        "sector": "left",
        "x_min": -10.0,
        "x_max": -8.0,
        "y": 0.0,
    },
    {
        "id": "gate_10",
        "name": "Gate 10 (Slalom Kiri 3)",
        "buoy_red": [-10.0, -6.0],
        "buoy_green": [-12.0, -6.0],
        "type": "horizontal",
        "sector": "left",
        "x_min": -12.0,
        "x_max": -10.0,
        "y": -6.0,
    },
]

# All individual buoys in the arena for touch collision detection
ALL_ARENA_BUOYS = []
for g in TRACK_GATES:
    ALL_ARENA_BUOYS.append({"name": f"{g['id']}_red", "pos": g["buoy_red"]})
    ALL_ARENA_BUOYS.append({"name": f"{g['id']}_green", "pos": g["buoy_green"]})


class RunLogger:
    """Manages automatic per-run directory logging for every simulation trial."""

    def __init__(self, base_dir: Path | str = "D:/KKI2/KKI2026/simulation/logs") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.test_number = 1 + sum(
            1 for path in self.base_dir.glob("run_*") if path.is_dir()
        )
        self.started_at = datetime.now(timezone.utc)
        self.started_at_local = self.started_at.astimezone()
        self.run_id = self.started_at.strftime("run_%Y%m%d_%H%M%S")
        self.run_dir = self.base_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.track_file = open(self.run_dir / "telemetry_track.jsonl", "a", encoding="utf-8")
        self.buoy_collisions_file = open(self.run_dir / "buoy_collisions.jsonl", "a", encoding="utf-8")
        self.wall_collisions_file = open(self.run_dir / "wall_collisions.jsonl", "a", encoding="utf-8")
        self.scoring_file = self.run_dir / "gate_scoring.json"
        self.report_file = self.run_dir / "summary_report.md"
        print(
            f"[LOGGER] Test #{self.test_number} started at "
            f"{self.started_at_local.strftime('%Y-%m-%d %H:%M:%S %Z')} | "
            f"Session log directory: {self.run_dir}"
        )

    def start_new_run(self) -> None:
        """Close the current files and begin a fresh log session."""
        self.track_file.close()
        self.buoy_collisions_file.close()
        self.wall_collisions_file.close()
        self.test_number += 1
        self.started_at = datetime.now(timezone.utc)
        self.started_at_local = self.started_at.astimezone()
        base_run_id = self.started_at.strftime("run_%Y%m%d_%H%M%S")
        self.run_id = base_run_id
        suffix = 2
        while (self.base_dir / self.run_id).exists():
            self.run_id = f"{base_run_id}_{suffix}"
            suffix += 1
        self.run_dir = self.base_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.track_file = open(self.run_dir / "telemetry_track.jsonl", "a", encoding="utf-8")
        self.buoy_collisions_file = open(self.run_dir / "buoy_collisions.jsonl", "a", encoding="utf-8")
        self.wall_collisions_file = open(self.run_dir / "wall_collisions.jsonl", "a", encoding="utf-8")
        self.scoring_file = self.run_dir / "gate_scoring.json"
        self.report_file = self.run_dir / "summary_report.md"
        print(
            f"[LOGGER] Test #{self.test_number} started at "
            f"{self.started_at_local.strftime('%Y-%m-%d %H:%M:%S %Z')} | "
            f"Session log directory: {self.run_dir}"
        )

    def log_point(
        self,
        x: float,
        y: float,
        heading: float,
        speed: float,
        steer_pwm: int,
        thr_pwm: int,
    ) -> None:
        record = {
            "test_number": self.test_number,
            "test_started_at": self.started_at_local.isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "x": round(x, 4),
            "y": round(y, 4),
            "heading_deg": round(heading, 2),
            "speed_mps": round(speed, 2),
            "steering_pwm": steer_pwm,
            "throttle_pwm": thr_pwm,
        }
        self.track_file.write(json.dumps(record) + "\n")
        self.track_file.flush()

    def log_buoy_collision(self, buoy_name: str, x: float, y: float, dist: float) -> None:
        record = {
            "test_number": self.test_number,
            "test_started_at": self.started_at_local.isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "BUOY_TOUCH_ERROR",
            "buoy_name": buoy_name,
            "boat_x": round(x, 4),
            "boat_y": round(y, 4),
            "distance_m": round(dist, 4),
        }
        self.buoy_collisions_file.write(json.dumps(record) + "\n")
        self.buoy_collisions_file.flush()

    def log_wall_collision(self, wall_name: str, x: float, y: float, speed: float) -> None:
        record = {
            "test_number": self.test_number,
            "test_started_at": self.started_at_local.isoformat(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "WALL_COLLISION_ERROR",
            "wall_name": wall_name,
            "boat_x": round(x, 4),
            "boat_y": round(y, 4),
            "speed_mps": round(speed, 2),
        }
        self.wall_collisions_file.write(json.dumps(record) + "\n")
        self.wall_collisions_file.flush()
    def save_gate_scoring(self, scoring_data: dict[str, object]) -> None:
        payload = dict(scoring_data)
        payload["test_number"] = self.test_number
        payload["test_started_at"] = self.started_at_local.isoformat()
        with open(self.scoring_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def write_summary_report(
        self,
        scoring_data: dict[str, object],
        buoy_cols: list[dict[str, object]],
        wall_cols: list[dict[str, object]],
        final_x: float,
        final_y: float,
    ) -> None:
        now = datetime.now(timezone.utc)
        duration_s = (now - self.started_at).total_seconds()
        passed = scoring_data.get("passed_valid", 0)
        missed = scoring_data.get("missed", 0)
        total = scoring_data.get("total_gates", 10)
        score_pct = scoring_data.get("score_percent", 0.0)
        buoy_touch_count = len(buoy_cols)
        wall_touch_count = len(wall_cols)

        lines = [
            f"# Laporan Hasil Uji Simulasi ASV KKI 2026 - {self.run_id}",
            "",
            f"- **No. Uji**: {self.test_number}",
            f"- **Jam Mulai (lokal)**: {self.started_at_local.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"- **Waktu Mulai (UTC)**: {self.started_at.isoformat()}",
            f"- **Waktu Update (UTC)**: {now.isoformat()}",
            f"- **Durasi Sesi**: {duration_s:.1f} detik",
            f"- **Posisi Akhir Kapal**: X = {final_x:.2f} m, Y = {final_y:.2f} m",
            f"- **Skor Validasi Gate**: **{passed} / {total} Gate ({score_pct}%)**",
            f"- **Gate Terlewati (Valid)**: {passed}",
            f"- **Gate Missed (Luar)**: {missed}",
            f"- **Sensor Sentuh Buoy (Buoy Collisions)**: **{buoy_touch_count} Kali**",
            f"- **Sensor Tabrak Pembatas (Wall Collisions)**: **{wall_touch_count} Kali**",
            "",
            "## 1. Detail Pelanggaran Tabrakan / Sentuh Buoy",
            "",
        ]
        if buoy_cols:
            lines.append("| No | Nama Buoy | Waktu Sentuh (UTC) | Posisi Kapal [X, Y] | Jarak Kontak (m) |")
            lines.append("|---|---|---|---|---|")
            for idx, col in enumerate(buoy_cols, 1):
                lines.append(
                    f"| {idx} | {col['buoy_name']} | {col['timestamp']} | [{col['boat_x']}, {col['boat_y']}] | {col['distance_m']} |"
                )
        else:
            lines.append("*Bersih: Tidak ada buoy yang tersentuh/ditabrak kapal (Zero Buoy Touch).*")

        lines.extend([
            "",
            "## 2. Detail Tabrakan Dinding / Pembatas Kolam",
            "",
        ])
        if wall_cols:
            lines.append("| No | Nama Dinding Pembatas | Waktu Tabrak (UTC) | Posisi Kapal [X, Y] | Kecepatan Benturan (m/s) |")
            lines.append("|---|---|---|---|---|")
            for idx, col in enumerate(wall_cols, 1):
                lines.append(
                    f"| {idx} | {col['wall_name']} | {col['timestamp']} | [{col['boat_x']}, {col['boat_y']}] | {col.get('speed_mps', 0.0)} |"
                )
        else:
            lines.append("*Bersih: Kapal tidak pernah menabrak dinding pembatas kolam (Zero Wall Collision).*")

        lines.extend([
            "",
            "## Detail Setiap Gerbang Buoy (Jarak 2.0m)",
            "",
            "| ID Gerbang | Nama Gate | Status | Koordinat Crossing | Waktu (s) |",
            "|---|---|---|---|---|",
        ])
        gates = scoring_data.get("gates", {})
        for gid, g in gates.items():
            stat = g.get("status", "PENDING")
            coord = g.get("crossing_coord")
            coord_str = f"[{coord[0]}, {coord[1]}]" if coord else "-"
            crossed_at = g.get("crossed_at")
            time_str = f"{crossed_at:.1f}" if crossed_at else "-"
            badge = (
                "PASSED (VALID)"
                if stat == "PASSED_VALID"
                else ("MISSED" if stat == "MISSED_OUTSIDE" else "PENDING")
            )
            lines.append(f"| {gid} | {g.get('name')} | **{badge}** | {coord_str} | {time_str} |")

        with open(self.report_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


run_logger = RunLogger()


class GateSensorTracker:
    """Track gate line crossings, buoy touch collisions, and pool wall collisions."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.gate_results: dict[str, dict[str, object]] = {
            g["id"]: {
                "name": g["name"],
                "status": "PENDING",
                "crossed_at": None,
                "crossing_coord": None,
            }
            for g in TRACK_GATES
        }
        self.buoy_collisions: list[dict[str, object]] = []
        self.wall_collisions: list[dict[str, object]] = []
        self.touched_buoys: set[str] = set()
        self.touched_walls: set[str] = set()

    def reset(self) -> None:
        with self.lock:
            self.gate_results = {
                g["id"]: {
                    "name": g["name"],
                    "status": "PENDING",
                    "crossed_at": None,
                    "crossing_coord": None,
                }
                for g in TRACK_GATES
            }
            self.buoy_collisions.clear()
            self.wall_collisions.clear()
            self.touched_buoys.clear()
            self.touched_walls.clear()

    def check_buoy_touch(self, x: float, y: float) -> None:
        """Check if the boat touches or violates the safety zone of any buoy."""
        for b in ALL_ARENA_BUOYS:
            bname = b["name"]
            bx, by = b["pos"]
            dist = math.hypot(x - bx, y - by)

            if dist < BUOY_TOUCH_RADIUS:
                if bname not in self.touched_buoys:
                    self.touched_buoys.add(bname)
                    record = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "buoy_name": bname,
                        "boat_x": round(x, 2),
                        "boat_y": round(y, 2),
                        "distance_m": round(dist, 3),
                    }
                    with self.lock:
                        self.buoy_collisions.append(record)
                    run_logger.log_buoy_collision(bname, x, y, dist)
                    print(f"==================================================")
                    print(f"[SENSOR BUOY] !! Kapal MENABRAK BUOY: {bname}!")
                    print(f"  Posisi: X={x:.2f}, Y={y:.2f} (Jarak Kontak={dist:.2f}m)")
                    print(f"==================================================")

    def check_wall_collision(self, x: float, y: float, speed: float) -> None:
        """Check if the boat hits the outer pool boundaries (30x30m)."""
        wall_hit = None
        if y >= WALL_LIMIT_Y:
            wall_hit = "DINDING_UTARA_NORTH"
        elif y <= -WALL_LIMIT_Y:
            wall_hit = "DINDING_SELATAN_SOUTH"
        elif x >= WALL_LIMIT_X:
            wall_hit = "DINDING_TIMUR_EAST"
        elif x <= -WALL_LIMIT_X:
            wall_hit = "DINDING_BARAT_WEST"

        if wall_hit:
            wall_key = f"{wall_hit}_{int(time.monotonic() // 2)}"
            if wall_key not in self.touched_walls:
                self.touched_walls.add(wall_key)
                record = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "wall_name": wall_hit,
                    "boat_x": round(x, 2),
                    "boat_y": round(y, 2),
                    "speed_mps": round(speed, 2),
                }
                with self.lock:
                    self.wall_collisions.append(record)
                run_logger.log_wall_collision(wall_hit, x, y, speed)
                print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                print(f"[SENSOR PEMBATAS] !! Kapal MENABRAK PEMBATAS: {wall_hit}!")
                print(f"  Posisi: X={x:.2f}, Y={y:.2f} (Speed={speed:.2f}m/s)")
                print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    def check_crossing(self, x_prev: float, y_prev: float, x_curr: float, y_curr: float, speed: float = 0.0) -> None:
        now = time.monotonic()
        updated = False

        # 1. Check buoy touch sensor
        self.check_buoy_touch(x_curr, y_curr)
        # 2. Check pool boundary wall collision sensor
        self.check_wall_collision(x_curr, y_curr, speed)
        with self.lock:
            for g in TRACK_GATES:
                gid = g["id"]
                if self.gate_results[gid]["status"] != "PENDING":
                    continue

                sector = g.get("sector")
                # Spatial sector isolation
                if sector == "right" and (x_curr < 2.0 or x_prev < 2.0):
                    continue
                if sector == "left" and (x_curr > -2.0 or x_prev > -2.0):
                    continue
                if sector == "top" and (y_curr < 5.0 or y_prev < 5.0):
                    continue

                if g["type"] == "horizontal":
                    y_line = g["y"]
                    if (y_prev < y_line <= y_curr) or (y_prev > y_line >= y_curr):
                        ratio = (y_line - y_prev) / (y_curr - y_prev) if y_curr != y_prev else 0.0
                        x_cross = x_prev + ratio * (x_curr - x_prev)

                        min_x = min(g["x_min"], g["x_max"])
                        max_x = max(g["x_min"], g["x_max"])

                        if min_x - 0.25 <= x_cross <= max_x + 0.25:
                            self.gate_results[gid]["status"] = "PASSED_VALID"
                            self.gate_results[gid]["crossed_at"] = now
                            self.gate_results[gid]["crossing_coord"] = [round(x_cross, 2), y_line]
                            print(f"[SENSOR BUOY] >> {g['name']}: PASSED (VALID)! X={x_cross:.2f}, Y={y_line:.2f}")
                        else:
                            self.gate_results[gid]["status"] = "MISSED_OUTSIDE"
                            self.gate_results[gid]["crossed_at"] = now
                            self.gate_results[gid]["crossing_coord"] = [round(x_cross, 2), y_line]
                            print(f"[SENSOR BUOY] !! {g['name']}: MISSED (OUTSIDE)! X={x_cross:.2f}, Y={y_line:.2f}")
                        updated = True

                elif g["type"] == "vertical":
                    x_line = g["x"]
                    if (x_prev > x_line >= x_curr) or (x_prev < x_line <= x_curr):
                        ratio = (x_line - x_prev) / (x_curr - x_prev) if x_curr != x_prev else 0.0
                        y_cross = y_prev + ratio * (y_curr - y_prev)

                        min_y = min(g["y_min"], g["y_max"])
                        max_y = max(g["y_min"], g["y_max"])

                        if min_y - 0.25 <= y_cross <= max_y + 0.25:
                            self.gate_results[gid]["status"] = "PASSED_VALID"
                            self.gate_results[gid]["crossed_at"] = now
                            self.gate_results[gid]["crossing_coord"] = [x_line, round(y_cross, 2)]
                            print(f"[SENSOR BUOY] >> {g['name']}: PASSED (VALID)! X={x_line:.2f}, Y={y_cross:.2f}")
                        else:
                            self.gate_results[gid]["status"] = "MISSED_OUTSIDE"
                            self.gate_results[gid]["crossed_at"] = now
                            self.gate_results[gid]["crossing_coord"] = [x_line, round(y_cross, 2)]
                            print(f"[SENSOR BUOY] !! {g['name']}: MISSED (OUTSIDE)! X={x_line:.2f}, Y={y_cross:.2f}")
                        updated = True

        if updated or self.buoy_collisions or self.wall_collisions:
            snap = self.snapshot()
            run_logger.save_gate_scoring(snap)
            run_logger.write_summary_report(snap, list(self.buoy_collisions), list(self.wall_collisions), x_curr, y_curr)

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            passed_count = sum(1 for v in self.gate_results.values() if v["status"] == "PASSED_VALID")
            missed_count = sum(1 for v in self.gate_results.values() if v["status"] == "MISSED_OUTSIDE")
            return {
                "run_id": run_logger.run_id,
                "log_dir": str(run_logger.run_dir),
                "total_gates": len(TRACK_GATES),
                "passed_valid": passed_count,
                "missed": missed_count,
                "buoy_touches": len(self.buoy_collisions),
                "wall_touches": len(self.wall_collisions),
                "score_percent": round((passed_count / len(TRACK_GATES)) * 100, 1),
                "gates": dict(self.gate_results),
                "buoy_collisions": list(self.buoy_collisions),
                "wall_collisions": list(self.wall_collisions),
            }


class SharedSimState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.latest_jpeg: bytes = b""
        self.steering_pwm: int = NEUTRAL_PWM
        self.throttle_pwm: int = NEUTRAL_PWM
        self.last_command_at: float = time.monotonic()
        self.reset_requested: bool = False
        self.x: float = 10.0
        self.y: float = -11.5
        self.heading_deg: float = 360.0
        self.speed_mps: float = 0.0
        self.yaw_rad: float = math.pi / 2.0
        self.mode: str = "MANUAL"
        self.armed: bool = True


def draw_google_maps_nav_overlay(
    img,
    x: float,
    y: float,
    heading: float,
    speed: float,
    steer_pwm: int,
    thr_pwm: int,
    gates_data: dict[str, object],
) -> None:
    """Draw Google Maps / AR Lane Assist navigation overlay showing centerline between buoys."""
    try:
        import cv2
        import numpy as np

        h, w = img.shape[:2]
        overlay = img.copy()

        # 1. Calculate steering deflection & target guide point
        steer_norm = (steer_pwm - NEUTRAL_PWM) / 400.0  # -1.0 (left) .. +1.0 (right)
        target_x_top = int(w / 2 + steer_norm * (w * 0.38))
        target_y_top = int(h * 0.40)

        # 2. Draw Translucent Google Maps Blue/Cyan Navigation Corridor Polygon
        bottom_left = (int(w * 0.22), h - 10)
        bottom_right = (int(w * 0.78), h - 10)
        top_left = (max(20, target_x_top - int(w * 0.15)), target_y_top)
        top_right = (min(w - 20, target_x_top + int(w * 0.15)), target_y_top)

        corridor_pts = np.array([bottom_left, top_left, top_right, bottom_right], np.int32)
        cv2.fillPoly(overlay, [corridor_pts], (235, 140, 20))  # Google Maps blue/cyan tint

        # 3. Draw Lane Boundary Guidance Rails (Red on Left, Green on Right)
        cv2.line(overlay, bottom_left, top_left, (0, 0, 255), 4, cv2.LINE_AA)  # Red buoy rail
        cv2.line(overlay, bottom_right, top_right, (0, 255, 0), 4, cv2.LINE_AA)  # Green buoy rail

        # 4. Centerline Glowing Path (Google Maps Dashed Cyan Navigation Line)
        bottom_center = (int(w / 2), h - 10)
        top_center = (target_x_top, target_y_top)
        cv2.line(overlay, bottom_center, top_center, (255, 230, 0), 4, cv2.LINE_AA)

        # Marching Chevron Arrows (>>>) along Centerline
        for t in [0.25, 0.50, 0.75]:
            cx = int(bottom_center[0] + t * (top_center[0] - bottom_center[0]))
            cy = int(bottom_center[1] + t * (top_center[1] - bottom_center[1]))
            wing_w = int(14 * (1.0 - t * 0.4))
            wing_h = int(10 * (1.0 - t * 0.4))
            cv2.line(overlay, (cx - wing_w, cy + wing_h), (cx, cy), (255, 255, 255), 3, cv2.LINE_AA)
            cv2.line(overlay, (cx + wing_w, cy + wing_h), (cx, cy), (255, 255, 255), 3, cv2.LINE_AA)

        # 5. Target Pin Marker at Gate Center (Google Maps Pin)
        cv2.circle(overlay, top_center, 12, (0, 230, 255), -1, cv2.LINE_AA)
        cv2.circle(overlay, top_center, 16, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(overlay, top_center, 4, (0, 0, 255), -1, cv2.LINE_AA)

        # Alpha Blend Corridor into Image (45% opacity)
        cv2.addWeighted(overlay, 0.45, img, 0.55, 0, img)

        # 6. Top Google Maps Navigation Header Bar
        banner_w, banner_h = 420, 44
        bx = int((w - banner_w) / 2)
        by = 12

        # Check if Wall Safety Sensor is triggered (near or hitting boundary)
        wall_alert = (abs(x) >= 13.8 or abs(y) >= 13.8)
        if wall_alert:
            cv2.rectangle(img, (bx, by), (bx + banner_w, by + banner_h), (0, 0, 180), -1)
            cv2.rectangle(img, (bx, by), (bx + banner_w, by + banner_h), (0, 255, 255), 2)
            cv2.putText(img, "[E-STOP] SENSOR TEMBOK: OTOMATIS BERHENTI", (bx + 14, by + 28), cv2.FONT_HERSHEY_DUPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
        else:
            cv2.rectangle(img, (bx, by), (bx + banner_w, by + banner_h), (25, 30, 35), -1)
            cv2.rectangle(img, (bx, by), (bx + banner_w, by + banner_h), (0, 200, 255), 2)
            if steer_norm < -0.15:
                nav_icon = "<--"
                nav_text = "Belok KIRI ke Garis Tengah"
            elif steer_norm > 0.15:
                nav_icon = "-->"
                nav_text = "Belok KANAN ke Garis Tengah"
            else:
                nav_icon = "^"
                nav_text = "LURUS di Garis Tengah (Optimal)"
            cv2.putText(img, f"{nav_icon}  {nav_text}", (bx + 16, by + 28), cv2.FONT_HERSHEY_DUPLEX, 0.50, (255, 255, 255), 1, cv2.LINE_AA)
        # 7. Bottom Telemetry & Gate Status HUD
        cv2.rectangle(img, (10, h - 36), (190, h - 10), (15, 20, 25), -1)
        cv2.rectangle(img, (10, h - 36), (190, h - 10), (80, 100, 120), 1)
        cv2.putText(img, f"SPD: {speed:.1f}m/s | THR: {thr_pwm}", (16, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 200), 1, cv2.LINE_AA)

        passed_g = gates_data.get("passed_valid", 0)
        cv2.rectangle(img, (w - 180, h - 36), (w - 10, h - 10), (15, 20, 25), -1)
        cv2.rectangle(img, (w - 180, h - 36), (w - 10, h - 10), (80, 100, 120), 1)
        cv2.putText(img, f"GATE: {passed_g}/10 | HDG: {heading:3.0f}", (w - 172, h - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 220, 0), 1, cv2.LINE_AA)

    except Exception:
        pass
state = SharedSimState()


class CameraStreamHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        if self.path != "/reset":
            self.send_error(404, "Not Found")
            return
        with state.lock:
            state.reset_requested = True
        payload = b'{"status":"reset_requested"}'
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path in ("/frame.jpg", "/camera/surface"):
            with state.lock:
                jpeg = state.latest_jpeg
            if not jpeg:
                self.send_error(503, "Frame not ready")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpeg)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(jpeg)
            return

        if self.path in ("/stream.mjpg", "/stream/atas", "/video"):
            try:
                self.send_response(200)
                self.send_header(
                    "Content-Type", "multipart/x-mixed-replace; boundary=frame"
                )
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                while True:
                    with state.lock:
                        jpeg = state.latest_jpeg
                    if jpeg:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    time.sleep(0.04)  # ~25 FPS
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.error, OSError, Exception):
                return
        if self.path == "/status":
            with state.lock:
                status_payload = {
                    "status": "running",
                    "steering_pwm": state.steering_pwm,
                    "throttle_pwm": state.throttle_pwm,
                    "x": state.x,
                    "y": state.y,
                    "heading_deg": state.heading_deg,
                    "speed_mps": state.speed_mps,
                    "gate_tracking": self.gate_tracker.snapshot(),
                }
            payload_bytes = json.dumps(status_payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload_bytes)))
            self.end_headers()
            self.wfile.write(payload_bytes)
            return

        if self.path in ("/gates", "/scoring", "/collisions"):
            payload_bytes = json.dumps(self.gate_tracker.snapshot(), indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload_bytes)))
            self.end_headers()
            self.wfile.write(payload_bytes)
            return

        self.send_error(404, "Not Found")


def start_http_stream_server(
    port: int = 8889,
    gate_tracker: GateSensorTracker | None = None,
) -> ThreadingHTTPServer:
    class BoundCameraStreamHandler(CameraStreamHandler):
        def __init__(self, request, client_address, server):
            self.gate_tracker = gate_tracker
            super().__init__(request, client_address, server)

    server = ThreadingHTTPServer(("0.0.0.0", port), BoundCameraStreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="webots-http-stream")
    thread.start()
    return server


def start_udp_actuator_receiver(port: int = 9090) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Fix Windows UDP WSAECONNRESET (WinError 10054)
        SIO_UDP_CONNRESET = 0x9800000C
        sock.ioctl(SIO_UDP_CONNRESET, False)
    except Exception:
        pass
    sock.bind(("0.0.0.0", port))
    sock.setblocking(False)

    def loop() -> None:
        while True:
            try:
                data, _ = sock.recvfrom(512)
                text = data.decode("utf-8", errors="ignore").strip()
                now = time.monotonic()
                if text.startswith("{"):
                    obj = json.loads(text)
                    steer = int(obj.get("steering_pwm", state.steering_pwm))
                    thr = int(obj.get("throttle_pwm", state.throttle_pwm))
                else:
                    parts = text.split(",")
                    steer = int(parts[0])
                    thr = int(parts[1]) if len(parts) > 1 else NEUTRAL_PWM

                with state.lock:
                    state.steering_pwm = max(PWM_MIN, min(PWM_MAX, steer))
                    state.throttle_pwm = max(PWM_MIN, min(PWM_MAX, thr))
                    state.last_command_at = now
            except (BlockingIOError, socket.error):
                time.sleep(0.002)
            except Exception:
                time.sleep(0.005)
                time.sleep(0.01)

    thread = threading.Thread(target=loop, daemon=True, name="webots-actuator-udp")
    thread.start()


def start_mavlink_bridge_server(
    port: int = 14550,
    gate_tracker: GateSensorTracker | None = None,
) -> None:
    try:
        from pymavlink import mavutil
    except ImportError:
        return

    mav = mavutil.mavlink_connection(
        f"udpout:127.0.0.1:{port}",
        source_system=1,
        source_component=1,
    )

    def mav_loop() -> None:
        last_hb = 0.0
        last_pos = 0.0
        while True:
            now = time.monotonic()
            with state.lock:
                lat = BASE_LAT + (state.y / METERS_PER_DEG_LAT)
                lon = BASE_LON + (
                    state.x
                    / (METERS_PER_DEG_LAT * math.cos(math.radians(BASE_LAT)))
                )
                hdg = state.heading_deg
                spd = state.speed_mps
                steer_pwm = state.steering_pwm
                thr_pwm = state.throttle_pwm
            gate_count = (
                int(gate_tracker.snapshot()["passed_valid"])
                if gate_tracker is not None
                else 0
            )

            # 1 Hz HEARTBEAT
            if now - last_hb >= 1.0:
                mav.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GROUND_ROVER,
                    mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
                    mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
                    | mavutil.mavlink.MAV_MODE_FLAG_MANUAL_INPUT_ENABLED
                    | mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED,
                    0,
                    mavutil.mavlink.MAV_STATE_ACTIVE,
                )
                last_hb = now

            # 10 Hz Telemetry
            if now - last_pos >= 0.1:
                mav.mav.global_position_int_send(
                    int(now * 1000) & 0xFFFFFFFF,
                    int(lat * 1e7),
                    int(lon * 1e7),
                    10000,
                    0,
                    int(spd * 100 * math.cos(math.radians(hdg))),
                    int(spd * 100 * math.sin(math.radians(hdg))),
                    0,
                    int(hdg * 100),
                )
                mav.mav.vfr_hud_send(
                    spd,
                    spd,
                    int(hdg),
                    50,
                    0.0,
                    0.0,
                )
                mav.mav.named_value_int_send(
                    int(now * 1000) & 0xFFFFFFFF,
                    b"gate_count",
                    gate_count,
                )
                mav.mav.rc_channels_raw_send(
                    int(now * 1000) & 0xFFFFFFFF,
                    0,
                    steer_pwm,
                    1500,
                    thr_pwm,
                    1500,
                    1500,
                    1500,
                    1500,
                    1500,
                    255,
                )
                last_pos = now

            time.sleep(0.02)

    thread = threading.Thread(target=mav_loop, daemon=True, name="webots-mavlink-bridge")
    thread.start()


def main() -> None:
    if Supervisor is None:
        print("Webots Supervisor module not loaded. Run from inside Webots.")
        return

    robot = Supervisor()
    time_step = int(robot.getBasicTimeStep())
    if time_step <= 0:
        time_step = TIME_STEP

    boat_node = robot.getSelf()
    trans_field = boat_node.getField("translation") if boat_node else None
    rot_field = boat_node.getField("rotation") if boat_node else None

    # Actuators
    rudder_motor = robot.getDevice("rudder_motor")
    thruster_motor = robot.getDevice("thruster_motor")

    if thruster_motor is not None:
        thruster_motor.setPosition(float("inf"))
        thruster_motor.setVelocity(0.0)

    # Sensors
    surface_camera = robot.getDevice("surface_camera")
    if surface_camera is not None:
        surface_camera.enable(time_step)

    gps = robot.getDevice("gps")
    if gps is not None:
        gps.enable(time_step)

    compass = robot.getDevice("compass")
    if compass is not None:
        compass.enable(time_step)

    gate_tracker = GateSensorTracker()
    agent = None
    if ControllerAgent is not None:
        try:
            agent = ControllerAgent.from_robot(robot, default_camera="surface_camera")
        except Exception:
            agent = None

    start_http_stream_server(8889, gate_tracker)
    start_udp_actuator_receiver(9090)
    start_mavlink_bridge_server(14550, gate_tracker)

    print("==================================================")
    print(f" - Test No   : {run_logger.test_number}")
    print(
        " - Start Time : "
        f"{run_logger.started_at_local.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    )
    print(" ASV Gate Sensor, Collision & Logging Supervisor Active")
    print(f" - Run Folder  : {run_logger.run_dir}")
    print(" - Stream URL  : http://127.0.0.1:8889/stream.mjpg")
    print(" - Gate Scoring: http://127.0.0.1:8889/gates")
    print(" - Touch Radius: 0.40m (Boat MUST NOT touch buoys)")
    print(" - Total Gates : 10 gates (2.0m width)")
    print("==================================================")

    # Initial state from world
    pos_x = 10.0
    pos_y = -11.5
    yaw_rad = math.pi / 2.0  # Facing North
    current_speed = 0.0
    last_loop_time = time.monotonic()
    last_point_log = 0.0

    if trans_field:
        init_pos = trans_field.getSFVec3f()
        pos_x = init_pos[0]
        pos_y = init_pos[1]
    if rot_field:
        init_rot = rot_field.getSFRotation()
        if len(init_rot) >= 4 and abs(init_rot[2]) > 0.5:
            yaw_rad = init_rot[3]

    prev_x = pos_x
    prev_y = pos_y

    while robot.step(time_step) != -1:
        now = time.monotonic()
        dt = min(0.05, max(0.005, now - last_loop_time))
        last_loop_time = now

        with state.lock:
            reset_requested = state.reset_requested
            state.reset_requested = False
        if reset_requested:
            if trans_field is not None:
                trans_field.setSFVec3f([10.0, -11.5, WATER_PLANE_Z])
            if rot_field is not None:
                rot_field.setSFRotation([0.0, 0.0, 1.0, math.pi / 2.0])
            if rudder_motor is not None:
                rudder_motor.setPosition(0.0)
            if thruster_motor is not None:
                thruster_motor.setVelocity(0.0)
            run_logger.start_new_run()
            gate_tracker.reset()
            pos_x = 10.0
            pos_y = -11.5
            yaw_rad = math.pi / 2.0
            current_speed = 0.0
            prev_x = pos_x
            prev_y = pos_y
            with state.lock:
                state.steering_pwm = NEUTRAL_PWM
                state.throttle_pwm = NEUTRAL_PWM
                state.x = pos_x
                state.y = pos_y
                state.heading_deg = 0.0
                state.speed_mps = 0.0
                state.last_command_at = now
            continue

        if agent is not None:
            agent.begin_step()

        # Read camera frame & convert to JPEG for streaming
        raw_image = None
        if surface_camera is not None:
            raw_image = surface_camera.getImage()
            if raw_image:
                try:
                    import cv2
                    import numpy as np

                    width = surface_camera.getWidth()
                    height = surface_camera.getHeight()
                    img_np = np.frombuffer(raw_image, dtype=np.uint8).reshape(
                        (height, width, 4)
                    )
                    bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
                    snap = gate_tracker.snapshot()
                    draw_google_maps_nav_overlay(
                        bgr,
                        pos_x,
                        pos_y,
                        nav_heading_deg,
                        current_speed,
                        steer_pwm,
                        thr_pwm,
                        snap,
                    )
                    ok, encoded = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ok:
                        with state.lock:
                            state.latest_jpeg = bytes(encoded)
                except Exception:
                    pass
        # Apply actuator commands
        with state.lock:
            if now - state.last_command_at > 4.0:
                state.throttle_pwm = NEUTRAL_PWM

            steer_pwm = state.steering_pwm
            thr_pwm = state.throttle_pwm
        rudder_target = (steer_pwm - NEUTRAL_PWM) / 400.0 * 0.78
        rudder_target = max(-0.785, min(0.785, rudder_target))
        if rudder_motor is not None:
            rudder_motor.setPosition(rudder_target)

        # 2. Thruster target speed in m/s (0 .. 2.8 m/s cruise)
        if thr_pwm > NEUTRAL_PWM:
            target_speed = (thr_pwm - NEUTRAL_PWM) / 100.0 * 2.2  # m/s
            prop_velocity = (thr_pwm - NEUTRAL_PWM) / 100.0 * 60.0
        elif thr_pwm < NEUTRAL_PWM:
            target_speed = (thr_pwm - NEUTRAL_PWM) / 100.0 * 1.0
            prop_velocity = (thr_pwm - NEUTRAL_PWM) / 100.0 * 30.0
        else:
            target_speed = 0.0
            prop_velocity = 0.0

        if thruster_motor is not None:
            thruster_motor.setVelocity(prop_velocity)

        # 3. Planar Marine Physics Simulation (Hydrodynamic Inertia & Water Coasting Drag)
        accel_rate = 2.0  # m/s^2 forward thrust acceleration
        water_drag = 0.55 * current_speed + 0.25 * (current_speed ** 2)  # m/s^2

        if current_speed < target_speed:
            current_speed = min(target_speed, current_speed + accel_rate * dt)
        elif current_speed > target_speed:
            current_speed = max(target_speed, current_speed - water_drag * dt)

        # Hydrodynamic Rudder Moment (Crisp 90-degree turning agility matching physical RC ASV)
        steer_ratio = (steer_pwm - NEUTRAL_PWM) / 400.0
        prop_wash = max(0.4, (thr_pwm - NEUTRAL_PWM) / 140.0) if thr_pwm > NEUTRAL_PWM else 0.4
        speed_factor = max(0.35, current_speed / 1.4)
        yaw_rate = -steer_ratio * 2.8 * (0.4 * speed_factor + 0.6 * prop_wash)  # rad/s (160 deg/s at full rudder)

        yaw_rad = (yaw_rad + yaw_rate * dt) % (2.0 * math.pi)

        # Forward translation along heading
        pos_x += current_speed * math.cos(yaw_rad) * dt
        pos_y += current_speed * math.sin(yaw_rad) * dt
        # SENSOR KELILING TEMBOK: Deteksi Tabrakan & Otomatis Berhenti (E-STOP)
        wall_sensor_triggered = False
        if pos_y >= WALL_LIMIT_Y:
            wall_sensor_triggered = True
            pos_y = WALL_LIMIT_Y
        elif pos_y <= -WALL_LIMIT_Y:
            wall_sensor_triggered = True
            pos_y = -WALL_LIMIT_Y

        if pos_x >= WALL_LIMIT_X:
            wall_sensor_triggered = True
            pos_x = WALL_LIMIT_X
        elif pos_x <= -WALL_LIMIT_X:
            wall_sensor_triggered = True
            pos_x = -WALL_LIMIT_X

        if wall_sensor_triggered:
            # Otomatis Berhenti (E-STOP): Matikan thruster & nolkan laju perahu
            current_speed = 0.0
            thr_pwm = NEUTRAL_PWM
            with state.lock:
                state.throttle_pwm = NEUTRAL_PWM
                state.speed_mps = 0.0

        # Check gate sensor crossing & buoy/wall touch collision
        gate_tracker.check_crossing(prev_x, prev_y, pos_x, pos_y, speed=current_speed)
        prev_x = pos_x
        prev_y = pos_y

        # Log trajectory point every 100ms
        if now - last_point_log >= 0.10:
            nav_hdg = (90.0 - math.degrees(yaw_rad)) % 360.0
            run_logger.log_point(pos_x, pos_y, nav_hdg, current_speed, steer_pwm, thr_pwm)
            last_point_log = now

        # Enforce level 2D position on water surface (Z = 0.04)
        if trans_field is not None:
            trans_field.setSFVec3f([pos_x, pos_y, WATER_PLANE_Z])
        if rot_field is not None:
            rot_field.setSFRotation([0.0, 0.0, 1.0, yaw_rad])

        nav_heading_deg = (90.0 - math.degrees(yaw_rad)) % 360.0

        with state.lock:
            state.x = pos_x
            state.y = pos_y
            state.heading_deg = nav_heading_deg
            state.speed_mps = current_speed
            state.yaw_rad = yaw_rad

        if agent is not None:
            agent.report_step(
                sensors={
                    "x": round(pos_x, 4),
                    "y": round(pos_y, 4),
                    "heading": round(nav_heading_deg, 2),
                    "speed": round(current_speed, 2),
                },
                metrics={
                    "steering_pwm": steer_pwm,
                    "throttle_pwm": thr_pwm,
                },
                actuators={
                    "rudder_target": round(rudder_target, 4),
                    "thrust_speed": round(current_speed, 2),
                },
            )


if __name__ == "__main__":
    main()
