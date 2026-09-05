from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from asv_dashboard_backend.config import BridgeSettings, ConfigError
from asv_dashboard_backend.control import (
    ControlAck,
    ControlError,
    ControlSessionRegistry,
    RemoteControlCommand,
)
from asv_dashboard_backend.main import create_app
from asv_dashboard_backend.state import BridgeState


VALID = {
    "type": "control",
    "seq": 1,
    "client_sent_at_ms": 10,
    "steering_pwm": 1490,
    "throttle_pwm": 1550,
    "enabled": True,
}


class FakeRemoteReader:
    def __init__(self) -> None:
        self.commands: list[tuple[object, str, float]] = []
        self.clears: list[str | None] = []
        self.actuator_commands: list[object] = []
        self.rejection: str | None = None

    async def run(self, _publish) -> None:
        return

    async def close(self) -> None:
        return

    def snapshot(self):
        raise AssertionError("snapshot is not used by remote control tests")

    def submit_remote_control(
        self, command: object, session_id: str, received_at: float
    ) -> None:
        self.commands.append((command, session_id, received_at))

    def clear_remote_control(self, session_id: str | None = None) -> None:
        self.clears.append(session_id)

    def remote_control_rejection_reason(self) -> str | None:
        return self.rejection

    def submit_actuator_command(self, command: object) -> None:
        self.actuator_commands.append(command)
        raise AssertionError("remote control must not use actuator POST lane")


def remote_settings(**kwargs: object) -> BridgeSettings:
    return BridgeSettings(
        asv_id="default",
        cors_origins=("https://remote.example.test",),
        pixhawk_enabled=True,
        remote_control_enabled=True,
        **kwargs,
    )


def test_remote_settings_default_to_disabled_and_half_second_timeout() -> None:
    settings = BridgeSettings()

    assert settings.remote_control_enabled is False
    assert settings.remote_command_timeout == 0.5


def test_throttle_neutral_priming_parse_and_validate_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASV_THROTTLE_NEUTRAL_PRIMING_SECONDS", "1.0")
    assert BridgeSettings.from_env().throttle_neutral_priming_seconds == 1.0

    monkeypatch.setenv("ASV_THROTTLE_NEUTRAL_PRIMING_SECONDS", "-0.1")
    with pytest.raises(ConfigError, match="ASV_THROTTLE_NEUTRAL_PRIMING_SECONDS"):
        BridgeSettings.from_env()


def test_pilot_input_deadband_parse_and_validate_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASV_PILOT_INPUT_DEADBAND_PWM", "80")
    assert BridgeSettings.from_env().pilot_input_deadband_pwm == 80

    monkeypatch.setenv("ASV_PILOT_INPUT_DEADBAND_PWM", "251")
    with pytest.raises(ConfigError, match="ASV_PILOT_INPUT_DEADBAND_PWM"):
        BridgeSettings.from_env()


def test_remote_settings_parse_and_validate_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASV_PIXHAWK_ENABLED", "true")
    monkeypatch.setenv("ASV_REMOTE_CONTROL_ENABLED", "yes")
    monkeypatch.setenv("ASV_REMOTE_COMMAND_TIMEOUT", "0.25")

    settings = BridgeSettings.from_env()

    assert settings.remote_control_enabled is True
    assert settings.remote_command_timeout == 0.25

    monkeypatch.setenv("ASV_PIXHAWK_ENABLED", "false")
    with pytest.raises(ConfigError, match="remote control"):
        BridgeSettings.from_env()


def test_remote_settings_reject_non_positive_or_over_cap_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for value in ("0", "-0.1", "0.500001"):
        monkeypatch.setenv("ASV_REMOTE_COMMAND_TIMEOUT", value)
        with pytest.raises(ConfigError, match="ASV_REMOTE_COMMAND_TIMEOUT"):
            BridgeSettings.from_env()


def test_remote_command_schema_is_strict_and_bounded() -> None:
    command = RemoteControlCommand.model_validate(VALID)
    assert command.steering_pwm == 1490

    invalid = (
        {"steering_pwm": 999},
        {"throttle_pwm": 2001},
        {"steering_pwm": 1490.5},
        {"throttle_pwm": "1550"},
        {"seq": True},
        {"enabled": 1},
        {"client_sent_at_ms": -1},
        {"seq": 9_007_199_254_740_992},
        {"client_sent_at_ms": 9_007_199_254_740_992},
        {"extra": True},
        {"type": "wrong"},
    )
    for change in invalid:
        with pytest.raises(ValidationError):
            RemoteControlCommand.model_validate({**VALID, **change})

    with pytest.raises(ValidationError):
        RemoteControlCommand.model_validate({key: value for key, value in VALID.items() if key != "seq"})
    for non_object in (None, [], "control", 1, True):
        with pytest.raises(ValidationError):
            RemoteControlCommand.model_validate(non_object)


def test_remote_command_accepts_safe_integer_and_pwm_boundaries() -> None:
    command = RemoteControlCommand.model_validate(
        {
            **VALID,
            "seq": 9_007_199_254_740_991,
            "client_sent_at_ms": 9_007_199_254_740_991,
            "steering_pwm": 1000,
            "throttle_pwm": 2000,
        }
    )

    assert command.seq == 9_007_199_254_740_991
    assert command.steering_pwm == 1000
    assert command.throttle_pwm == 2000


def test_ack_reason_coherence_and_error_codes_are_strict() -> None:
    accepted = ControlAck.model_validate(
        {
            "type": "ack",
            "seq": 1,
            "accepted": True,
            "reason": None,
            "client_sent_at_ms": 10,
            "server_received_at_ms": 11,
        }
    )
    rejected = accepted.model_copy(
        update={"accepted": False, "reason": "stale_sequence"}
    )
    assert accepted.accepted is True
    assert rejected.accepted is False

    with pytest.raises(ValidationError):
        ControlAck.model_validate(
            {
                **accepted.model_dump(),
                "accepted": True,
                "reason": "stale_sequence",
            }
        )
    with pytest.raises(ValidationError):
        ControlAck.model_validate(
            {**rejected.model_dump(), "accepted": False, "reason": None}
        )
    with pytest.raises(ValidationError):
        ControlAck.model_validate({**accepted.model_dump(), "accepted": 1})

    for change in (
        {"seq": 0},
        {"client_sent_at_ms": -1},
        {"server_received_at_ms": 9_007_199_254_740_992},
        {"reason": "unknown"},
    ):
        with pytest.raises(ValidationError):
            ControlAck.model_validate({**accepted.model_dump(), **change})

    for code in ("invalid_json", "invalid_message", "origin_not_allowed"):
        assert ControlError.model_validate(
            {"type": "error", "code": code, "message": "internal"}
        ).code == code
    with pytest.raises(ValidationError):
        ControlError.model_validate(
            {"type": "error", "code": "secret", "message": "internal"}
        )
    with pytest.raises(ValidationError):
        ControlError.model_validate(
            {"type": "error", "code": "invalid_json", "message": "internal", "extra": 1}
        )


def test_registry_keeps_one_active_session_strict_sequence_and_owner_release() -> None:
    registry = ControlSessionRegistry()
    first, previous = registry.open("default", "first")
    assert first == "first"
    assert previous is None
    assert registry.validate_sequence(first, 1) is None
    assert registry.validate_sequence(first, 1) == "stale_sequence"

    second, previous = registry.open("default", "second")
    assert second == "second"
    assert previous == first
    assert registry.validate_sequence(first, 2) == "superseded"
    assert registry.validate_sequence(second, 1) is None
    assert registry.validate_sequence(second, 3) is None
    assert registry.validate_sequence(second, 2) == "stale_sequence"
    assert registry.validate_sequence(second, 3) == "stale_sequence"
    assert registry.is_owner("default", second)
    assert not registry.release("default", first)
    assert registry.is_owner("default", second)
    assert registry.release("default", second)
    assert not registry.is_owner("default", second)


def test_remote_websocket_valid_frame_gets_internal_ack_and_reader_command() -> None:
    reader = FakeRemoteReader()
    app = create_app(settings=remote_settings(), telemetry_reader=reader)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/control/default",
            headers={"origin": "https://remote.example.test"},
        ) as socket:
            socket.send_json(VALID)
            ack = socket.receive_json()

    assert ack["type"] == "ack"
    assert ack["seq"] == 1
    assert ack["accepted"] is True
    assert ack["reason"] is None
    assert ack["client_sent_at_ms"] == 10
    assert isinstance(ack["server_received_at_ms"], int)
    assert len(reader.commands) == 1
    assert reader.actuator_commands == []


def test_remote_websocket_malformed_json_gets_error_and_stays_alive() -> None:
    reader = FakeRemoteReader()
    app = create_app(settings=remote_settings(), telemetry_reader=reader)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/control/default",
            headers={"origin": "https://remote.example.test"},
        ) as socket:
            socket.send_text("{")
            error = socket.receive_json()
            socket.send_json(VALID)
            ack = socket.receive_json()

    assert error == {
        "type": "error",
        "code": "invalid_json",
        "message": "control frame must be valid JSON",
    }
    assert ack["accepted"] is True


def test_remote_websocket_non_object_json_gets_error_and_stays_alive() -> None:
    reader = FakeRemoteReader()
    app = create_app(settings=remote_settings(), telemetry_reader=reader)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/control/default",
            headers={"origin": "https://remote.example.test"},
        ) as socket:
            socket.send_text("[]")
            error = socket.receive_json()
            socket.send_json(VALID)
            ack = socket.receive_json()

    assert error == {
        "type": "error",
        "code": "invalid_message",
        "message": "control frame does not match the control schema",
    }
    assert ack["accepted"] is True


def test_remote_websocket_rejects_wrong_asv_origin_and_disabled_feature() -> None:
    cases = (
        (remote_settings(), "/ws/control/other", "https://remote.example.test"),
        (remote_settings(), "/ws/control/default", "https://other.example.test"),
        (replace(remote_settings(), remote_control_enabled=False), "/ws/control/default", "https://remote.example.test"),
        (remote_settings(), "/ws/control/default", ""),
    )

    for settings, path, origin in cases:
        app = create_app(settings=settings, telemetry_reader=FakeRemoteReader())
        with TestClient(app) as client:
            with pytest.raises(WebSocketDisconnect) as error:
                with client.websocket_connect(path, headers={"origin": origin}):
                    pass
        assert error.value.code == 1008



def test_remote_websocket_new_session_supersedes_old_with_4001() -> None:
    reader = FakeRemoteReader()
    app = create_app(settings=remote_settings(), telemetry_reader=reader)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/control/default",
            headers={"origin": "https://remote.example.test"},
        ) as first:
            first.send_json(VALID)
            first_ack = first.receive_json()
            assert first_ack["accepted"] is True
            assert len(reader.commands) == 1
            first_session_id = reader.commands[0][1]

            with client.websocket_connect(
                "/ws/control/default",
                headers={"origin": "https://remote.example.test"},
            ) as second:
                assert reader.clears == [first_session_id]

                second.send_json(VALID)
                second_ack = second.receive_json()
                assert second_ack["accepted"] is True
                assert len(reader.commands) == 2
                second_session_id = reader.commands[1][1]
                assert second_session_id != first_session_id

                with pytest.raises(WebSocketDisconnect) as error:
                    first.receive_text()
                assert error.value.code == 4001
                assert reader.clears == [first_session_id]
                assert len(reader.commands) == 2
                assert reader.commands[1][1] == second_session_id


def test_remote_websocket_enabled_false_clears_owner_and_stale_does_not_submit() -> None:
    reader = FakeRemoteReader()
    app = create_app(settings=remote_settings(), telemetry_reader=reader)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/control/default",
            headers={"origin": "https://remote.example.test"},
        ) as socket:
            socket.send_json(VALID)
            assert socket.receive_json()["accepted"] is True
            socket.send_json({**VALID, "seq": 1, "enabled": True})
            stale = socket.receive_json()
            socket.send_json({**VALID, "seq": 2, "enabled": False})
            released = socket.receive_json()

    assert stale["accepted"] is False
    assert stale["reason"] == "stale_sequence"
    assert released["accepted"] is True
    assert released["reason"] is None
    assert len(reader.commands) == 1
    assert reader.clears
    assert reader.actuator_commands == []
