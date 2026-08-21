#!/usr/bin/env python3
"""Deterministic batch evaluator for the Webots ASV course."""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.request
from typing import Any


STATUS_URL = "http://127.0.0.1:8889/status"
RESET_URL = "http://127.0.0.1:8889/reset"
START_Y = -11.5
START_TOLERANCE_M = 0.25
DOCK_TOLERANCE_M = 0.75


def normalize_arena(value: object) -> str:
    arena = str(value or "A").strip().upper()
    if arena not in {"A", "B"}:
        raise ValueError("arena harus A atau B")
    return arena


def start_x_for_arena(arena: str) -> float:
    return 11.1 if normalize_arena(arena) == "A" else 18.9


def dock_for_arena(arena: str) -> tuple[float, float]:
    return (11.5, -13.0) if normalize_arena(arena) == "A" else (18.5, -13.0)


def get_status() -> dict[str, Any] | None:
    try:
        req = urllib.request.urlopen(STATUS_URL, timeout=2.0)
        return json.loads(req.read().decode())
    except Exception:
        return None


def is_initial_status(
    status: dict[str, Any],
    *,
    tolerance_m: float = START_TOLERANCE_M,
) -> bool:
    """Return True only for a clean, untouched start position."""
    tracking = status.get("gate_tracking") or {}
    arena = normalize_arena(status.get("arena") or tracking.get("arena") or "A")
    start_x = start_x_for_arena(arena)
    return (
        abs(float(status.get("x", float("inf"))) - start_x) <= tolerance_m
        and abs(float(status.get("y", float("inf"))) - START_Y) <= tolerance_m
        and int(tracking.get("passed_valid", 0)) == 0
        and int(tracking.get("missed", 0)) == 0
        and int(tracking.get("wall_touches", 0)) == 0
        and int(tracking.get("buoy_touches", 0)) == 0
        and int(tracking.get("marker_progress_count", 0)) == 0
    )


def is_docked_status(status: dict[str, Any]) -> bool:
    """Return True only after gates, both markers, and final blue dock complete."""
    tracking = status.get("gate_tracking") or {}
    if bool(tracking.get("docked", False)):
        return True
    if int(tracking.get("passed_valid", 0)) < int(tracking.get("total_gates", 10)):
        return False
    if int(tracking.get("markers_passed_valid", 0)) < int(
        tracking.get("total_markers", 2)
    ):
        return False
    try:
        x = float(status["x"])
        y = float(status["y"])
    except (KeyError, TypeError, ValueError):
        return False
    target = tracking.get("dock_target")
    if isinstance(target, list) and len(target) == 2:
        dock_x, dock_y = float(target[0]), float(target[1])
    else:
        arena = normalize_arena(status.get("arena") or tracking.get("arena") or "A")
        dock_x, dock_y = dock_for_arena(arena)
    return math.hypot(dock_x - x, dock_y - y) <= DOCK_TOLERANCE_M


def reset_simulation(arena: str = "A") -> None:
    selected = normalize_arena(arena)
    request = urllib.request.Request(f"{RESET_URL}?arena={selected}", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=3.0) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Webots reset returned HTTP {response.status}")
    except Exception as exc:
        raise RuntimeError(
            "Tidak bisa reset Webots. Pastikan world/controller berjalan di port 8889."
        ) from exc


def wait_for_initial_status(
    timeout_s: float = 10.0,
    arena: str = "A",
) -> dict[str, Any]:
    selected = normalize_arena(arena)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = get_status()
        if status and normalize_arena(status.get("arena", "A")) == selected and is_initial_status(status):
            return status
        time.sleep(0.2)
    raise RuntimeError(
        "Webots tidak mencapai kondisi awal bersih "
        f"Arena {selected} ({start_x_for_arena(selected)}, {START_Y}) dalam {timeout_s:.1f}s."
    )


def run_batch_evaluation(
    max_duration_s: float = 300.0,
    arena: str = "A",
) -> dict[str, object]:
    selected = normalize_arena(arena)
    print("\n=======================================================")
    print("Memulai Batch Evaluasi Navigasi Vision Otonom...")
    print("=======================================================")

    reset_simulation(selected)
    wait_for_initial_status(arena=selected)
    start_time = time.monotonic()

    while time.monotonic() - start_time < max_duration_s:
        status = get_status()
        if not status:
            time.sleep(1.0)
            continue

        tracking = status.get("gate_tracking") or {}
        passed = int(tracking.get("passed_valid", 0))
        missed = int(tracking.get("missed", 0))
        buoy_hits = int(tracking.get("buoy_touches", 0))
        wall_hits = int(tracking.get("wall_touches", 0))
        total = int(tracking.get("total_gates", 10))
        score_pct = float(tracking.get("score_percent", 0.0))
        pos_x = float(status.get("x", 0.0))
        pos_y = float(status.get("y", 0.0))
        speed = float(status.get("speed_mps", 0.0))
        hdg = float(status.get("heading_deg", 0.0))
        gates = tracking.get("gates") or {}
        gate_10_status = (gates.get("gate_10") or {}).get("status", "PENDING")
        markers_passed = int(tracking.get("markers_passed_valid", 0))
        markers_total = int(tracking.get("total_markers", 2))
        docked = is_docked_status(status)

        elapsed = time.monotonic() - start_time
        print(
            f"[{elapsed:4.1f}s] Pos: [{pos_x:5.2f}, {pos_y:5.2f}] "
            f"Hdg: {hdg:5.1f}° Spd: {speed:4.2f}m/s | "
            f"Gate: {passed}/{total} ({score_pct:4.1f}%) | "
            f"Marker: {markers_passed}/{markers_total} | "
            f"Buoy Hit: {buoy_hits} | Wall Hit: {wall_hits} | "
            f"Gate 10: {gate_10_status} | Dock: {'OK' if docked else '...'}",
            end="\r",
            flush=True,
        )
        if wall_hits > 0:
            print(
                f"\n\n>>> [GAGAL - WALL HIT] Sensor pembatas dinding aktif "
                f"({wall_hits} benturan)! Menghentikan batch."
            )
            break
        if docked:
            print("\n\n>>> [SUKSES] 10 gate, 2 marker, dan docking selesai.")
            break
        if missed + passed >= 10 and gate_10_status != "PASSED_VALID":
            print("\n\n>>> [SELESAI] Semua gate diproses, tetapi Gate 10 tidak valid.")
            break
        time.sleep(0.5)

    print()
    status = get_status() or {}
    tracking = status.get("gate_tracking") or {}
    return {
        "run_id": tracking.get("run_id"),
        "arena": tracking.get("arena", selected),
        "log_dir": tracking.get("log_dir"),
        "passed_valid": tracking.get("passed_valid", 0),
        "missed": tracking.get("missed", 0),
        "buoy_touches": tracking.get("buoy_touches", 0),
        "wall_touches": tracking.get("wall_touches", 0),
        "score_percent": tracking.get("score_percent", 0.0),
        "markers_passed_valid": tracking.get("markers_passed_valid", 0),
        "markers_missed": tracking.get("markers_missed", 0),
        "markers": tracking.get("markers", {}),
        "docked": tracking.get("docked", is_docked_status(status)),
        "gates": tracking.get("gates", {}),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluasi batch ASV Webots Arena A/B")
    parser.add_argument("--arena", choices=("A", "B", "a", "b"), default="A")
    parser.add_argument("--duration", type=float, default=300.0)
    arguments = parser.parse_args()
    print("\n--- Ringkasan Hasil Batch ---")
    print(
        json.dumps(
            run_batch_evaluation(arguments.duration, arguments.arena),
            indent=2,
        )
    )
