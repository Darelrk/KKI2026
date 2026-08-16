#!/usr/bin/env python3
"""Automated Simulation Batch Evaluator for ASV KKI 2026.

Loops pure vision-guided runs in Webots until the boat successfully
clears the course through the final buoy (Gate 10) with 0 errors.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def get_status() -> dict[str, object] | None:
    try:
        req = urllib.request.urlopen("http://127.0.0.1:8889/status", timeout=2.0)
        return json.loads(req.read().decode())
    except Exception:
        return None


def run_batch_evaluation(max_duration_s: float = 80.0) -> dict[str, object]:
    print("\n=======================================================")
    print("Memulai Batch Evaluasi Navigasi Vision Otonom...")
    print("=======================================================")

    start_time = time.monotonic()
    last_reported_gate = None

    while time.monotonic() - start_time < max_duration_s:
        status = get_status()
        if not status:
            time.sleep(1.0)
            continue

        gt = status.get("gate_tracking", {})
        passed = gt.get("passed_valid", 0)
        missed = gt.get("missed", 0)
        buoy_hits = gt.get("buoy_touches", 0)
        wall_hits = gt.get("wall_touches", 0)
        total = gt.get("total_gates", 10)
        score_pct = gt.get("score_percent", 0.0)
        pos_x = status.get("x", 0.0)
        pos_y = status.get("y", 0.0)
        speed = status.get("speed_mps", 0.0)
        hdg = status.get("heading_deg", 0.0)

        gates = gt.get("gates", {})
        gate_10 = gates.get("gate_10", {})
        gate_10_status = gate_10.get("status", "PENDING")

        elapsed = time.monotonic() - start_time
        print(
            f"[{elapsed:4.1f}s] Pos: [{pos_x:5.2f}, {pos_y:5.2f}] Hdg: {hdg:5.1f}° Spd: {speed:4.2f}m/s | "
            f"Gate: {passed}/{total} ({score_pct:4.1f}%) | Buoy Hit: {buoy_hits} | Wall Hit: {wall_hits} | Gate 10: {gate_10_status}",
            end="\r",
            flush=True,
        )
        if wall_hits > 0:
            print(f"\n\n>>> [GAGAL - WALL HIT] Sensor pembatas dinding aktif ({wall_hits} benturan)! Menghentikan batch segera untuk hemat waktu.")
            break

        if gate_10_status == "PASSED_VALID":
            print("\n\n>>> [SUKSES] Kapal BERHASIL melewati Gerbang Akhir (Gate 10) secara VALID!")
            break

        if missed + passed >= 10:
            print("\n\n>>> [SELESAI] Semua 10 gate telah diproses pada batch ini.")
            break
        time.sleep(0.5)

    print()
    status = get_status() or {}
    gt = status.get("gate_tracking", {})
    return {
        "run_id": gt.get("run_id"),
        "log_dir": gt.get("log_dir"),
        "passed_valid": gt.get("passed_valid", 0),
        "missed": gt.get("missed", 0),
        "buoy_touches": gt.get("buoy_touches", 0),
        "wall_touches": gt.get("wall_touches", 0),
        "score_percent": gt.get("score_percent", 0.0),
        "gates": gt.get("gates", {}),
    }


if __name__ == "__main__":
    result = run_batch_evaluation()
    print("\n--- Ringkasan Hasil Batch ---")
    print(json.dumps(result, indent=2))
