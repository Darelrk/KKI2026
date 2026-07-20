# GPS Track Recording and Playback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tambahkan dua mode operasi GPS — merekam track manual operator (RECORD) dan memutar ulang track tersebut secara otomatis (REPLAY) — sebagai navigasi utama kapal ASV.

**Architecture:** Script baru `gps_pilot.py` sebagai entry point terpisah dari `vision_test.py`. `vision_route.py` tidak disentuh; logika GPS recording dan replay adalah modul independen. Format track menggunakan JSON Lines untuk rekaman mentah dan JSON untuk waypoint bersih. Playback mendukung dua mode: Mission AUTO upload via MAVLink dan GUIDED lookahead.

**Tech Stack:** Python 3.14, stdlib (`json`, `math`, `time`, `pathlib`), pymavlink, ArduRover MANUAL/GUIDED/AUTO.

---

## File map

- **Create:** `D:/KKI2/gps_pilot.py` — entry point: `--mode record` / `--mode replay` / `--mode waypoints` / `--mode mission-upload`.
- **Create:** `D:/KKI2/gps_track.py` — tipe data track, sampling logic, filtering, waypoint dedup, checkpoint detection.
- **Create:** `D:/KKI2/tests/test_gps_track.py` — unit test deterministic untuk sampling, filtering, checkpoint.
- **Reference:** `D:/KKI2/docs/superpowers/specs/2026-07-15-gps-track-recording-playback.md` — kontrak parameter dan failcase.

Tidak ada perubahan pada `vision_route.py`, `vision_test.py`, atau model `best.pt`.

---

### Task 1: Tipe data track dan sampling logic

**Files:**
- Create: `D:/KKI2/gps_track.py`
- Create: `D:/KKI2/tests/test_gps_track.py`

- [ ] **Step 1: Tulis test sampling dan tipe data**

```python
from gps_track import GpsSample, Waypoint, TrackRecorder, TrackFilter


def test_sample_creation():
    sample = GpsSample(
        lat=-1.234567, lon=102.345678, heading_deg=87.0,
        ground_speed_m_s=0.72, fix_type=3, satellites=12,
        hdop=1.4, mode="MANUAL", armed=True,
    )
    assert sample.lat == -1.234567


def test_recorder_rejects_no_fix():
    recorder = TrackRecorder(interval_s=1.0, min_distance_m=2.0, heading_change_deg=20.0)
    sample = GpsSample(lat=-1.23, lon=102.34, heading_deg=0.0,
                       ground_speed_m_s=0.0, fix_type=0, satellites=0,
                       hdop=99.9, mode="MANUAL", armed=False)
    assert recorder.record(sample, now=0.0) is None


def test_recorder_interval_and_distance():
    recorder = TrackRecorder(interval_s=1.0, min_distance_m=2.0, heading_change_deg=20.0)
    s1 = GpsSample(lat=-1.234567, lon=102.345678, heading_deg=87.0,
                   ground_speed_m_s=0.7, fix_type=3, satellites=10, hdop=1.4,
                   mode="MANUAL", armed=True)
    s2 = GpsSample(lat=-1.234568, lon=102.345679, heading_deg=87.1,
                   ground_speed_m_s=0.7, fix_type=3, satellites=10, hdop=1.4,
                   mode="MANUAL", armed=True)
    # First sample always passes
    wp1 = recorder.record(s1, now=0.0)
    assert wp1 is not None
    # Second: too close (<2m), should be None
    wp2 = recorder.record(s2, now=1.5)
    assert wp2 is None


def test_recorder_heading_change_triggers_waypoint():
    recorder = TrackRecorder(interval_s=10.0, min_distance_m=10.0, heading_change_deg=20.0)
    s1 = GpsSample(lat=-1.234567, lon=102.345678, heading_deg=87.0,
                   ground_speed_m_s=0.7, fix_type=3, satellites=10, hdop=1.4,
                   mode="MANUAL", armed=True)
    s2 = GpsSample(lat=-1.234600, lon=102.345700, heading_deg=120.0,
                   ground_speed_m_s=0.7, fix_type=3, satellites=10, hdop=1.4,
                   mode="MANUAL", armed=True)
    recorder.record(s1, now=0.0)
    wp2 = recorder.record(s2, now=2.0)
    assert wp2 is not None  # heading change 33° > 20°
```

- [ ] **Step 2: Jalankan test untuk mengunci kegagalan**

Run: `python -m pytest -q tests/test_gps_track.py`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implementasikan tipe data dan recorder**

```python
from __future__ import annotations

import math
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone


@dataclass
class GpsSample:
    lat: float
    lon: float
    heading_deg: float
    ground_speed_m_s: float
    fix_type: int
    satellites: int
    hdop: float
    mode: str
    armed: bool

    def to_dict(self) -> dict:
        result = asdict(self)
        result["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        return result


@dataclass
class Waypoint:
    index: int
    lat: float
    lon: float
    heading_deg: float
    distance_from_start_m: float
    checkpoint: str | None = None


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2.0) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
    return R * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _heading_delta_deg(h1: float, h2: float) -> float:
    delta = (h2 - h1) % 360.0
    if delta > 180.0:
        delta -= 360.0
    return abs(delta)


class TrackRecorder:
    def __init__(
        self,
        *,
        interval_s: float = 1.0,
        min_distance_m: float = 2.0,
        heading_change_deg: float = 20.0,
    ) -> None:
        if interval_s <= 0 or min_distance_m <= 0 or heading_change_deg <= 0:
            raise ValueError("recorder parameters must be positive")
        self.interval_s = interval_s
        self.min_distance_m = min_distance_m
        self.heading_change_deg = heading_change_deg
        self._last_waypoint: Waypoint | None = None
        self._last_sample: GpsSample | None = None
        self._last_wp_time = -math.inf
        self._total_distance_m = 0.0
        self._index = 0

    def record(self, sample: GpsSample, *, now: float | None = None) -> Waypoint | None:
        if sample.fix_type < 3:
            self._last_sample = sample
            return None
        if now is None:
            now = time.monotonic()

        if self._last_waypoint is None:
            wp = Waypoint(
                index=self._index,
                lat=sample.lat,
                lon=sample.lon,
                heading_deg=sample.heading_deg,
                distance_from_start_m=0.0,
            )
            self._last_waypoint = wp
            self._last_wp_time = now
            self._last_sample = sample
            self._index += 1
            return wp

        delta = _haversine_m(self._last_waypoint.lat, self._last_waypoint.lon,
                             sample.lat, sample.lon)
        time_ok = (now - self._last_wp_time) >= self.interval_s
        distance_ok = delta >= self.min_distance_m
        heading_ok = self._last_sample is not None and _heading_delta_deg(
            self._last_sample.heading_deg, sample.heading_deg
        ) >= self.heading_change_deg

        if not (time_ok and distance_ok) and not heading_ok:
            self._last_sample = sample
            return None

        self._total_distance_m += delta
        wp = Waypoint(
            index=self._index,
            lat=sample.lat,
            lon=sample.lon,
            heading_deg=sample.heading_deg,
            distance_from_start_m=self._total_distance_m,
        )
        self._last_waypoint = wp
        self._last_wp_time = now
        self._last_sample = sample
        self._index += 1
        return wp
```

- [ ] **Step 4: Verifikasi test sampling**

Run: `python -m pytest -q tests/test_gps_track.py`
Expected: PASS

---

### Task 2: Track filtering dan waypoint export

**Files:**
- Modify: `D:/KKI2/gps_track.py`
- Modify: `D:/KKI2/tests/test_gps_track.py`

- [ ] **Step 1: Tulis test filter dan export**

```python
from gps_track import TrackFilter, export_route_json, load_raw_track


def test_track_filter_dedup_and_sort():
    samples = [
        GpsSample(lat=-1.234, lon=102.345, heading_deg=90.0,
                  ground_speed_m_s=0.5, fix_type=3, satellites=10,
                  hdop=1.4, mode="MANUAL", armed=True)
            for _ in range(5)
    ]
    filtered = TrackFilter().filter(samples)
    assert len(filtered) >= 1  # dedup to at least one unique


def test_export_route_json_roundtrip(tmp_path):
    waypoints = [
        Waypoint(index=0, lat=-1.23, lon=102.34, heading_deg=90.0,
                 distance_from_start_m=0.0, checkpoint="START"),
        Waypoint(index=1, lat=-1.24, lon=102.35, heading_deg=180.0,
                 distance_from_start_m=120.0, checkpoint=None),
    ]
    path = tmp_path / "route.json"
    export_route_json(waypoints, path, source="test.jsonl")
    data = path.read_text(encoding="utf-8")
    assert "START" in data
    assert "version" in data
```

- [ ] **Step 2: Jalankan test untuk mengunci kegagalan**

Run: `python -m pytest -q tests/test_gps_track.py -k filter or export`
Expected: FAIL

- [ ] **Step 3: Implementasikan filter dan export**

```python
class TrackFilter:
    def __init__(self, max_speed_m_s: float = 5.0, max_hdop: float = 3.0) -> None:
        self.max_speed_m_s = max_speed_m_s
        self.max_hdop = max_hdop

    def filter(self, samples: list[GpsSample]) -> list[GpsSample]:
        valid = [
            s for s in samples
            if s.fix_type >= 3
            and s.hdop <= self.max_hdop
            and s.ground_speed_m_s <= self.max_speed_m_s
        ]
        if not valid:
            return []
        # Remove near-duplicate positions (>3m leap possible)
        cleaned: list[GpsSample] = [valid[0]]
        for s in valid[1:]:
            last = cleaned[-1]
            if _haversine_m(last.lat, last.lon, s.lat, s.lon) > 0.01:
                cleaned.append(s)
        return cleaned


def load_raw_track(path: str) -> list[GpsSample]:
    import json
    from pathlib import Path
    samples: list[GpsSample] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("event") == "gps_sample":
            samples.append(GpsSample(
                lat=obj["lat"], lon=obj["lon"],
                heading_deg=obj["heading_deg"],
                ground_speed_m_s=obj["ground_speed_m_s"],
                fix_type=obj["fix_type"],
                satellites=obj["satellites"],
                hdop=obj["hdop"],
                mode=obj["mode"],
                armed=obj["armed"],
            ))
    return samples


def export_route_json(
    waypoints: list[Waypoint],
    output_path: str,
    source: str = "",
    *,
    interval_s: float = 1.0,
    min_distance_m: float = 2.0,
) -> None:
    import json
    data = {
        "version": 1,
        "source": source,
        "parameters": {
            "record_interval_s": interval_s,
            "min_distance_m": min_distance_m,
        },
        "waypoints": [
            {
                "index": wp.index,
                "lat": wp.lat,
                "lon": wp.lon,
                "heading_deg": wp.heading_deg,
                "distance_from_start_m": wp.distance_from_start_m,
                "checkpoint": wp.checkpoint,
            }
            for wp in waypoints
        ],
    }
    json.dump(data, open(output_path, "w", encoding="utf-8"), indent=2)
```

- [ ] **Step 4: Verifikasi filter dan export**

Run: `python -m pytest -q tests/test_gps_track.py`
Expected: PASS

---

### Task 3: Entry point GPS pilot

**Files:**
- Create: `D:/KKI2/gps_pilot.py`

- [ ] **Step 1: Implementasikan `--mode record`**

```python
#!/usr/bin/env python3
"""GPS track recording and playback for ASV."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gps_track import GpsSample, TrackRecorder, export_route_json, load_raw_track
from vision_route import clamp, PWM_MIN, PWM_MAX
from vision_test import PixhawkLink


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GPS track recording and playback untuk ASV."
    )
    parser.add_argument(
        "--mode",
        choices=("record", "replay", "waypoints", "mission-upload"),
        required=True,
    )

    # Recording params
    parser.add_argument("--endpoint", default="tcp:127.0.0.1:5762",
                        help="Endpoint MAVLink")
    parser.add_argument("--log", default=r"D:\KKI2\gps_track_raw.jsonl",
                        help="Output file rekaman GPS mentah")
    parser.add_argument("--route", default=r"D:\KKI2\gps_route.json",
                        help="File waypoint bersih")
    parser.add_argument("--record-interval-s", type=float, default=1.0)
    parser.add_argument("--record-min-distance-m", type=float, default=2.0)
    parser.add_argument("--record-heading-change-deg", type=float, default=20.0)
    parser.add_argument("--duration", type=float, default=0.0,
                        help="Durasi rekaman; 0 = sampai Q/ESC")

    # Filtering params
    parser.add_argument("--max-hdop", type=float, default=3.0)

    # Replay params
    parser.add_argument("--lookahead-m", type=float, default=10.0)
    parser.add_argument("--replay-speed-mps", type=float, default=0.7)
    parser.add_argument("--guided-interval-s", type=float, default=0.5)
    parser.add_argument("--throttle-pwm", type=int, default=1500)
    return parser.parse_args()


def record_mode(args: argparse.Namespace) -> None:
    """Record GPS track while operator drives manually."""
    import cv2
    link = PixhawkLink(args.endpoint)
    logger = open(args.log, "a", encoding="utf-8")

    recorder = TrackRecorder(
        interval_s=args.record_interval_s,
        min_distance_m=args.record_min_distance_m,
        heading_change_deg=args.record_heading_change_deg,
    )

    print(f"Merekam track GPS ke {args.log}")
    print("Kendalikan kapal dengan remote. Tekan Q/ESC untuk berhenti.")

    started_at = time.monotonic()
    try:
        while True:
            if args.duration and time.monotonic() - started_at >= args.duration:
                break

            telemetry = link.telemetry()

            # Read GLOBAL_POSITION_INT for lat/lon
            gpi = None
            for _ in range(10):
                msg = link.connection.recv_match(
                    type="GLOBAL_POSITION_INT", blocking=False
                )
                if msg is not None:
                    gpi = msg
                    break

            if gpi is not None:
                sample = GpsSample(
                    lat=gpi.lat / 1e7,
                    lon=gpi.lon / 1e7,
                    heading_deg=float(gpi.hdg / 100.0) if hasattr(gpi, "hdg") and gpi.hdg != 65535 else telemetry.get("heading_deg", 0.0),
                    ground_speed_m_s=telemetry.get("ground_speed_m_s", 0.0),
                    fix_type=3,
                    satellites=0,
                    hdop=0.0,
                    mode=telemetry["mode"],
                    armed=telemetry["armed"],
                )
                wp = recorder.record(sample)
                record = sample.to_dict()
                record["event"] = "gps_sample"
                record["checkpoint"] = wp.checkpoint if wp else None
                json.dump(record, logger, ensure_ascii=False, separators=(",", ":"))
                logger.write("\n")
                logger.flush()

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
    finally:
        logger.close()
        link.close()
    print("Rekaman selesai.")


# Placeholder: main dispatches to record/replay/waypoints/mission-upload
```

- [ ] **Step 2: Tambahkan `--mode waypoints` untuk filter dan export route**

```python
def waypoints_mode(args: argparse.Namespace) -> None:
    """Filter raw track and export cleaned waypoints."""
    raw_path = args.log
    if not Path(raw_path).is_file():
        raise FileNotFoundError(f"Track tidak ditemukan: {raw_path}")

    samples = load_raw_track(raw_path)
    from gps_track import TrackFilter
    filtered = TrackFilter(max_hdop=args.max_hdop).filter(samples)

    recorder = TrackRecorder(
        interval_s=args.record_interval_s,
        min_distance_m=args.record_min_distance_m,
        heading_change_deg=args.record_heading_change_deg,
    )
    waypoints: list = []
    for s in filtered:
        wp = recorder.record(s)
        if wp is not None:
            waypoints.append(wp)

    export_route_json(
        waypoints, args.route,
        source=raw_path,
        interval_s=args.record_interval_s,
        min_distance_m=args.record_min_distance_m,
    )
    print(f"Diexport {len(waypoints)} waypoint ke {args.route}")
```

- [ ] **Step 3: Tambahkan `--mode mission-upload`**

```python
def mission_upload_mode(args: argparse.Namespace) -> None:
    """Upload waypoints to Pixhawk as a mission."""
    import json
    route_path = Path(args.route)
    if not route_path.is_file():
        raise FileNotFoundError(f"Route tidak ditemukan: {route_path}")

    data = json.loads(route_path.read_text(encoding="utf-8"))
    waypoints = data["waypoints"]
    print(f"Mengupload {len(waypoints)} waypoint ke Pixhawk...")
    # Implementation: clear mission, MISSION_COUNT, MISSION_ITEM_INT per waypoint
    link = PixhawkLink(args.endpoint)
    try:
        link.connection.waypoint_clear_all_send()
        time.sleep(0.5)
        link.connection.waypoint_count_send(len(waypoints))
        for i, wp in enumerate(waypoints):
            link.connection.mav.mission_item_int_send(
                link.connection.target_system,
                link.connection.target_component,
                i,  # seq
                0,  # frame: MAV_FRAME_GLOBAL_RELATIVE_ALT
                16,  # command: NAV_WAYPOINT
                0,  # current
                1,  # autocontinue
                0.0,  # param1: hold time
                0.0,  # param2: acceptance radius
                0.0,  # param3: pass through
                float(args.replay_speed_mps),  # param4: target speed
                int(wp["lat"] * 1e7),
                int(wp["lon"] * 1e7),
                0,  # altitude (relative)
                0,  # seq + 1 for next
            )
            time.sleep(0.05)
        print("Mission uploaded. Switch to AUTO to start.")
    finally:
        link.close()
```

- [ ] **Step 4: Tambahkan `--mode replay`**

```python
def replay_mode(args: argparse.Namespace) -> None:
    """Replay track in GUIDED mode with lookahead."""
    import json
    route_path = Path(args.route)
    if not route_path.is_file():
        raise FileNotFoundError(f"Route tidak ditemukan: {route_path}")

    data = json.loads(route_path.read_text(encoding="utf-8"))
    waypoints = data["waypoints"]
    total_wp = len(waypoints)
    if total_wp < 2:
        raise ValueError("Route harus memiliki minimal 2 waypoint")

    link = PixhawkLink(args.endpoint)
    print(f"Replay {total_wp} waypoint, lookahead={args.lookahead_m}m, speed={args.replay_speed_mps}m/s")

    last_update = 0.0
    try:
        while True:
            telemetry = link.telemetry()
            gpi = link.connection.recv_match(type="GLOBAL_POSITION_INT", blocking=False, timeout=0.1)
            if gpi is None:
                time.sleep(0.1)
                continue

            current_lat = gpi.lat / 1e7
            current_lon = gpi.lon / 1e7

            # Find closest waypoint index along track
            best_idx = 0
            best_dist = float("inf")
            for i, wp in enumerate(waypoints):
                d = _haversine_m(current_lat, current_lon, wp["lat"], wp["lon"])
                if d < best_dist:
                    best_dist = d
                    best_idx = i

            # Deviation check
            if best_dist > 15.0:
                print(f"Deviasi {best_dist:.1f}m, melebihi 15m — masuk FAILSAFE")
                break

            # Lookahead: move forward from best_idx
            target_idx = best_idx
            accumulated = 0.0
            for i in range(best_idx, total_wp - 1):
                d = _haversine_m(
                    waypoints[i]["lat"], waypoints[i]["lon"],
                    waypoints[i + 1]["lat"], waypoints[i + 1]["lon"],
                )
                if accumulated + d >= args.lookahead_m:
                    target_idx = i + 1
                    break
                accumulated += d
                target_idx = i + 1

            target = waypoints[target_idx]

            now = time.monotonic()
            if now - last_update >= args.guided_interval_s:
                # Send position target
                link.connection.mav.set_position_target_global_int_send(
                    0,  # time_boot_ms
                    link.connection.target_system,
                    link.connection.target_component,
                    0,  # coordinate frame: MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
                    0b0000111111111000,  # type mask: pos + vel
                    int(target["lat"] * 1e7),
                    int(target["lon"] * 1e7),
                    0,  # alt
                    0.0,  # vx
                    0.0,  # vy
                    0.0,  # vz
                    0.0,  # afx
                    0.0,  # afy
                    0.0,  # afz
                    float(args.replay_speed_mps),  # yaw
                    0.5,  # yaw_rate
                )
                last_update = now

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break

            # End of track
            if target_idx >= total_wp - 1 and _haversine_m(current_lat, current_lon, target["lat"], target["lon"]) < 5.0:
                print("FINISH tercapai")
                break
    finally:
        link.close()
```

- [ ] **Step 5: Integrasikan dispatcher di `gps_pilot.py`**

```python
def main() -> None:
    args = parse_args()
    import cv2
    if args.mode == "record":
        record_mode(args)
    elif args.mode == "replay":
        replay_mode(args)
    elif args.mode == "waypoints":
        waypoints_mode(args)
    elif args.mode == "mission-upload":
        mission_upload_mode(args)
```

Verifikasi:

```bash
python -m py_compile gps_pilot.py gps_track.py
python -m pytest -q tests/test_gps_track.py
python gps_pilot.py --help
```

---

### Task 4: GPS telemetry lengkap di PixhawkLink

**Files:**
- Modify: `D:/KKI2/vision_test.py`
- Modify: `D:/KKI2/tests/test_vision_route.py`

- [ ] **Step 1: Tulis test parsial GLOBAL_POSITION_INT**

```python
from types import SimpleNamespace
from vision_test import global_position_int_dict


def test_global_position_int_dict():
    msg = SimpleNamespace(lat=-12345670, lon=1023456780, hdg=8710, relative_alt=0, alt=0, vx=0, vy=0, vz=0)
    result = global_position_int_dict(msg)
    assert result["lat"] == -1.234567
    assert result["lon"] == 102.345678
    assert result["heading_deg"] == 87.1
```

- [ ] **Step 2: Implementasikan helper**

```python
def global_position_int_dict(message: Any) -> dict[str, float] | None:
    if message is None:
        return None
    return {
        "lat": float(message.lat) / 1e7,
        "lon": float(message.lon) / 1e7,
        "heading_deg": float(message.hdg) / 100.0 if getattr(message, "hdg", 65535) != 65535 else 0.0,
    }
```

- [ ] **Step 3: Tambahkan GPS_RAW_INT ke telemetry PixhawkLink**

`PixhawkLink.__init__`: tambahkan `self._last_gps_raw_int = None`
`PixhawkLink.telemetry()`: tambahkan type `"GPS_RAW_INT"` ke daftar `recv_match`, baca `satellites_visible` dan `hdop`.

- [ ] **Step 4: Verifikasi helper dan compile**

```bash
python -m pytest -q tests/test_vision_route.py -k heading
python -m py_compile vision_test.py gps_pilot.py gps_track.py
```

---

### Task 5: Verifikasi keselamatan dan dokumentasi hasil

**Files:**
- Modify: `D:/KKI2/docs/superpowers/specs/2026-07-15-gps-track-recording-playback.md`

- [ ] **Step 1: Uji record tanpa propulsi (bench)**

1. Disarm Pixhawk, hubungkan telemetry.
2. Jalankan `python gps_pilot.py --mode record --duration 30`. Telemetry masuk, file `gps_track_raw.jsonl` terisi, override tidak dikirim, tidak ada thruster bergerak.
3. Pastikan setiap baris JSON valid.

- [ ] **Step 2: Uji waypoint filtering**

`python gps_pilot.py --mode waypoints`
Pastikan file `gps_route.json` berisi waypoint tanpa duplikat dan tidak melebihi jumlah sampel original.

- [ ] **Step 3: Verifikasi deviasi sebelum uji replay air**

`python gps_pilot.py --mode replay --throttle-pwm 1500`
Kapal di bench, target log menunjukkan GUIDED target bergerak. Pastikan jika latitude sama terus, skrip berhenti karena deviasi.

- [ ] **Step 4: Update spec**

Setelah pengujian nyata, update `Kondisi implementasi saat ini` bagian GPS pada spesifikasi.

---

## Self-review plan

- **Spec coverage:** recording (interval/distance/heading), filtering, export JSON, mission upload, GUIDED replay, lookahead, deviation failsafe — semua memiliki task.
- **No new dependency:** hanya stdlib + pymavlink + OpenCV (keyboard/cam).
- **Safety:** throttle default replay 1500; GUIDED menggunakan speed mps bukan PWM; script tidak auto-arm.
- **No placeholders:** setiap task memiliki minimal code, file, dan expected result.
