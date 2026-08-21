"""Webots ASV Supervisor Controller with Gate Sensors, Buoy Touch Collision Detection & Per-Run Logging for KKI2026.

- Automatically creates a new timestamped folder for every simulation run under
  the active repository's simulation/logs/run_YYYYMMDD_HHMMSS/ directory.
- Saves live telemetry_track.jsonl, gate_scoring.json, buoy_collisions.jsonl, and summary_report.md.
- Tracks boat position across all 10 track gates (3 right slalom, 4 top corridor, 3 left slalom).
- Detects buoy touch collisions (error/penalty if boat touches any buoy).
- Verifies if the boat passes cleanly between each pair of buoys (2.0m width) or misses.
- Serves virtual Logitech camera frames over HTTP (/frame.jpg and /stream.mjpg).
  Raw endpoints (/frame_raw.jpg and /stream_raw.mjpg) omit the HUD overlay so
  vision does not mistake navigation graphics for marker boxes.
- Exposes /status, /gates, and /collisions endpoints with live scoring and penalty tracking.
"""

from __future__ import annotations

import json
import math
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
BOAT_START_Z = 0.025  # m; estimated 4-5 cm displacement draft after settling
BOAT_MASS_KG = 9.5
BOAT_LOA_M = 1.065
BOAT_BEAM_M = 0.300
# The field prototype can throw the stern pod farther than the conservative
# +/-60 degree placeholder used by the first Webots model.  An 80 degree
# default gives the monohull enough lateral/yaw authority to reproduce the
# measured hard corner; keep the environment override for identification
# runs with a different servo stop.
MAX_AZIMUTH_DEG = max(5.0, min(90.0, float(os.getenv("ASV_MAX_AZIMUTH_DEG", "80.0"))))
MAX_AZIMUTH_RAD = math.radians(MAX_AZIMUTH_DEG)
MAX_THRUST_N = float(os.getenv("ASV_MAX_THRUST_N", "34.0"))
MAX_REVERSE_THRUST_N = float(os.getenv("ASV_MAX_REVERSE_THRUST_N", "12.0"))
REVERSE_THRUST_ENABLED = os.getenv("ASV_REVERSE_THRUST_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
THRUSTER_OFFSET = [-0.490, 0.0, -0.035]
COMMAND_TIMEOUT_S = 1.0
ULTRASONIC_MAX_RANGE_M = 5.0
ULTRASONIC_DEVICES = {
    "front_left": "ultrasonic_front_left",
    "front": "ultrasonic_front",
    "front_right": "ultrasonic_front_right",
    "left": "ultrasonic_left",
    "right": "ultrasonic_right",
}
ULTRASONIC_MAVLINK_NAMES = {
    "front_left": b"ultra_fl",
    "front": b"ultra_f",
    "front_right": b"ultra_fr",
    "left": b"ultra_l",
    "right": b"ultra_r",
}

BASE_LAT = -6.200000
BASE_LON = 106.816666
METERS_PER_DEG_LAT = 111320.0

# Buoy & Wall Collision Sensor Thresholds
BUOY_TOUCH_RADIUS = 0.40  # side clearance: half beam 0.15m + buoy radius 0.22m
# Inner wall face is at +/-14.90 m. The hull's worst-case half-diagonal in the
# horizontal plane is 0.553 m, so +/-14.30 m retains a conservative clearance.
WALL_LIMIT_Y = 14.30
# The supplied KKI layout starts in the blue three-buoy dock, goes north on
# the right-hand leg (Arena A), and returns to that dock after the two bottom
# marker checkpoints.  Arena B mirrors every X coordinate across X=15 m.
DOCK_TARGET_A = (11.5, -13.0)
DOCK_ENTRY_A = (11.5, -10.45)
DOCK_HEADING_A_DEG = 180.0
MARKER_CORRIDOR_HALF_WIDTH_M = 0.75
DOCK_TOLERANCE_M = 0.75
DOCK_HEADING_TOLERANCE_DEG = 15.0
DOCK_MAX_SPEED_MPS = 0.15
DOCK_STABLE_TIME_S = 3.0
ARENA_MIRROR_X = 15.0
# 10 Track Gates based on official KKI 30x30m layout (2.0m buoy gap)
ARENA_A_TRACK_GATES = [
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

# These are floating *pass-through* markers, not dock targets.  The boat must
# cross them in order after Gate 10 and before final docking.
ARENA_A_ROUTE_MARKERS = [
    {
        "id": "marker_biru",
        "name": "Marker Biru (Bottom Checkpoint 1)",
        "position": [-9.7, -8.7],
    },
    {
        "id": "marker_hijau",
        "name": "Marker Hijau (Bottom Checkpoint 2)",
        "position": [-6.9, -11.9],
    },
]

# The physical rectangles are passed on the safe side by the route controller:
# blue on its west/left side, then green on its east/right side with a small
# north lead.  The scorer uses the same offsets, so a valid pass never asks
# the hull centre to overlap a floating obstacle.
ARENA_A_MARKER_PASS_OFFSETS = ((-1.50, -0.50), (1.35, 0.65))

ARENA_A_DOCK_BUOYS = [
    {"name": "dock_buoy_1", "pos": [10.7, -12.4]},
    {"name": "dock_buoy_2", "pos": [10.7, -13.0]},
    {"name": "dock_buoy_3", "pos": [10.7, -13.6]},
]

def normalize_arena(value: object) -> str:
    """Return the supported arena identifier, defaulting safely to Arena A."""
    arena = str(value or "A").strip().upper()
    return arena if arena in {"A", "B"} else "A"


def mirror_x(x: float) -> float:
    return (2.0 * ARENA_MIRROR_X) - x


def arena_point(point: tuple[float, float] | list[float], arena: str) -> tuple[float, float]:
    x, y = float(point[0]), float(point[1])
    return (x, y) if normalize_arena(arena) == "A" else (mirror_x(x), y)


def arena_heading(heading_a_deg: float, arena: str) -> float:
    if normalize_arena(arena) == "A":
        return heading_a_deg % 360.0
    return (-heading_a_deg) % 360.0


def track_gates_for_arena(arena: str) -> list[dict[str, object]]:
    """Build a detached, mirrored gate definition list for the active arena."""
    selected = normalize_arena(arena)
    gates: list[dict[str, object]] = []
    for source in ARENA_A_TRACK_GATES:
        gate = dict(source)
        gate["name"] = f"Arena {selected} - {source['name']}"
        gate["buoy_red"] = list(arena_point(source["buoy_red"], selected))
        gate["buoy_green"] = list(arena_point(source["buoy_green"], selected))
        if "x" in source:
            gate["x"] = arena_point((float(source["x"]), 0.0), selected)[0]
        if "x_min" in source:
            x1 = arena_point((float(source["x_min"]), 0.0), selected)[0]
            x2 = arena_point((float(source["x_max"]), 0.0), selected)[0]
            gate["x_min"], gate["x_max"] = min(x1, x2), max(x1, x2)
        gates.append(gate)
    return gates


def buoys_for_gates(gates: list[dict[str, object]]) -> list[dict[str, object]]:
    buoys: list[dict[str, object]] = []
    for gate in gates:
        buoys.append({"name": f"{gate['id']}_red", "pos": gate["buoy_red"]})
        buoys.append({"name": f"{gate['id']}_green", "pos": gate["buoy_green"]})
    return buoys


def route_markers_for_arena(arena: str) -> list[dict[str, object]]:
    """Return the ordered blue/green bottom checkpoints for an arena."""
    selected = normalize_arena(arena)
    markers: list[dict[str, object]] = []
    for index, source in enumerate(ARENA_A_ROUTE_MARKERS):
        marker = dict(source)
        marker["name"] = f"Arena {selected} - {source['name']}"
        marker["position"] = list(arena_point(source["position"], selected))
        offset_x, offset_y = ARENA_A_MARKER_PASS_OFFSETS[index]
        marker["pass_position"] = list(
            arena_point(
                (float(source["position"][0]) + offset_x, float(source["position"][1]) + offset_y),
                selected,
            )
        )
        markers.append(marker)
    return markers


def dock_buoys_for_arena(arena: str) -> list[dict[str, object]]:
    """Return the three blue floating buoys guarding the final dock."""
    selected = normalize_arena(arena)
    return [
        {
            "name": (
                source["name"]
                if selected == "A"
                else f"arena_b_{source['name']}"
            ),
            "pos": list(arena_point(source["pos"], selected)),
        }
        for source in ARENA_A_DOCK_BUOYS
    ]


def start_position_for_arena(arena: str) -> tuple[float, float]:
    return arena_point((11.1, -11.5), arena)


def dock_position_for_arena(arena: str) -> tuple[float, float]:
    return arena_point(DOCK_TARGET_A, arena)


def dock_entry_for_arena(arena: str) -> tuple[float, float]:
    return arena_point(DOCK_ENTRY_A, arena)


def dock_heading_for_arena(arena: str) -> float:
    # Final approach enters the vertical dock from its open northern side.
    return arena_heading(DOCK_HEADING_A_DEG, arena)


def wall_x_limits_for_arena(arena: str) -> tuple[float, float]:
    return (-14.3, 14.3) if normalize_arena(arena) == "A" else (15.7, 44.3)


def configured_arena() -> str:
    """Read Arena A/B from Webots controller args first, then environment."""
    for argument in sys.argv[1:]:
        if argument.upper().startswith("--ARENA="):
            return normalize_arena(argument.split("=", 1)[1])
    return normalize_arena(os.getenv("ASV_ARENA", "A"))


class RunLogger:
    """Manages automatic per-run directory logging for every simulation trial."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = (
            Path(base_dir)
            if base_dir is not None
            else Path(__file__).resolve().parents[3] / "logs"
        )
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
        *,
        yaw_rate_dps: float = 0.0,
        azimuth_angle_deg: float = 0.0,
        azimuth_target_deg: float = 0.0,
        thrust_force_n: float = 0.0,
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
            "yaw_rate_dps": round(yaw_rate_dps, 3),
            "azimuth_angle_deg": round(azimuth_angle_deg, 3),
            "azimuth_target_deg": round(azimuth_target_deg, 3),
            "thrust_force_n": round(thrust_force_n, 3),
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
        markers_passed = scoring_data.get("markers_passed_valid", 0)
        markers_missed = scoring_data.get("markers_missed", 0)
        markers_total = scoring_data.get("total_markers", 2)
        score_pct = scoring_data.get("score_percent", 0.0)
        buoy_touch_count = len(buoy_cols)
        wall_touch_count = len(wall_cols)
        docked = bool(scoring_data.get("docked", False))
        dock_position = scoring_data.get("dock_position")
        dock_position_text = (
            f"X = {dock_position[0]:.2f} m, Y = {dock_position[1]:.2f} m"
            if isinstance(dock_position, list) and len(dock_position) == 2
            else "-"
        )

        lines = [
            f"# Laporan Hasil Uji Simulasi ASV KKI 2026 - {self.run_id}",
            "",
            f"- **No. Uji**: {self.test_number}",
            f"- **Jam Mulai (lokal)**: {self.started_at_local.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"- **Waktu Mulai (UTC)**: {self.started_at.isoformat()}",
            f"- **Waktu Update (UTC)**: {now.isoformat()}",
            f"- **Durasi Sesi**: {duration_s:.1f} detik",
            f"- **Posisi Akhir Kapal**: X = {final_x:.2f} m, Y = {final_y:.2f} m",
            f"- **Status Docking**: **{'BERHASIL' if docked else 'BELUM'}**",
            f"- **Posisi Docking**: {dock_position_text}",
            f"- **Skor Validasi Gate**: **{passed} / {total} Gate ({score_pct}%)**",
            f"- **Gate Terlewati (Valid)**: {passed}",
            f"- **Gate Missed (Luar)**: {missed}",
            f"- **Marker Bawah Valid**: **{markers_passed} / {markers_total}**",
            f"- **Marker Bawah Missed**: {markers_missed}",
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

        lines.extend([
            "",
            "## Detail Checkpoint Marker Bawah",
            "",
            "| ID Marker | Nama Marker | Status | Koordinat Crossing | Waktu (s) |",
            "|---|---|---|---|---|",
        ])
        markers = scoring_data.get("markers", {})
        for marker_id, marker in markers.items():
            status = marker.get("status", "PENDING")
            coord = marker.get("crossing_coord")
            coord_str = f"[{coord[0]}, {coord[1]}]" if coord else "-"
            crossed_at = marker.get("crossed_at")
            time_str = f"{crossed_at:.1f}" if crossed_at else "-"
            badge = (
                "PASSED (VALID)"
                if status == "PASSED_VALID"
                else ("MISSED" if status == "MISSED_OUTSIDE" else "PENDING")
            )
            lines.append(
                f"| {marker_id} | {marker.get('name')} | **{badge}** | {coord_str} | {time_str} |"
            )

        with open(self.report_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")


run_logger = RunLogger()


class GateSensorTracker:
    """Track the ordered course, clearance violations, and stable docking."""

    def __init__(self, arena: str = "A") -> None:
        self.lock = threading.Lock()
        self.arena = normalize_arena(arena)
        self.track_gates: list[dict[str, object]] = []
        self.route_markers: list[dict[str, object]] = []
        self.all_buoys: list[dict[str, object]] = []
        self.gate_results: dict[str, dict[str, object]] = {}
        self.marker_results: dict[str, dict[str, object]] = {}
        self.buoy_collisions: list[dict[str, object]] = []
        self.wall_collisions: list[dict[str, object]] = []
        self.touched_buoys: set[str] = set()
        self.touched_walls: set[str] = set()
        self.docked = False
        self.docked_at: str | None = None
        self.dock_position: list[float] | None = None
        self.dock_candidate_since: float | None = None
        self.dock_stable_elapsed_s = 0.0
        self.reset(self.arena)

    def reset(self, arena: str | None = None) -> None:
        with self.lock:
            if arena is not None:
                self.arena = normalize_arena(arena)
            self.track_gates = track_gates_for_arena(self.arena)
            self.route_markers = route_markers_for_arena(self.arena)
            self.all_buoys = buoys_for_gates(self.track_gates) + dock_buoys_for_arena(
                self.arena
            )
            self.gate_results = {
                str(g["id"]): {
                    "name": g["name"],
                    "status": "PENDING",
                    "crossed_at": None,
                    "crossing_coord": None,
                }
                for g in self.track_gates
            }
            self.marker_results = {
                str(marker["id"]): {
                    "name": marker["name"],
                    "status": "PENDING",
                    "crossed_at": None,
                    "crossing_coord": None,
                }
                for marker in self.route_markers
            }
            self.buoy_collisions.clear()
            self.wall_collisions.clear()
            self.touched_buoys.clear()
            self.touched_walls.clear()
            self.docked = False
            self.docked_at = None
            self.dock_position = None
            self.dock_candidate_since = None
            self.dock_stable_elapsed_s = 0.0

    def check_docking(
        self,
        x: float,
        y: float,
        heading_deg: float,
        speed_mps: float,
        simulation_time_s: float,
    ) -> bool:
        """Latch success only after a slow, aligned three-second dock hold."""
        dock_x, dock_y = dock_position_for_arena(self.arena)
        desired_heading = dock_heading_for_arena(self.arena)
        distance_m = math.hypot(dock_x - x, dock_y - y)
        heading_error = abs(((desired_heading - heading_deg + 180.0) % 360.0) - 180.0)
        with self.lock:
            if self.docked:
                return False
            passed_count = sum(
                1
                for value in self.gate_results.values()
                if value["status"] == "PASSED_VALID"
            )
            markers_passed = sum(
                1
                for value in self.marker_results.values()
                if value["status"] == "PASSED_VALID"
            )
            stable = (
                passed_count >= len(self.track_gates)
                and markers_passed >= len(self.route_markers)
                and distance_m <= DOCK_TOLERANCE_M
                and heading_error <= DOCK_HEADING_TOLERANCE_DEG
                and abs(speed_mps) <= DOCK_MAX_SPEED_MPS
            )
            if not stable:
                self.dock_candidate_since = None
                self.dock_stable_elapsed_s = 0.0
                return False
            if self.dock_candidate_since is None:
                self.dock_candidate_since = simulation_time_s
                self.dock_stable_elapsed_s = 0.0
                return False
            self.dock_stable_elapsed_s = simulation_time_s - self.dock_candidate_since
            if self.dock_stable_elapsed_s < DOCK_STABLE_TIME_S:
                return False
            self.docked = True
            self.docked_at = datetime.now(timezone.utc).isoformat()
            self.dock_position = [round(x, 3), round(y, 3)]

        snap = self.snapshot()
        run_logger.save_gate_scoring(snap)
        run_logger.write_summary_report(
            snap,
            list(self.buoy_collisions),
            list(self.wall_collisions),
            x,
            y,
        )
        print(
            f"[DOCKING] BERHASIL Arena {self.arena} di ({x:.2f}, {y:.2f}); "
            f"jarak={distance_m:.2f}m heading_error={heading_error:.1f}deg"
        )
        return True

    def _check_marker_crossing(
        self,
        x_prev: float,
        y_prev: float,
        x_curr: float,
        y_curr: float,
        now: float,
    ) -> bool:
        """Score the next bottom marker only after every buoy gate is processed.

        A marker is valid only when the hull centre crosses the ordered
        safe-side plane in the expected direction and remains inside the
        configured corridor. The plane is offset from the rectangle centre so
        the physical hull can pass the obstacle without touching it.
        """
        with self.lock:
            gate_progress = sum(
                1
                for value in self.gate_results.values()
                if value["status"] != "PENDING"
            )
            if gate_progress < len(self.track_gates):
                return False
            marker_index = next(
                (
                    index
                    for index, marker in enumerate(self.route_markers)
                    if self.marker_results[str(marker["id"])]["status"] == "PENDING"
                ),
                None,
            )
            if marker_index is None:
                return False

            marker = self.route_markers[marker_index]
            marker_id = str(marker["id"])
            marker_x, marker_y = map(
                float,
                marker.get("pass_position", marker["position"]),
            )
            if marker_index == 0:
                last_gate = self.track_gates[-1]
                red_x, red_y = map(float, last_gate["buoy_red"])
                green_x, green_y = map(float, last_gate["buoy_green"])
                incoming_x = (red_x + green_x) / 2.0
                incoming_y = (red_y + green_y) / 2.0
            else:
                incoming_x, incoming_y = map(
                    float,
                    self.route_markers[marker_index - 1].get(
                        "pass_position",
                        self.route_markers[marker_index - 1]["position"],
                    ),
                )

            route_dx = marker_x - incoming_x
            route_dy = marker_y - incoming_y
            route_length = math.hypot(route_dx, route_dy)
            if route_length <= 1e-6:
                return False
            previous_along = (
                (x_prev - marker_x) * route_dx
                + (y_prev - marker_y) * route_dy
            ) / route_length
            current_along = (
                (x_curr - marker_x) * route_dx
                + (y_curr - marker_y) * route_dy
            ) / route_length
            if not (previous_along < 0.0 <= current_along):
                return False

            denominator = current_along - previous_along
            ratio = -previous_along / denominator if denominator else 0.0
            crossing_x = x_prev + ratio * (x_curr - x_prev)
            crossing_y = y_prev + ratio * (y_curr - y_prev)
            lateral_m = abs(
                route_dx * (crossing_y - marker_y)
                - route_dy * (crossing_x - marker_x)
            ) / route_length
            result = self.marker_results[marker_id]
            result["status"] = (
                "PASSED_VALID"
                if lateral_m <= MARKER_CORRIDOR_HALF_WIDTH_M
                else "MISSED_OUTSIDE"
            )
            result["crossed_at"] = now
            result["crossing_coord"] = [round(crossing_x, 2), round(crossing_y, 2)]
            print(
                f"[SENSOR MARKER] {marker['name']}: {result['status']} "
                f"at {result['crossing_coord']} lateral={lateral_m:.2f}m"
            )
            return True

    def check_buoy_touch(self, x: float, y: float) -> bool:
        """Check the side-clearance safety zone of active-arena buoys."""
        updated = False
        for buoy in self.all_buoys:
            buoy_name = str(buoy["name"])
            buoy_x, buoy_y = buoy["pos"]
            distance = math.hypot(x - float(buoy_x), y - float(buoy_y))
            if distance >= BUOY_TOUCH_RADIUS or buoy_name in self.touched_buoys:
                continue
            self.touched_buoys.add(buoy_name)
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "buoy_name": buoy_name,
                "boat_x": round(x, 2),
                "boat_y": round(y, 2),
                "distance_m": round(distance, 3),
            }
            with self.lock:
                self.buoy_collisions.append(record)
            run_logger.log_buoy_collision(buoy_name, x, y, distance)
            updated = True
            print(
                f"[SENSOR BUOY] Kapal menyentuh {buoy_name}: "
                f"X={x:.2f} Y={y:.2f} jarak={distance:.2f}m"
            )
        return updated

    def check_wall_collision(self, x: float, y: float, speed: float) -> bool:
        """Check the physical boundaries of the selected 30x30 m arena."""
        x_min, x_max = wall_x_limits_for_arena(self.arena)
        wall_hit = None
        if y >= WALL_LIMIT_Y:
            wall_hit = "DINDING_UTARA_NORTH"
        elif y <= -WALL_LIMIT_Y:
            wall_hit = "DINDING_SELATAN_SOUTH"
        elif x >= x_max:
            wall_hit = "DINDING_TIMUR_EAST"
        elif x <= x_min:
            wall_hit = "DINDING_BARAT_WEST"
        if wall_hit is None:
            return False

        wall_key = f"{wall_hit}_{int(time.monotonic() // 2)}"
        if wall_key in self.touched_walls:
            return False
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
        print(
            f"[SENSOR PEMBATAS] Kapal menyentuh {wall_hit}: "
            f"X={x:.2f} Y={y:.2f} speed={speed:.2f}m/s"
        )
        return True

    def check_crossing(
        self,
        x_prev: float,
        y_prev: float,
        x_curr: float,
        y_curr: float,
        speed: float = 0.0,
    ) -> None:
        """Score only the next expected gate so crossings cannot jump order."""
        now = time.monotonic()
        buoy_updated = self.check_buoy_touch(x_curr, y_curr)
        wall_updated = self.check_wall_collision(x_curr, y_curr, speed)
        updated = False

        with self.lock:
            gate = next(
                (
                    item
                    for item in self.track_gates
                    if self.gate_results[str(item["id"])]["status"] == "PENDING"
                ),
                None,
            )
            if gate is not None:
                gate_id = str(gate["id"])
                crossing_coord: list[float] | None = None
                passed = False
                if gate["type"] == "horizontal":
                    y_line = float(gate["y"])
                    crossed = (y_prev < y_line <= y_curr) or (y_prev > y_line >= y_curr)
                    if crossed:
                        ratio = (y_line - y_prev) / (y_curr - y_prev) if y_curr != y_prev else 0.0
                        x_cross = x_prev + ratio * (x_curr - x_prev)
                        min_x = float(gate["x_min"])
                        max_x = float(gate["x_max"])
                        passed = min_x - 0.25 <= x_cross <= max_x + 0.25
                        crossing_coord = [round(x_cross, 2), y_line]
                else:
                    x_line = float(gate["x"])
                    crossed = (x_prev > x_line >= x_curr) or (x_prev < x_line <= x_curr)
                    if crossed:
                        ratio = (x_line - x_prev) / (x_curr - x_prev) if x_curr != x_prev else 0.0
                        y_cross = y_prev + ratio * (y_curr - y_prev)
                        min_y = float(gate["y_min"])
                        max_y = float(gate["y_max"])
                        passed = min_y - 0.25 <= y_cross <= max_y + 0.25
                        crossing_coord = [x_line, round(y_cross, 2)]

                if crossing_coord is not None:
                    result = self.gate_results[gate_id]
                    result["status"] = "PASSED_VALID" if passed else "MISSED_OUTSIDE"
                    result["crossed_at"] = now
                    result["crossing_coord"] = crossing_coord
                    updated = True
                    print(
                        f"[SENSOR GATE] {gate['name']}: {result['status']} "
                        f"at {crossing_coord}"
                    )

        marker_updated = self._check_marker_crossing(
            x_prev,
            y_prev,
            x_curr,
            y_curr,
            now,
        )

        if updated or marker_updated or buoy_updated or wall_updated:
            snapshot = self.snapshot()
            run_logger.save_gate_scoring(snapshot)
            run_logger.write_summary_report(
                snapshot,
                list(self.buoy_collisions),
                list(self.wall_collisions),
                x_curr,
                y_curr,
            )

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            passed_count = sum(
                1 for value in self.gate_results.values() if value["status"] == "PASSED_VALID"
            )
            missed_count = sum(
                1 for value in self.gate_results.values() if value["status"] == "MISSED_OUTSIDE"
            )
            progress_count = passed_count + missed_count
            markers_passed = sum(
                1
                for value in self.marker_results.values()
                if value["status"] == "PASSED_VALID"
            )
            markers_missed = sum(
                1
                for value in self.marker_results.values()
                if value["status"] == "MISSED_OUTSIDE"
            )
            marker_progress_count = markers_passed + markers_missed
            dock_x, dock_y = dock_position_for_arena(self.arena)
            dock_entry_x, dock_entry_y = dock_entry_for_arena(self.arena)
            return {
                "run_id": run_logger.run_id,
                "log_dir": str(run_logger.run_dir),
                "arena": self.arena,
                "total_gates": len(self.track_gates),
                "passed_valid": passed_count,
                "missed": missed_count,
                "progress_count": progress_count,
                "total_markers": len(self.route_markers),
                "markers_passed_valid": markers_passed,
                "markers_missed": markers_missed,
                "marker_progress_count": marker_progress_count,
                "buoy_touches": len(self.buoy_collisions),
                "wall_touches": len(self.wall_collisions),
                "score_percent": round((passed_count / len(self.track_gates)) * 100, 1),
                "docked": self.docked,
                "docked_at": self.docked_at,
                "dock_target": [dock_x, dock_y],
                "dock_entry": [dock_entry_x, dock_entry_y],
                "dock_heading_deg": round(dock_heading_for_arena(self.arena), 2),
                "dock_stable_s": round(self.dock_stable_elapsed_s, 2),
                "dock_position": self.dock_position,
                "gates": dict(self.gate_results),
                "markers": dict(self.marker_results),
                "buoy_collisions": list(self.buoy_collisions),
                "wall_collisions": list(self.wall_collisions),
            }

    def is_docked(self) -> bool:
        with self.lock:
            return self.docked


class SharedSimState:
    def __init__(self, arena: str = "A") -> None:
        self.lock = threading.Lock()
        self.latest_jpeg: bytes = b""
        self.latest_raw_jpeg: bytes = b""
        self.steering_pwm: int = NEUTRAL_PWM
        self.throttle_pwm: int = NEUTRAL_PWM
        self.last_command_at: float = time.monotonic()
        self.reset_requested: bool = False
        self.requested_arena: str = normalize_arena(arena)
        self.arena: str = normalize_arena(arena)
        start_x, start_y = start_position_for_arena(self.arena)
        self.x: float = start_x
        self.y: float = start_y
        self.z: float = BOAT_START_Z
        self.heading_deg: float = 360.0
        self.speed_mps: float = 0.0
        self.yaw_rate_dps: float = 0.0
        self.yaw_rad: float = math.pi / 2.0
        self.ultrasonic: dict[str, float] = {
            key: ULTRASONIC_MAX_RANGE_M for key in ULTRASONIC_DEVICES
        }
        self.azimuth_angle_deg: float = 0.0
        self.thrust_force_n: float = 0.0
        self.control_phase: str = "IDLE"
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
        active_arena = normalize_arena(gates_data.get("arena", "A"))
        wall_x_min, wall_x_max = wall_x_limits_for_arena(active_arena)
        wall_alert = x <= wall_x_min or x >= wall_x_max or abs(y) >= WALL_LIMIT_Y
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
state = SharedSimState(configured_arena())


class CameraStreamHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        requested_arena = query.get("arena", [None])[0]
        if path.startswith("/arena/"):
            requested_arena = path.rsplit("/", 1)[-1]
            path = "/arena"
        if path not in {"/reset", "/arena"}:
            self.send_error(404, "Not Found")
            return
        arena = normalize_arena(requested_arena or state.arena)
        with state.lock:
            state.requested_arena = arena
            state.reset_requested = True
        payload = json.dumps(
            {"status": "reset_requested", "arena": arena}
        ).encode("utf-8")
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/frame.jpg", "/camera/surface", "/frame_raw.jpg"):
            with state.lock:
                jpeg = (
                    state.latest_raw_jpeg
                    if path == "/frame_raw.jpg"
                    else state.latest_jpeg
                )
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

        if path in ("/stream.mjpg", "/stream/atas", "/video", "/stream_raw.mjpg"):
            try:
                self.send_response(200)
                self.send_header(
                    "Content-Type", "multipart/x-mixed-replace; boundary=frame"
                )
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                while True:
                    with state.lock:
                        jpeg = (
                            state.latest_raw_jpeg
                            if path == "/stream_raw.mjpg"
                            else state.latest_jpeg
                        )
                    if jpeg:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    time.sleep(0.04)  # ~25 FPS
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.error, OSError, Exception):
                return
        if path == "/status":
            with state.lock:
                status_payload = {
                    "status": "running",
                    "arena": state.arena,
                    "steering_pwm": state.steering_pwm,
                    "throttle_pwm": state.throttle_pwm,
                    "x": state.x,
                    "y": state.y,
                    "z": state.z,
                    "heading_deg": state.heading_deg,
                    "speed_mps": state.speed_mps,
                    "yaw_rate_dps": state.yaw_rate_dps,
                    "ultrasonic": dict(state.ultrasonic),
                    # Deprecated compatibility alias for older dashboards.
                    "sonar": dict(state.ultrasonic),
                    "azimuth_angle_deg": state.azimuth_angle_deg,
                    "thrust_force_n": state.thrust_force_n,
                    "control_phase": state.control_phase,
                    "gate_tracking": self.gate_tracker.snapshot(),
                }
            payload_bytes = json.dumps(status_payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload_bytes)))
            self.end_headers()
            self.wfile.write(payload_bytes)
            return

        if path in ("/gates", "/scoring", "/collisions"):
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
                yaw_rate_dps = state.yaw_rate_dps
                azimuth_angle_deg = state.azimuth_angle_deg
                ultrasonic_values = dict(state.ultrasonic)
                arena_id = 0 if state.arena == "A" else 1
            gate_snapshot = gate_tracker.snapshot() if gate_tracker is not None else {}
            # Route progress advances after either a valid pass or a recorded
            # miss.  Keeping it separate from passed_valid prevents the
            # controller from orbiting a gate that is already behind the boat.
            gate_count = int(gate_snapshot.get("progress_count", 0))
            passed_count = int(gate_snapshot.get("passed_valid", 0))
            marker_count = int(gate_snapshot.get("marker_progress_count", 0))

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
                    int(spd * 100 * math.sin(math.radians(hdg))),
                    int(spd * 100 * math.cos(math.radians(hdg))),
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
                mav.mav.named_value_int_send(
                    int(now * 1000) & 0xFFFFFFFF,
                    b"gates_ok",
                    passed_count,
                )
                # NAMED_VALUE_INT names are limited to ten bytes.
                mav.mav.named_value_int_send(
                    int(now * 1000) & 0xFFFFFFFF,
                    b"mark_count",
                    marker_count,
                )
                mav.mav.named_value_int_send(
                    int(now * 1000) & 0xFFFFFFFF,
                    b"arena_id",
                    arena_id,
                )
                for ultrasonic_key, mavlink_name in ULTRASONIC_MAVLINK_NAMES.items():
                    mav.mav.named_value_float_send(
                        int(now * 1000) & 0xFFFFFFFF,
                        mavlink_name,
                        float(
                            ultrasonic_values.get(
                                ultrasonic_key,
                                ULTRASONIC_MAX_RANGE_M,
                            )
                        ),
                    )
                mav.mav.named_value_float_send(
                    int(now * 1000) & 0xFFFFFFFF,
                    b"yaw_rate",
                    float(yaw_rate_dps),
                )
                mav.mav.named_value_float_send(
                    int(now * 1000) & 0xFFFFFFFF,
                    b"azimuth",
                    float(azimuth_angle_deg),
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


def heading_from_orientation(orientation: list[float]) -> tuple[float, float]:
    """Return compass heading and mathematical yaw from a Webots matrix."""
    if len(orientation) < 9:
        return 0.0, math.pi / 2.0
    forward_world_x = orientation[0]
    forward_world_y = orientation[3]
    yaw_rad = math.atan2(forward_world_y, forward_world_x)
    return (90.0 - math.degrees(yaw_rad)) % 360.0, yaw_rad


def read_ultrasonic_values(devices: dict[str, object]) -> dict[str, float]:
    readings: dict[str, float] = {}
    for key, device in devices.items():
        try:
            value = float(device.getValue())
        except Exception:
            value = ULTRASONIC_MAX_RANGE_M
        if not math.isfinite(value):
            value = ULTRASONIC_MAX_RANGE_M
        readings[key] = max(0.05, min(ULTRASONIC_MAX_RANGE_M, value))
    return readings


def thrust_force_from_pwm(throttle_pwm: int) -> float:
    """Map RC3 to forward thrust or a small reversible-ESC brake pulse."""
    if throttle_pwm >= NEUTRAL_PWM:
        forward_ratio = max(0.0, min(1.0, (throttle_pwm - NEUTRAL_PWM) / 500.0))
        return MAX_THRUST_N * forward_ratio
    if not REVERSE_THRUST_ENABLED:
        return 0.0
    reverse_ratio = max(0.0, min(1.0, (NEUTRAL_PWM - throttle_pwm) / 500.0))
    return -MAX_REVERSE_THRUST_N * reverse_ratio


def main() -> None:
    if Supervisor is None:
        print("Webots Supervisor module not loaded. Run from inside Webots.")
        return

    robot = Supervisor()
    time_step = max(1, int(robot.getBasicTimeStep()) or TIME_STEP)
    boat_node = robot.getSelf()
    if boat_node is None:
        raise RuntimeError("ASV controller cannot access its Robot node")
    trans_field = boat_node.getField("translation")
    rot_field = boat_node.getField("rotation")

    azimuth_motor = robot.getDevice("azimuth_motor")
    azimuth_sensor = robot.getDevice("azimuth_sensor")
    thruster_motor = robot.getDevice("thruster_motor")
    if azimuth_sensor is not None:
        azimuth_sensor.enable(time_step)
    if thruster_motor is not None:
        thruster_motor.setPosition(float("inf"))
        thruster_motor.setVelocity(0.0)

    surface_camera = robot.getDevice("surface_camera")
    if surface_camera is not None:
        surface_camera.enable(time_step)
    for device_name in ("gps", "compass", "inertial_unit"):
        device = robot.getDevice(device_name)
        if device is not None:
            device.enable(time_step)

    ultrasonic_devices: dict[str, object] = {}
    for ultrasonic_key, device_name in ULTRASONIC_DEVICES.items():
        device = robot.getDevice(device_name)
        if device is not None:
            device.enable(time_step)
            ultrasonic_devices[ultrasonic_key] = device

    active_arena = configured_arena()
    with state.lock:
        state.arena = active_arena
        state.requested_arena = active_arena
    gate_tracker = GateSensorTracker(active_arena)
    agent = None
    if ControllerAgent is not None:
        try:
            agent = ControllerAgent.from_robot(robot, default_camera="surface_camera")
        except Exception:
            agent = None

    http_port = int(os.getenv("ASV_HTTP_PORT", "8889"))
    actuator_port = int(os.getenv("ASV_ACTUATOR_PORT", "9090"))
    telemetry_port = int(os.getenv("ASV_TELEMETRY_PORT", "14550"))
    start_http_stream_server(http_port, gate_tracker)
    start_udp_actuator_receiver(actuator_port)
    start_mavlink_bridge_server(telemetry_port, gate_tracker)

    print("==================================================")
    print(" ASV FULL-PHYSICS SINGLE AZIMUTH THRUSTER ACTIVE")
    print(f" - Arena       : {active_arena}")
    print(f" - Hull        : LOA={BOAT_LOA_M:.3f}m B={BOAT_BEAM_M:.3f}m mass={BOAT_MASS_KG:.1f}kg")
    print(
        f" - Thruster    : max={MAX_THRUST_N:.1f}N "
        f"reverse={'ON' if REVERSE_THRUST_ENABLED else 'OFF'} "
        f"({MAX_REVERSE_THRUST_N:.1f}N), azimuth=+/-{MAX_AZIMUTH_DEG:.0f}deg (RC1), throttle=RC3"
    )
    print(f" - Ultrasonic  : {', '.join(ULTRASONIC_DEVICES)}")
    print(f" - Run Folder  : {run_logger.run_dir}")
    print(f" - Stream URL  : http://127.0.0.1:{http_port}/stream.mjpg")
    print(f" - Vision URL  : http://127.0.0.1:{http_port}/stream_raw.mjpg")
    print(f" - Status API  : http://127.0.0.1:{http_port}/status")
    print("==================================================")

    initial_position = boat_node.getPosition()
    pos_x, pos_y, pos_z = map(float, initial_position)
    nav_heading_deg, yaw_rad = heading_from_orientation(boat_node.getOrientation())
    prev_x, prev_y = pos_x, pos_y
    last_point_log_sim_s = -1.0

    while robot.step(time_step) != -1:
        wall_now = time.monotonic()
        simulation_time_s = float(robot.getTime())
        with state.lock:
            reset_requested = state.reset_requested
            requested_arena = state.requested_arena
            state.reset_requested = False

        if reset_requested:
            active_arena = normalize_arena(requested_arena)
            start_x, start_y = start_position_for_arena(active_arena)
            trans_field.setSFVec3f([start_x, start_y, BOAT_START_Z])
            rot_field.setSFRotation([0.0, 0.0, 1.0, math.pi / 2.0])
            boat_node.resetPhysics()
            if azimuth_motor is not None:
                azimuth_motor.setPosition(0.0)
            if thruster_motor is not None:
                thruster_motor.setVelocity(0.0)
            run_logger.start_new_run()
            gate_tracker.reset(active_arena)
            pos_x, pos_y, pos_z = start_x, start_y, BOAT_START_Z
            prev_x, prev_y = pos_x, pos_y
            nav_heading_deg, yaw_rad = 0.0, math.pi / 2.0
            with state.lock:
                state.arena = active_arena
                state.steering_pwm = NEUTRAL_PWM
                state.throttle_pwm = NEUTRAL_PWM
                state.x, state.y, state.z = pos_x, pos_y, pos_z
                state.heading_deg = nav_heading_deg
                state.speed_mps = 0.0
                state.yaw_rate_dps = 0.0
                state.ultrasonic = {
                    key: ULTRASONIC_MAX_RANGE_M for key in ULTRASONIC_DEVICES
                }
                state.azimuth_angle_deg = 0.0
                state.thrust_force_n = 0.0
                state.control_phase = "RESET"
                state.last_command_at = wall_now
            continue

        if agent is not None:
            agent.begin_step()

        position = boat_node.getPosition()
        pos_x, pos_y, pos_z = map(float, position)
        velocity = boat_node.getVelocity()
        current_speed = math.hypot(float(velocity[0]), float(velocity[1]))
        yaw_rate_dps = math.degrees(float(velocity[5]))
        nav_heading_deg, yaw_rad = heading_from_orientation(boat_node.getOrientation())
        ultrasonic_values = read_ultrasonic_values(ultrasonic_devices)

        with state.lock:
            if wall_now - state.last_command_at > COMMAND_TIMEOUT_S:
                state.throttle_pwm = NEUTRAL_PWM
            steer_pwm = state.steering_pwm
            throttle_pwm = state.throttle_pwm

        gate_tracker.check_crossing(
            prev_x,
            prev_y,
            pos_x,
            pos_y,
            speed=current_speed,
        )
        gate_tracker.check_docking(
            pos_x,
            pos_y,
            nav_heading_deg,
            current_speed,
            simulation_time_s,
        )
        prev_x, prev_y = pos_x, pos_y

        x_min, x_max = wall_x_limits_for_arena(active_arena)
        outside_safe_boundary = (
            pos_x <= x_min or pos_x >= x_max or abs(pos_y) >= WALL_LIMIT_Y
        )
        if gate_tracker.is_docked() or outside_safe_boundary:
            steer_pwm = NEUTRAL_PWM
            throttle_pwm = NEUTRAL_PWM
            with state.lock:
                state.steering_pwm = steer_pwm
                state.throttle_pwm = throttle_pwm

        # RC1 follows the azimuth sign of the single-thruster model.  Keep the
        # mapping explicit at the physics boundary so the route controller's
        # signed heading correction is not altered by the telemetry bridge.
        azimuth_target = max(
            -MAX_AZIMUTH_RAD,
            min(
                MAX_AZIMUTH_RAD,
                (steer_pwm - NEUTRAL_PWM) / 400.0 * MAX_AZIMUTH_RAD,
            ),
        )
        if azimuth_motor is not None:
            azimuth_motor.setPosition(azimuth_target)
        try:
            azimuth_actual = float(azimuth_sensor.getValue()) if azimuth_sensor is not None else azimuth_target
        except Exception:
            azimuth_actual = azimuth_target

        thrust_force_n = thrust_force_from_pwm(throttle_pwm)
        if gate_tracker.is_docked() or outside_safe_boundary:
            thrust_force_n = 0.0
        force_local = [
            thrust_force_n * math.cos(azimuth_actual),
            thrust_force_n * math.sin(azimuth_actual),
            0.0,
        ]
        if abs(thrust_force_n) > 0.0:
            boat_node.addForceWithOffset(force_local, THRUSTER_OFFSET, True)
        if thruster_motor is not None:
            thruster_motor.setVelocity(160.0 * thrust_force_n / MAX_THRUST_N)

        if simulation_time_s - last_point_log_sim_s >= 0.10:
            run_logger.log_point(
                pos_x,
                pos_y,
                nav_heading_deg,
                current_speed,
                steer_pwm,
                throttle_pwm,
                yaw_rate_dps=yaw_rate_dps,
                azimuth_angle_deg=math.degrees(azimuth_actual),
                azimuth_target_deg=math.degrees(azimuth_target),
                thrust_force_n=thrust_force_n,
            )
            last_point_log_sim_s = simulation_time_s

        if surface_camera is not None:
            raw_image = surface_camera.getImage()
            if raw_image:
                try:
                    import cv2
                    import numpy as np

                    width = surface_camera.getWidth()
                    height = surface_camera.getHeight()
                    image = np.frombuffer(raw_image, dtype=np.uint8).reshape((height, width, 4))
                    bgr = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
                    raw_bgr = bgr.copy()
                    raw_ok, raw_encoded = cv2.imencode(
                        ".jpg",
                        raw_bgr,
                        [cv2.IMWRITE_JPEG_QUALITY, 80],
                    )
                    draw_google_maps_nav_overlay(
                        bgr,
                        pos_x,
                        pos_y,
                        nav_heading_deg,
                        current_speed,
                        steer_pwm,
                        throttle_pwm,
                        gate_tracker.snapshot(),
                    )
                    ok, encoded = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ok:
                        with state.lock:
                            state.latest_jpeg = bytes(encoded)
                            if raw_ok:
                                state.latest_raw_jpeg = bytes(raw_encoded)
                except Exception:
                    pass

        with state.lock:
            state.arena = active_arena
            state.x, state.y, state.z = pos_x, pos_y, pos_z
            state.heading_deg = nav_heading_deg
            state.speed_mps = current_speed
            state.yaw_rate_dps = yaw_rate_dps
            state.yaw_rad = yaw_rad
            state.ultrasonic = ultrasonic_values
            state.azimuth_angle_deg = math.degrees(azimuth_actual)
            state.thrust_force_n = thrust_force_n
            state.control_phase = (
                "DOCKED"
                if gate_tracker.is_docked()
                else "E_STOP"
                if outside_safe_boundary
                else "THRUST"
                if thrust_force_n > 0.0
                else "COAST"
            )

        if agent is not None:
            agent.report_step(
                sensors={
                    "x": round(pos_x, 4),
                    "y": round(pos_y, 4),
                    "z": round(pos_z, 4),
                    "heading": round(nav_heading_deg, 2),
                    "speed": round(current_speed, 3),
                    "ultrasonic": {
                        key: round(value, 3)
                        for key, value in ultrasonic_values.items()
                    },
                },
                metrics={
                    "steering_pwm": steer_pwm,
                    "throttle_pwm": throttle_pwm,
                    "thrust_force_n": round(thrust_force_n, 3),
                },
                actuators={
                    "azimuth_target_rad": round(azimuth_target, 4),
                    "azimuth_actual_rad": round(azimuth_actual, 4),
                },
            )


if __name__ == "__main__":
    main()
