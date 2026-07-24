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

def test_resolve_pixhawk_endpoint_prefers_by_id(monkeypatch) -> None:
    from asv_dashboard_backend.telemetry import _resolve_pixhawk_endpoint

    def fake_glob(pattern: str) -> list[str]:
        if "by-id" in pattern:
            return ["/dev/serial/by-id/usb-ArduPilot_fmuv3_123-if00"]
        return []

    monkeypatch.setattr("glob.glob", fake_glob)
    assert (
        _resolve_pixhawk_endpoint("/dev/ttyACM0")
        == "/dev/serial/by-id/usb-ArduPilot_fmuv3_123-if00"
    )


def test_request_telemetry_streams_sends_stream_all() -> None:
    reader = make_reader()

    class FakeMav:
        def __init__(self) -> None:
            self.sent: list[tuple[object, ...]] = []

        def request_data_stream_send(self, sys: int, comp: int, stream: int, rate: int, start: int) -> None:
            self.sent.append((sys, comp, stream, rate, start))

    class FakeApi:
        MAV_DATA_STREAM_ALL = 0

    class FakeConnection:
        target_system = 1
        target_component = 1

        def __init__(self) -> None:
            self.mav = FakeMav()

    conn = FakeConnection()
    reader._connection = conn
    reader._mavlink_api = FakeApi()

    reader._request_telemetry_streams()

    assert len(conn.mav.sent) == 1
    assert conn.mav.sent[0] == (1, 1, 0, 4, 1)

    # Calling again with same target does not re-send
    reader._request_telemetry_streams()
    assert len(conn.mav.sent) == 1