from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from asv_dashboard_backend.config import BridgeSettings
from asv_dashboard_backend.frames import FrameTooLargeError, build_underwater_payload
from asv_dashboard_backend.main import create_app
from asv_dashboard_backend.state import (
    BridgeState,
    ControlModePayload,
    VisionMetadata,
)
from asv_dashboard_backend.telemetry import PixhawkTelemetryReader

SMALL_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCAAJABADASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAABf/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AJpAIAn/2Q=="
)


def settings() -> BridgeSettings:
    return BridgeSettings(
        asv_id="default",
        stream_url="https://camera.example.test/stream.mjpg",
        cors_origins=("https://dashboard.example.test",),
        max_base64_length=180_000,
        max_fps=1.0,
    )


def test_control_mode_defaults_to_manual_and_setter_transitions_both_directions() -> None:
    state = BridgeState(settings())

    assert state.control_mode == "MANUAL"
    assert state.set_control_mode("AUTONOMOUS") == "AUTONOMOUS"
    assert state.control_mode == "AUTONOMOUS"
    assert state.set_control_mode("MANUAL") == "MANUAL"
    assert state.control_mode == "MANUAL"


def test_control_mode_setter_rejects_lowercase_mode() -> None:
    with pytest.raises(ValidationError):
        BridgeState(settings()).set_control_mode("manual")


def test_control_mode_payload_rejects_invalid_case_and_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ControlModePayload.model_validate({"mode": "manual"})

    with pytest.raises(ValidationError):
        ControlModePayload.model_validate({"mode": "MANUAL", "extra": True})

def test_control_mode_http_defaults_manual_and_changes_without_restarting_app() -> None:
    app = create_app(settings=settings())

    with TestClient(app) as client:
        initial = client.get("/api/control/mode")
        autonomous = client.put(
            "/api/control/mode",
            json={"mode": "AUTONOMOUS"},
        )
        after_autonomous = client.get("/api/control/mode")
        manual = client.put(
            "/api/control/mode",
            json={"mode": "MANUAL"},
        )
        after_manual = client.get("/api/control/mode")

    assert initial.status_code == 200
    assert initial.json() == {"mode": "MANUAL"}
    assert autonomous.status_code == 200
    assert autonomous.json() == {"mode": "AUTONOMOUS"}
    assert after_autonomous.status_code == 200
    assert after_autonomous.json() == {"mode": "AUTONOMOUS"}
    assert manual.status_code == 200
    assert manual.json() == {"mode": "MANUAL"}
    assert after_manual.status_code == 200
    assert after_manual.json() == {"mode": "MANUAL"}


def test_control_mode_http_rejects_invalid_payload() -> None:
    app = create_app(settings=settings())

    with TestClient(app) as client:
        response = client.put(
            "/api/control/mode",
            json={"mode": "manual"},
        )

    assert response.status_code == 422


def test_control_mode_preflight_allows_configured_dashboard_origin() -> None:
    app = create_app(settings=settings())

    with TestClient(app) as client:
        response = client.options(
            "/api/control/mode",
            headers={
                "Origin": "https://dashboard.example.test",
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "https://dashboard.example.test"
    )
    assert "PUT" in response.headers["access-control-allow-methods"]


class CapturingTelemetryReader:
    def __init__(self) -> None:
        self.commands = []
        self.clears = []
    async def run(self, _publish) -> None:
        return

    async def close(self) -> None:
        return

    def snapshot(self):
        raise AssertionError("snapshot is not used by actuator route tests")

    def submit_actuator_command(self, command) -> None:
        self.commands.append(command)
    def clear_remote_control(self, session_id=None) -> None:
        self.clears.append(session_id)


def test_autonomous_mode_change_clears_remote_reader() -> None:
    reader = CapturingTelemetryReader()
    app = create_app(settings=settings(), telemetry_reader=reader)

    with TestClient(app) as client:
        response = client.put(
            "/api/control/mode",
            json={"mode": "AUTONOMOUS"},
        )
        repeated_response = client.put(
            "/api/control/mode",
            json={"mode": "AUTONOMOUS"},
        )

    assert response.status_code == 200
    assert response.json() == {"mode": "AUTONOMOUS"}
    assert repeated_response.status_code == 200
    assert repeated_response.json() == {"mode": "AUTONOMOUS"}
    assert reader.clears == [None, None]


def actuator_settings() -> BridgeSettings:
    return BridgeSettings(
        pixhawk_enabled=True,
        model_actuators_enabled=True,
        actuator_control_token="secret-token",
    )


def test_cors_origins_parse_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ASV_CORS_ORIGINS",
        " https://dashboard.example.test, http://localhost:3000 ",
    )

    assert BridgeSettings.from_env().cors_origins == (
        "https://dashboard.example.test",
        "http://localhost:3000",
    )


def test_build_underwater_payload_accepts_valid_jpeg_and_metadata() -> None:
    payload = build_underwater_payload(
        SMALL_JPEG,
        frame_id="frame-001",
        captured_at=datetime(2026, 7, 20, 9, 30, tzinfo=timezone.utc),
        max_base64_length=180_000,
    )

    assert payload["mime"] == "image/jpeg"
    assert payload["frame_id"] == "frame-001"
    assert payload["captured_at"] == "2026-07-20T09:30:00+00:00"
    assert payload["data_base64"].startswith("/9j/")
    assert len(payload["data_base64"]) <= 180_000


def test_build_underwater_payload_reencodes_oversized_jpeg() -> None:
    oversized = SMALL_JPEG + (b"x" * 240_000)

    payload = build_underwater_payload(
        oversized,
        frame_id="frame-002",
        captured_at=datetime.now(timezone.utc),
        max_base64_length=500,
    )

    assert len(payload["data_base64"]) <= 500
    assert base64.b64decode(payload["data_base64"]).startswith(b"\xff\xd8")


def test_build_underwater_payload_rejects_non_jpeg() -> None:
    with pytest.raises(ValueError, match="JPEG"):
        build_underwater_payload(
            b"not-a-jpeg",
            frame_id="frame-003",
            captured_at=datetime.now(timezone.utc),
            max_base64_length=180_000,
        )


def test_status_and_frame_endpoints_keep_local_state() -> None:
    app = create_app(settings=settings())

    with TestClient(app) as client:
        health = client.get("/healthz")
        status = client.put(
            "/api/status",
            json={
                "id": "default",
                "online": True,
                "model_status": "running",
                "camera": "surface",
                "stream_url": "https://camera.example.test/stream.mjpg",
                "run_id": "run-001",
            },
        )
        frame = client.post(
            "/api/frame/underwater",
            content=SMALL_JPEG,
            headers={"content-type": "image/jpeg", "x-frame-id": "frame-004"},
        )
        current = client.get("/api/status")

    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert status.status_code == 200
    assert frame.status_code == 200
    assert frame.json()["frame_id"] == "frame-004"
    assert current.json()["run_id"] == "run-001"


def test_actuator_endpoint_requires_token_and_queues_command() -> None:
    reader = CapturingTelemetryReader()
    app = create_app(settings=actuator_settings(), telemetry_reader=reader)

    with TestClient(app) as client:
        assert client.post(
            "/api/control/actuator",
            json={"steering_pwm": 1500, "throttle_pwm": 1560, "enabled": True},
        ).status_code == 403
        assert client.post(
            "/api/control/actuator",
            headers={"x-asv-control-token": "wrong"},
            json={"steering_pwm": 1500, "throttle_pwm": 1560, "enabled": True},
        ).status_code == 403
        accepted = client.post(
            "/api/control/actuator",
            headers={"x-asv-control-token": "secret-token"},
            json={"steering_pwm": 1490, "throttle_pwm": 1540, "enabled": True},
        )

    assert accepted.status_code == 200
    assert len(reader.commands) == 1
    assert reader.commands[0].steering_pwm == 1490
    assert reader.commands[0].throttle_pwm == 1540

def test_control_websocket_delegates_to_real_pixhawk_reader(
    monkeypatch,
    caplog,
) -> None:
    class FakeMav:
        def __init__(self) -> None:
            self.sent: list[tuple[object, ...]] = []

        def rc_channels_override_send(self, *values: object) -> None:
            self.sent.append(values)

    class FakeConnection:
        target_system = 7
        target_component = 9
        flightmode = "MANUAL"

        def __init__(self) -> None:
            self.mav = FakeMav()
            self.closed = False

        def recv_match(self, **_kwargs: object) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    settings_with_remote = BridgeSettings(
        asv_id="default",
        cors_origins=("https://dashboard.example.test",),
        pixhawk_enabled=True,
        pixhawk_heartbeat_timeout=30.0,
        remote_control_enabled=True,
    )
    reader = PixhawkTelemetryReader(settings_with_remote)
    connection = FakeConnection()
    reader._connection = connection
    reader._mode = "MANUAL"
    now = time.monotonic()
    reader._last_heartbeat_monotonic = now
    reader._last_pilot_input_monotonic = now - 2.0

    connection_attempts: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fail_if_connection_created(
        *args: object, **kwargs: object
    ) -> None:
        connection_attempts.append((args, kwargs))
        raise AssertionError("WebSocket must reuse the reader's Pixhawk link")

    monkeypatch.setattr(
        "pymavlink.mavutil.mavlink_connection",
        fail_if_connection_created,
    )
    app = create_app(settings=settings_with_remote, telemetry_reader=reader)

    with caplog.at_level(
        logging.INFO,
        logger="asv_dashboard_backend.main",
    ):
        with TestClient(app) as client:
            with client.websocket_connect(
                "/ws/control/default",
                headers={"origin": "https://dashboard.example.test"},
            ) as socket:
                socket.send_json(
                    {
                        "type": "control",
                        "seq": 1,
                        "client_sent_at_ms": 100,
                        "steering_pwm": 1475,
                        "throttle_pwm": 1585,
                        "enabled": True,
                    }
                )
                ack = socket.receive_json()
                reader._apply_actuator_command()

                assert ack["type"] == "ack"
                assert ack["accepted"] is True
                assert ack["reason"] is None
                assert connection.mav.sent[-1] == (
                    7,
                    9,
                    1475,
                    65535,
                    1585,
                    65535,
                    65535,
                    65535,
                    65535,
                    65535,
                )

    assert any(
        "Remote input" in record.message
        and "RC1=1475" in record.message
        and "RC3=1585" in record.message
        and "accepted=True" in record.message
        for record in caplog.records
    )

    assert connection_attempts == []


def test_read_endpoints_allow_configured_dashboard_origin() -> None:
    app = create_app(settings=settings())

    with TestClient(app) as client:
        response = client.options(
            "/api/status",
            headers={
                "Origin": "https://dashboard.example.test",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "https://dashboard.example.test"
    )


def test_status_endpoint_rejects_wrong_asv_id() -> None:
    app = create_app(settings=settings())

    with TestClient(app) as client:
        response = client.put(
            "/api/status",
            json={
                "id": "other",
                "online": True,
                "model_status": "running",
                "camera": "surface",
                "stream_url": None,
                "run_id": "run-001",
            },
        )

    assert response.status_code == 409


def test_mjpeg_stream_has_http_multipart_shape() -> None:
    state = BridgeState(settings())
    state.update_surface_frame(SMALL_JPEG)
    app = create_app(settings=settings(), state=state)

    with TestClient(app) as client:
        response = client.get("/stream.mjpg?once=true")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("multipart/x-mixed-replace")
    assert b"Content-Type: image/jpeg" in response.content
    assert response.content.endswith(SMALL_JPEG + b"\r\n")


def vision_payload(frame_id: int = 1) -> dict[str, object]:
    return {
        "schema_version": 1,
        "asv_id": "default",
        "frame_id": frame_id,
        "captured_at": "2026-07-20T10:00:00+00:00",
        "source_width": 1280,
        "source_height": 720,
        "detections": [
            {
                "track_id": None,
                "label": "buoy",
                "confidence": 0.9,
                "x": 0.1,
                "y": 0.1,
                "width": 0.2,
                "height": 0.2,
            }
        ],
    }


def test_vision_metadata_rejects_invalid_schema_and_out_of_bounds_box() -> None:
    app = create_app(settings=settings())
    payload = vision_payload()
    payload["schema_version"] = 2
    payload["detections"][0]["x"] = 0.9
    payload["detections"][0]["width"] = 0.2

    with TestClient(app) as client:
        response = client.post("/api/vision/metadata", json=payload)

    assert response.status_code == 422


def test_vision_metadata_post_broadcasts_to_websocket() -> None:
    app = create_app(settings=settings())
    expected = VisionMetadata.model_validate(vision_payload()).model_dump(mode="json")

    with TestClient(app) as client:
        with client.websocket_connect("/ws/vision/default") as socket:
            response = client.post("/api/vision/metadata", json=vision_payload())
            assert response.status_code == 200
            assert socket.receive_json() == expected


def test_vision_state_keeps_only_newest_payload() -> None:
    state = BridgeState(settings())
    queue = state.subscribe_detections()
    state.publish_detection(VisionMetadata.model_validate(vision_payload(frame_id=1)))
    state.publish_detection(VisionMetadata.model_validate(vision_payload(frame_id=2)))

    assert queue.get_nowait().frame_id == 2
    state.unsubscribe_detections(queue)


def test_vision_metadata_rejects_wrong_asv_id() -> None:
    app = create_app(settings=settings())
    payload = vision_payload()
    payload["asv_id"] = "other"

    with TestClient(app) as client:
        response = client.post("/api/vision/metadata", json=payload)

    assert response.status_code == 409


def test_vision_websocket_rejects_wrong_asv_id() -> None:
    app = create_app(settings=settings())

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/ws/vision/other"):
                pass

    assert getattr(error.value, "code", None) == 1008

def test_telemetry_broadcasts_to_websocket() -> None:
    state = BridgeState(settings())
    app = create_app(settings=settings(), state=state)
    payload = {
        "connected": True,
        "position": {"latitude": 3.5, "longitude": 98.7, "captured_at": "2026-07-25T00:00:00Z"},
        "heading_deg": 90.0,
        "speed_mps": 1.5,
        "captured_at": "2026-07-25T00:00:00Z",
        "heartbeat_at": "2026-07-25T00:00:00Z",
        "track": [],
    }

    with TestClient(app) as client:
        with client.websocket_connect("/ws/telemetry/default") as socket:
            state.publish_telemetry(payload)
            assert socket.receive_json() == payload


def test_telemetry_websocket_rejects_wrong_asv_id() -> None:
    app = create_app(settings=settings())

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/ws/telemetry/other"):
                pass

    assert getattr(error.value, "code", None) == 1008

