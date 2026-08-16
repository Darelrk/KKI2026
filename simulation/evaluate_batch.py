#!/usr/bin/env python3
"""Deterministic batch evaluator for the Webots ASV course."""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any


STATUS_URL = "http://127.0.0.1:8889/status"
RESET_URL = "http://127.0.0.1:8889/reset"
START_X = 10.0
START_Y = -11.5
START_TOLERANCE_M = 0.25


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
    return (
        abs(float(status.get("x", float("inf"))) - START_X) <= tolerance_m
        and abs(float(status.get("y", float("inf"))) - START_Y) <= tolerance_m
        and int(tracking.get("passed_valid", 0)) == 0
        and int(tracking.get("missed", 0)) == 0
        and int(tracking.get("wall_touches", 0)) == 0
        and int(tracking.get("buoy_touches", 0)) == 0
    )


def reset_simulation() -> None:
    request = urllib.request.Request(RESET_URL, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=3.0) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Webots reset returned HTTP {response.status}")
    except Exception as exc:
        raise RuntimeError(
            "Tidak bisa reset Webots. Pastikan world/controller berjalan di port 8889."
        ) from exc


def wait_for_initial_status(timeout_s: float = 10.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = get_status()
        if status and is_initial_status(status):
            return status
        time.sleep(0.2)
    raise RuntimeError(
        "Webots tidak mencapai kondisi awal bersih "
        f"({START_X}, {START_Y}) dalam {timeout_s:.1f}s."
    )


def run_batch_evaluation(max_duration_s: float = 80.0) -> dict[str, object]:
    print("\n=======================================================")
    print("Memulai Batch Evaluasi Navigasi Vision Otonom...")
    print("=======================================================")

    reset_simulation()
    wait_for_initial_status()
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

        elapsed = time.monotonic() - start_time
        print(
            f"[{elapsed:4.1f}s] Pos: [{pos_x:5.2f}, {pos_y:5.2f}] "
            f"Hdg: {hdg:5.1f}° Spd: {speed:4.2f}m/s | "
            f"Gate: {passed}/{total} ({score_pct:4.1f}%) | "
            f"Buoy Hit: {buoy_hits} | Wall Hit: {wall_hits} | "
            f"Gate 10: {gate_10_status}",
            end="\r",
            flush=True,
        )
        if wall_hits > 0:
            print(
                f"\n\n>>> [GAGAL - WALL HIT] Sensor pembatas dinding aktif "
                f"({wall_hits} benturan)! Menghentikan batch."
            )
            break
        if gate_10_status == "PASSED_VALID":
            print("\n\n>>> [SUKSES] Gate 10 PASSED_VALID.")
            break
        if missed + passed >= 10:
            print("\n\n>>> [SELESAI] Semua 10 gate telah diproses.")
            break
        time.sleep(0.5)

    print()
    status = get_status() or {}
    tracking = status.get("gate_tracking") or {}
    return {
        "run_id": tracking.get("run_id"),
        "log_dir": tracking.get("log_dir"),
        "passed_valid": tracking.get("passed_valid", 0),
        "missed": tracking.get("missed", 0),
        "buoy_touches": tracking.get("buoy_touches", 0),
        "wall_touches": tracking.get("wall_touches", 0),
        "score_percent": tracking.get("score_percent", 0.0),
        "gates": tracking.get("gates", {}),
    }


if __name__ == "__main__":
    print("\n--- Ringkasan Hasil Batch ---")
    print(json.dumps(run_batch_evaluation(), indent=2))
