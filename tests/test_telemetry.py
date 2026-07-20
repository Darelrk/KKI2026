from __future__ import annotations

import time

from asv_dashboard_backend.config import BridgeSettings
from asv_dashboard_backend.telemetry import PixhawkTelemetryReader


class FakeMavlinkMessage:
    def __init__(self, message_type: str, **fields: object) -> None:
        self._message_type = message_type
        for key, value in fields.items():
            setattr(self, key, value)

    def get_type(self) -> str:
        return self._message_type


def make_reader() -> PixhawkTelemetryReader:
    return PixhawkTelemetryReader(
        BridgeSettings(
            pixhawk_enabled=True,
            pixhawk_track_max_points=2,
        )
    )


def test_reader_extracts_gps_heading_speed_and_bounded_track() -> None:
    reader = make_reader()
    now = time.monotonic()
    reader._consume_message(FakeMavlinkMessage("HEARTBEAT"), now)
    reader._consume_message(
        FakeMavlinkMessage(
            "GLOBAL_POSITION_INT",
            lat=-612345678,
            lon=1068456789,
            hdg=9123,
            vx=300,
            vy=400,
        ),
        now,
    )
    reader._consume_message(
        FakeMavlinkMessage("VFR_HUD", heading=95, groundspeed=1.5),
        now,
    )

    snapshot = reader.snapshot()

    assert snapshot.connected is True
    assert snapshot.position is not None
    assert snapshot.position.latitude == -61.2345678
    assert snapshot.position.longitude == 106.8456789
    assert snapshot.heading_deg == 95
    assert snapshot.speed_mps == 1.5
    assert len(snapshot.track) == 1


def test_reader_marks_heartbeat_stale_without_dropping_last_position() -> None:
    reader = make_reader()
    reader._last_heartbeat_monotonic = (
        time.monotonic() - reader.settings.pixhawk_heartbeat_timeout - 0.1
    )

    snapshot = reader.snapshot()

    assert snapshot.connected is False
    assert snapshot.position is None
    assert snapshot.track == []


def test_reader_rejects_zero_zero_position_without_gps_fix() -> None:
    reader = make_reader()
    reader._consume_message(
        FakeMavlinkMessage(
            "GLOBAL_POSITION_INT",
            lat=0,
            lon=0,
            hdg=65535,
            vx=0,
            vy=0,
        ),
        time.monotonic(),
    )

    snapshot = reader.snapshot()

    assert snapshot.position is None
    assert snapshot.track == []
