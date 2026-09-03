from __future__ import annotations

import asyncio
import time

from asv_dashboard_backend.config import BridgeSettings
from asv_dashboard_backend.control import RemoteControlCommand
from asv_dashboard_backend.telemetry import ActuatorCommand, PixhawkTelemetryReader


class FakeMavlinkMessage:
    def __init__(self, message_type: str, **fields: object) -> None:
        self._message_type = message_type
        for key, value in fields.items():
            setattr(self, key, value)

    def get_type(self) -> str:
        return self._message_type


class FakeOverrideMav:
    def __init__(self) -> None:
        self.sent: list[tuple[object, ...]] = []

    def rc_channels_override_send(self, *values: object) -> None:
        self.sent.append(values)


class FakeOverrideConnection:
    target_system = 7
    target_component = 9
    flightmode = "MANUAL"

    def __init__(self) -> None:
        self.mav = FakeOverrideMav()
        self.closed = False

    def close(self) -> None:
        self.closed = True


def make_remote_command(
    *,
    seq: int = 1,
    steering_pwm: int = 1490,
    throttle_pwm: int = 1560,
    enabled: bool = True,
) -> RemoteControlCommand:
    return RemoteControlCommand(
        type="control",
        seq=seq,
        client_sent_at_ms=0,
        steering_pwm=steering_pwm,
        throttle_pwm=throttle_pwm,
        enabled=enabled,
    )


def make_reader() -> PixhawkTelemetryReader:
    return PixhawkTelemetryReader(
        BridgeSettings(
            pixhawk_enabled=True,
            pixhawk_track_max_points=2,
        )
    )


def test_connect_if_due_keeps_mavlink_connection(monkeypatch) -> None:
    reader = make_reader()
    connection = object()

    monkeypatch.setattr(
        "pymavlink.mavutil.mavlink_connection",
        lambda *args, **kwargs: connection,
    )
    reader._request_telemetry_streams = lambda: None  # type: ignore[method-assign]

    asyncio.run(reader._connect_if_due())

    assert reader._connection is connection


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
    reader._consume_message(
        FakeMavlinkMessage(
            "GLOBAL_POSITION_INT",
            lat=-612345678,
            lon=1068456789,
            hdg=9123,
            vx=300,
            vy=400,
        ),
        time.monotonic(),
    )
    reader._last_heartbeat_monotonic = (
        time.monotonic() - reader.settings.pixhawk_heartbeat_timeout - 0.1
    )

    snapshot = reader.snapshot()

    assert snapshot.connected is False
    assert snapshot.position is not None
    assert snapshot.position.latitude == -61.2345678
    assert len(snapshot.track) == 1


def test_reader_hides_stale_heading_and_speed_while_link_is_down() -> None:
    reader = make_reader()
    now = time.monotonic()
    reader._consume_message(FakeMavlinkMessage("HEARTBEAT"), now)
    reader._consume_message(
        FakeMavlinkMessage("VFR_HUD", heading=346, groundspeed=0.0),
        now,
    )

    assert reader.snapshot().heading_deg == 346

    reader._last_heartbeat_monotonic = (
        now - reader.settings.pixhawk_heartbeat_timeout - 0.1
    )
    snapshot = reader.snapshot()

    assert snapshot.connected is False
    assert snapshot.heading_deg is None
    assert snapshot.speed_mps is None


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


def test_unified_worker_only_overrides_fresh_manual_commands() -> None:
    settings = BridgeSettings(
        pixhawk_enabled=True,
        model_actuators_enabled=True,
        actuator_control_token="secret-token",
    )
    reader = PixhawkTelemetryReader(settings)

    class FakeMav:
        def __init__(self) -> None:
            self.sent: list[tuple[object, ...]] = []

        def rc_channels_override_send(self, *values: object) -> None:
            self.sent.append(values)

    class FakeConnection:
        target_system = 1
        target_component = 1
        flightmode = "MANUAL"

        def __init__(self) -> None:
            self.mav = FakeMav()

    connection = FakeConnection()
    reader._connection = connection
    reader._mode = "MANUAL"
    reader._last_heartbeat_monotonic = time.monotonic()
    reader._last_rc_monotonic = time.monotonic()
    reader.submit_actuator_command(
        ActuatorCommand(steering_pwm=1490, throttle_pwm=1560, enabled=True)
    )

    reader._apply_actuator_command()

    # The vision loop can take over one second per frame on the Pi.
    reader._actuator_command_at = time.monotonic() - 1.0
    reader._apply_actuator_command()
    assert connection.mav.sent[-1][2:5] == (1490, 65535, 1560)

    assert connection.mav.sent[-1] == (
        1,
        1,
        1490,
        65535,
        1560,
        65535,
        65535,
        65535,
        65535,
        65535,
    )

    reader._mode = "AUTO"
    reader._apply_actuator_command()
    assert connection.mav.sent[-1] == (1, 1, 0, 0, 0, 0, 0, 0, 0, 0)


def test_unified_worker_releases_override_without_fresh_rc_input() -> None:
    reader = PixhawkTelemetryReader(
        BridgeSettings(
            pixhawk_enabled=True,
            model_actuators_enabled=True,
            actuator_control_token="secret-token",
        )
    )

    class FakeMav:
        def __init__(self) -> None:
            self.sent: list[tuple[object, ...]] = []

        def rc_channels_override_send(self, *values: object) -> None:
            self.sent.append(values)

    class FakeConnection:
        target_system = 1
        target_component = 1
        flightmode = "MANUAL"

        def __init__(self) -> None:
            self.mav = FakeMav()

    connection = FakeConnection()
    reader._connection = connection
    reader._mode = "MANUAL"
    reader._last_heartbeat_monotonic = time.monotonic()
    reader._mode = "AUTO"
    reader.submit_actuator_command(
        ActuatorCommand(steering_pwm=1490, throttle_pwm=1560, enabled=True)
    )

    reader._apply_actuator_command()

    assert connection.mav.sent == []


def test_unified_worker_prioritizes_pilot_rc_stick_deflection() -> None:
    reader = PixhawkTelemetryReader(
        BridgeSettings(
            pixhawk_enabled=True,
            model_actuators_enabled=True,
            actuator_control_token="secret-token",
        )
    )
    class FakeMav:
        def __init__(self) -> None:
            self.sent: list[tuple[object, ...]] = []
        def rc_channels_override_send(self, *values: object) -> None:
            self.sent.append(values)
    class FakeRcMsg:
        def get_type(self) -> str:
            return "RC_CHANNELS"
        chan1_raw = 1750
        chan3_raw = 1500
        chancount = 8

    class FakeConnection:
        target_system = 1
        target_component = 1
        flightmode = "MANUAL"
        def __init__(self) -> None:
            self.mav = FakeMav()

    connection = FakeConnection()
    reader._connection = connection
    reader._mode = "MANUAL"
    now = time.monotonic()
    reader._last_heartbeat_monotonic = now
    reader.submit_actuator_command(
        ActuatorCommand(steering_pwm=1490, throttle_pwm=1560, enabled=True)
    )
    reader._override_active = True

    # Pilot moves steering stick to 1750 PWM (>60 from neutral)
    reader._consume_message(FakeRcMsg(), now)
    reader._apply_actuator_command()

    # Override must be immediately released (0,0) to give pilot 100% priority
    assert connection.mav.sent[-1] == (1, 1, 0, 0, 0, 0, 0, 0, 0, 0)
    assert reader._override_active is False


def make_remote_ready_reader(
    now: float = 10.0,
    *,
    model_actuators_enabled: bool = False,
) -> tuple[PixhawkTelemetryReader, FakeOverrideConnection]:
    reader = PixhawkTelemetryReader(
        BridgeSettings(
            pixhawk_enabled=True,
            remote_control_enabled=True,
            model_actuators_enabled=model_actuators_enabled,
            actuator_control_token="secret-token" if model_actuators_enabled else None,
        )
    )
    connection = FakeOverrideConnection()
    reader._connection = connection
    reader._mode = "MANUAL"
    reader._last_heartbeat_monotonic = now
    reader._last_pilot_input_monotonic = now - 2.0
    return reader, connection


def test_remote_control_applies_fresh_pwm_on_existing_safe_link(
    monkeypatch,
) -> None:
    monkeypatch.setattr("asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.0)
    reader, connection = make_remote_ready_reader()
    command = make_remote_command(steering_pwm=1475, throttle_pwm=1585)

    reader.submit_remote_control(command, "session-a", 10.0)
    reader._apply_actuator_command()

    assert connection.mav.sent == [
        (7, 9, 1475, 65535, 1585, 65535, 65535, 65535, 65535, 65535)
    ]
def test_remote_override_feedback_does_not_trigger_pilot_gate(
    monkeypatch,
) -> None:
    monkeypatch.setattr("asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.0)
    reader, connection = make_remote_ready_reader()
    command = make_remote_command(steering_pwm=1600, throttle_pwm=1500)

    reader.submit_remote_control(command, "session-a", 10.0)
    reader._apply_actuator_command()
    reader._consume_message(
        FakeMavlinkMessage(
            "RC_CHANNELS",
            chan1_raw=1600,
            chan3_raw=1500,
            chancount=8,
        ),
        10.1,
    )

    assert reader.remote_control_rejection_reason() is None
    assert connection.mav.sent[-1][2:5] == (1600, 65535, 1500)
def test_remote_override_feedback_still_detects_different_pilot_input(
    monkeypatch,
) -> None:
    monkeypatch.setattr("asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.0)
    reader, _ = make_remote_ready_reader()
    command = make_remote_command(steering_pwm=1600, throttle_pwm=1500)

    reader.submit_remote_control(command, "session-a", 10.0)
    reader._apply_actuator_command()
    reader._consume_message(
        FakeMavlinkMessage(
            "RC_CHANNELS",
            chan1_raw=1700,
            chancount=8,
            chan3_raw=1500,
        ),
        10.1,
    )

    assert reader.remote_control_rejection_reason() == "pilot_input_active"
def test_missing_rc_receiver_does_not_block_remote_control(
    monkeypatch,
) -> None:
    monkeypatch.setattr("asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.0)
    reader, connection = make_remote_ready_reader()
    reader._consume_message(
        FakeMavlinkMessage(
            "RC_CHANNELS",
            chan1_raw=1575,
            chan3_raw=1500,
            chancount=0,
        ),
        10.1,
    )

    assert reader.remote_control_rejection_reason() is None

    reader.submit_remote_control(
        make_remote_command(steering_pwm=1600, throttle_pwm=1500),
        "session-a",
        10.1,
    )
    reader._apply_actuator_command()

    assert connection.mav.sent[-1][2:5] == (1600, 65535, 1500)


def test_receiver_idle_throttle_offset_does_not_trigger_pilot_gate(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.2
    )
    reader, _ = make_remote_ready_reader()

    reader._consume_message(
        FakeMavlinkMessage(
            "RC_CHANNELS",
            chan1_raw=1501,
            chan3_raw=1433,
            chancount=8,
        ),
        10.1,
    )

    assert reader.remote_control_rejection_reason() is None




def test_remote_control_invalid_mutation_releases_without_sending_bad_pwm(
    monkeypatch,
) -> None:
    monkeypatch.setattr("asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.0)
    reader, connection = make_remote_ready_reader()
    command = make_remote_command(steering_pwm=1475, throttle_pwm=1585)

    reader.submit_remote_control(command, "session-a", 10.0)
    reader._apply_actuator_command()
    assert connection.mav.sent[-1][2:5] == (1475, 65535, 1585)

    command.steering_pwm = 1475.5  # type: ignore[assignment]
    reader._apply_actuator_command()
    assert connection.mav.sent[-1] == (7, 9, 0, 0, 0, 0, 0, 0, 0, 0)

    reader.submit_remote_control(make_remote_command(seq=2), "session-a", 11.0)
    reader._apply_actuator_command()
    command = reader._remote_command
    assert command is not None
    command.throttle_pwm = "1580"  # type: ignore[assignment]
    reader._apply_actuator_command()

    assert connection.mav.sent[-1] == (7, 9, 0, 0, 0, 0, 0, 0, 0, 0)
    assert len(connection.mav.sent) == 4


def test_remote_control_expiry_at_exact_timeout_releases_without_sending_pwm(
    monkeypatch,
) -> None:
    now = [10.0]
    monkeypatch.setattr(
        "asv_dashboard_backend.telemetry.time.monotonic", lambda: now[0]
    )
    reader, connection = make_remote_ready_reader()
    reader.submit_remote_control(make_remote_command(), "session-a", 10.0)

    reader._apply_actuator_command()
    now[0] = 10.5
    reader._apply_actuator_command()

    assert connection.mav.sent == [
        (7, 9, 1490, 65535, 1560, 65535, 65535, 65535, 65535, 65535),
        (7, 9, 0, 0, 0, 0, 0, 0, 0, 0),
    ]


def test_remote_control_expiry_after_timeout_releases_without_sending_again(
    monkeypatch,
) -> None:
    now = [10.0]
    monkeypatch.setattr(
        "asv_dashboard_backend.telemetry.time.monotonic", lambda: now[0]
    )
    reader, connection = make_remote_ready_reader()
    reader.submit_remote_control(make_remote_command(), "session-a", 10.0)

    reader._apply_actuator_command()
    now[0] = 10.501
    reader._apply_actuator_command()
    sent_count = len(connection.mav.sent)
    reader._apply_actuator_command()

    assert connection.mav.sent == [
        (7, 9, 1490, 65535, 1560, 65535, 65535, 65535, 65535, 65535),
        (7, 9, 0, 0, 0, 0, 0, 0, 0, 0),
    ]
    assert sent_count == len(connection.mav.sent)

def test_model_actuator_survives_exact_timeout_boundary(monkeypatch) -> None:
    now = [10.0]
    monkeypatch.setattr(
        "asv_dashboard_backend.telemetry.time.monotonic", lambda: now[0]
    )
    reader, connection = make_remote_ready_reader(model_actuators_enabled=True)
    reader.submit_actuator_command(
        ActuatorCommand(steering_pwm=1510, throttle_pwm=1540, enabled=True)
    )
    reader._apply_actuator_command()

    now[0] = 10.0 + reader.settings.actuator_command_timeout
    reader._last_heartbeat_monotonic = now[0]
    reader._apply_actuator_command()

    assert connection.mav.sent == [
        (7, 9, 1510, 65535, 1540, 65535, 65535, 65535, 65535, 65535),
        (7, 9, 1510, 65535, 1540, 65535, 65535, 65535, 65535, 65535),
    ]


def test_remote_control_owner_mismatch_does_not_clear_slot() -> None:
    reader, _ = make_remote_ready_reader()
    command = make_remote_command()

    reader.submit_remote_control(command, "session-a", 10.0)

    assert reader.clear_remote_control("session-b") is False
    assert reader._remote_command == command
    assert reader._remote_session_id == "session-a"


def test_remote_control_owner_clear_releases_immediately_and_preserves_model(
    monkeypatch,
) -> None:
    monkeypatch.setattr("asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.0)
    reader, connection = make_remote_ready_reader(
        model_actuators_enabled=True,
    )
    model_command = ActuatorCommand(
        steering_pwm=1510,
        throttle_pwm=1540,
        enabled=True,
    )
    reader.submit_actuator_command(model_command)
    reader.submit_remote_control(make_remote_command(), "session-a", 10.0)
    reader._apply_actuator_command()

    assert reader.clear_remote_control("session-a") is True
    assert connection.mav.sent[-1] == (7, 9, 0, 0, 0, 0, 0, 0, 0, 0)
    sent_count = len(connection.mav.sent)
    assert reader.clear_remote_control("session-a") is False
    assert len(connection.mav.sent) == sent_count

    reader._apply_actuator_command()
    assert connection.mav.sent[-1][2:5] == (1510, 65535, 1540)


def test_remote_control_rejection_reason_feature_disabled_blocks_apply() -> None:
    reader = PixhawkTelemetryReader(
        BridgeSettings(pixhawk_enabled=True, remote_control_enabled=False)
    )
    connection = FakeOverrideConnection()
    reader._connection = connection
    reader._mode = "MANUAL"
    reader._last_heartbeat_monotonic = 10.0
    reader._last_pilot_input_monotonic = 8.0
    reader.submit_remote_control(make_remote_command(), "session-a", 10.0)

    assert reader.remote_control_rejection_reason() == "remote_control_disabled"
    reader._apply_actuator_command()
    assert connection.mav.sent == []


def test_remote_control_rejection_reason_reports_pixhawk_unavailable() -> None:
    reader, connection = make_remote_ready_reader()
    reader._connection = None
    reader.submit_remote_control(make_remote_command(), "session-a", 10.0)

    assert reader.remote_control_rejection_reason() == "pixhawk_unavailable"
    reader._apply_actuator_command()
    assert connection.mav.sent == []


def test_remote_control_rejection_reason_reports_stale_heartbeat(
    monkeypatch,
) -> None:
    monkeypatch.setattr("asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.0)
    reader, connection = make_remote_ready_reader()
    reader._last_heartbeat_monotonic = 8.9
    reader.submit_remote_control(make_remote_command(), "session-a", 10.0)

    assert reader.remote_control_rejection_reason() == "pixhawk_unavailable"
    reader._apply_actuator_command()
    assert connection.mav.sent == []


def test_remote_control_rejection_reason_reports_non_manual_flightmode(
    monkeypatch,
) -> None:
    monkeypatch.setattr("asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.0)
    reader, connection = make_remote_ready_reader()
    reader._mode = "AUTO"
    reader.submit_remote_control(make_remote_command(), "session-a", 10.0)

    assert reader.remote_control_rejection_reason() == "flightmode_not_manual"
    reader._apply_actuator_command()
    assert connection.mav.sent == []


def test_remote_control_rejection_reason_reports_pilot_input(
    monkeypatch,
) -> None:
    monkeypatch.setattr("asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.0)
    reader, connection = make_remote_ready_reader()
    reader._last_pilot_input_monotonic = 9.0
    reader.submit_remote_control(make_remote_command(), "session-a", 10.0)

    assert reader.remote_control_rejection_reason() == "pilot_input_active"
    reader._apply_actuator_command()
    assert connection.mav.sent == []


def test_remote_disabled_command_blocks_model_until_cleared(
    monkeypatch,
) -> None:
    monkeypatch.setattr("asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.0)
    reader, connection = make_remote_ready_reader(model_actuators_enabled=True)
    reader.submit_actuator_command(
        ActuatorCommand(steering_pwm=1510, throttle_pwm=1540, enabled=True)
    )
    reader.submit_remote_control(
        make_remote_command(enabled=False),
        "session-a",
        10.0,
    )

    reader._apply_actuator_command()
    assert connection.mav.sent == []
    reader.clear_remote_control("session-a")
    reader._apply_actuator_command()
    assert connection.mav.sent[-1][2:5] == (1510, 65535, 1540)


def test_remote_submit_keeps_newest_received_command() -> None:
    reader, _ = make_remote_ready_reader()
    older = make_remote_command(seq=1)
    newer = make_remote_command(seq=2, steering_pwm=1520)

    reader.submit_remote_control(newer, "session-a", 11.0)
    reader.submit_remote_control(older, "session-a", 10.0)

    assert reader._remote_command == newer
    assert reader._remote_command_at == 11.0


def test_remote_submit_does_not_open_second_mavlink_connection(monkeypatch) -> None:
    monkeypatch.setattr("asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.0)
    reader, connection = make_remote_ready_reader()
    calls: list[tuple[object, ...]] = []

    def fail_if_connection_created(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("remote submit must reuse the reader connection")

    monkeypatch.setattr(
        "pymavlink.mavutil.mavlink_connection",
        fail_if_connection_created,
    )
    reader.submit_remote_control(make_remote_command(), "session-a", 10.0)
    reader._apply_actuator_command()

    assert calls == []
    assert connection.mav.sent


def priming_reader(
    now: float = 10.0,
    *,
    priming_seconds: float = 1.0,
) -> tuple[PixhawkTelemetryReader, FakeOverrideConnection]:
    reader = PixhawkTelemetryReader(
        BridgeSettings(
            pixhawk_enabled=True,
            remote_control_enabled=True,
            model_actuators_enabled=True,
            actuator_control_token="secret-token",
            throttle_neutral_priming_seconds=priming_seconds,
        )
    )
    connection = FakeOverrideConnection()
    reader._connection = connection
    reader._mode = "MANUAL"
    reader._last_heartbeat_monotonic = now
    reader._last_pilot_input_monotonic = now - 2.0
    return reader, connection


def test_remote_takeover_primes_neutral_before_throttle(monkeypatch) -> None:
    now = [10.0]
    monkeypatch.setattr(
        "asv_dashboard_backend.telemetry.time.monotonic", lambda: now[0]
    )
    reader, connection = priming_reader()
    reader.submit_remote_control(
        make_remote_command(steering_pwm=1600, throttle_pwm=1700),
        "session-a",
        now[0],
    )

    reader._apply_actuator_command()

    assert connection.mav.sent == [
        (7, 9, 1600, 65535, 1500, 65535, 65535, 65535, 65535, 65535)
    ]
    assert reader._throttle_priming_started_at == now[0]
    # The priming frame echoed by ArduPilot is not physical pilot input.
    reader._consume_message(
        FakeMavlinkMessage(
            "RC_CHANNELS", chan1_raw=1600, chan3_raw=1500, chancount=8
        ),
        now[0] + 0.1,
    )
    assert reader._last_pilot_input_monotonic == 8.0

    now[0] = 10.5
    reader._last_heartbeat_monotonic = now[0]
    reader.submit_remote_control(
        make_remote_command(seq=2, steering_pwm=1600, throttle_pwm=1700),
        "session-a",
        now[0],
    )
    reader._apply_actuator_command()
    assert connection.mav.sent[-1][2:5] == (1600, 65535, 1500)

    now[0] = 11.0
    reader._last_heartbeat_monotonic = now[0]
    reader.submit_remote_control(
        make_remote_command(seq=3, steering_pwm=1600, throttle_pwm=1700),
        "session-a",
        now[0],
    )
    reader._apply_actuator_command()
    assert connection.mav.sent[-1][2:5] == (1600, 65535, 1700)


def test_neutral_command_starts_priming_without_delay(monkeypatch) -> None:
    now = [10.0]
    monkeypatch.setattr(
        "asv_dashboard_backend.telemetry.time.monotonic", lambda: now[0]
    )
    reader, connection = priming_reader()
    reader.submit_remote_control(
        make_remote_command(steering_pwm=1600, throttle_pwm=1500),
        "session-a",
        now[0],
    )

    reader._apply_actuator_command()

    assert connection.mav.sent == [
        (7, 9, 1600, 65535, 1500, 65535, 65535, 65535, 65535, 65535)
    ]
    assert reader._throttle_priming_started_at == now[0]

    now[0] = 11.0
    reader._last_heartbeat_monotonic = now[0]
    reader.submit_remote_control(
        make_remote_command(seq=2, steering_pwm=1600, throttle_pwm=1700),
        "session-a",
        now[0],
    )
    reader._apply_actuator_command()
    assert connection.mav.sent[-1][2:5] == (1600, 65535, 1700)


def test_model_lane_uses_same_throttle_priming(monkeypatch) -> None:
    now = [10.0]
    monkeypatch.setattr(
        "asv_dashboard_backend.telemetry.time.monotonic", lambda: now[0]
    )
    reader, connection = priming_reader()
    reader.submit_actuator_command(
        ActuatorCommand(steering_pwm=1600, throttle_pwm=1700, enabled=True)
    )

    reader._apply_actuator_command()

    assert connection.mav.sent[-1][2:5] == (1600, 65535, 1500)
    reader._consume_message(
        FakeMavlinkMessage(
            "RC_CHANNELS", chan1_raw=1600, chan3_raw=1500, chancount=8
        ),
        now[0] + 0.1,
    )
    assert reader._last_pilot_input_monotonic == 8.0

    now[0] = 11.0
    reader._last_heartbeat_monotonic = now[0]
    reader._apply_actuator_command()
    assert connection.mav.sent[-1][2:5] == (1600, 65535, 1700)


def test_priming_disabled_sends_throttle_immediately(monkeypatch) -> None:
    monkeypatch.setattr("asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.0)
    reader, connection = priming_reader(priming_seconds=0.0)
    reader.submit_remote_control(
        make_remote_command(steering_pwm=1490, throttle_pwm=1700),
        "session-a",
        10.0,
    )

    reader._apply_actuator_command()

    assert connection.mav.sent == [
        (7, 9, 1490, 65535, 1700, 65535, 65535, 65535, 65535, 65535)
    ]
    assert reader._throttle_priming_started_at is None


def test_override_release_reprimes_on_next_takeover(monkeypatch) -> None:
    now = [10.0]
    monkeypatch.setattr(
        "asv_dashboard_backend.telemetry.time.monotonic", lambda: now[0]
    )
    reader, connection = priming_reader()
    reader.submit_remote_control(
        make_remote_command(steering_pwm=1490, throttle_pwm=1700),
        "session-a",
        now[0],
    )
    reader._apply_actuator_command()
    assert connection.mav.sent[-1][2:5] == (1490, 65535, 1500)

    now[0] = 11.0
    reader._last_heartbeat_monotonic = now[0]
    reader.submit_remote_control(
        make_remote_command(seq=2, steering_pwm=1490, throttle_pwm=1700),
        "session-a",
        now[0],
    )
    reader._apply_actuator_command()
    assert connection.mav.sent[-1][2:5] == (1490, 65535, 1700)

    now[0] = 12.0
    reader.clear_remote_control("session-a")
    assert connection.mav.sent[-1] == (7, 9, 0, 0, 0, 0, 0, 0, 0, 0)
    assert reader._throttle_priming_started_at is None

    reader._last_heartbeat_monotonic = now[0]
    reader.submit_remote_control(
        make_remote_command(seq=3, steering_pwm=1490, throttle_pwm=1700),
        "session-a",
        now[0],
    )
    reader._apply_actuator_command()
    assert connection.mav.sent[-1][2:5] == (1490, 65535, 1500)


def test_close_clears_remote_and_releases_override(monkeypatch) -> None:
    monkeypatch.setattr("asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.0)
    reader, connection = make_remote_ready_reader()
    reader.submit_remote_control(make_remote_command(), "session-a", 10.0)
    reader._apply_actuator_command()

    asyncio.run(reader.close())

    assert reader._remote_command is None
    assert reader._remote_session_id is None
    assert reader._remote_command_at == float("-inf")
    assert reader._connection is None
    assert connection.closed is True
    assert connection.mav.sent[-1] == (7, 9, 0, 0, 0, 0, 0, 0, 0, 0)


def test_reset_connection_clears_remote_releases_and_allows_reconnect(
    monkeypatch,
) -> None:
    monkeypatch.setattr("asv_dashboard_backend.telemetry.time.monotonic", lambda: 10.0)
    reader, connection = make_remote_ready_reader()
    reader.submit_remote_control(make_remote_command(), "session-a", 10.0)
    reader._apply_actuator_command()

    asyncio.run(reader._reset_connection(RuntimeError("broken")))

    assert reader._remote_command is None
    assert reader._remote_session_id is None
    assert reader._remote_command_at == float("-inf")
    assert reader._connection is None
    assert connection.closed is True
    assert connection.mav.sent[-1] == (7, 9, 0, 0, 0, 0, 0, 0, 0, 0)

    new_connection = FakeOverrideConnection()
    connection_attempts: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def connect(*args: object, **kwargs: object) -> FakeOverrideConnection:
        connection_attempts.append((args, kwargs))
        return new_connection

    monkeypatch.setattr("pymavlink.mavutil.mavlink_connection", connect)
    reader._request_telemetry_streams = lambda: None  # type: ignore[method-assign]
    reader._next_reconnect = 0.0
    asyncio.run(reader._connect_if_due())

    assert len(connection_attempts) == 1
    assert reader._connection is new_connection