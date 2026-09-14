"""Capture relay contract: remote POST -> dashboard capture listeners."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from asv_dashboard_backend.config import BridgeSettings
from asv_dashboard_backend.main import create_app


def capture_settings(**kwargs: object) -> BridgeSettings:
    return BridgeSettings(
        asv_id="default",
        cors_origins=(
            "https://dashboard.example.test",
            "https://remote.example.test",
        ),
        **kwargs,
    )


def post_capture(client: TestClient, origin: str = "https://remote.example.test"):
    return client.post(
        "/api/capture/request",
        headers={"origin": origin, "accept": "application/json"},
    )


def test_post_capture_request_reaches_dashboard_listener() -> None:
    app = create_app(settings=capture_settings())

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/capture/default",
            headers={"origin": "https://dashboard.example.test"},
        ) as dashboard:
            response = post_capture(client)

            assert response.status_code == 200
            assert response.json() == {"ok": True, "dashboards": 1}
            assert dashboard.receive_json() == {"type": "capture_request"}


def test_post_capture_request_reports_zero_without_dashboard() -> None:
    app = create_app(settings=capture_settings())

    with TestClient(app) as client:
        response = post_capture(client)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "dashboards": 0}


def test_post_capture_request_reaches_every_connected_dashboard() -> None:
    app = create_app(settings=capture_settings())

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/capture/default",
            headers={"origin": "https://dashboard.example.test"},
        ) as first, client.websocket_connect(
            "/ws/capture/default",
            headers={"origin": "https://dashboard.example.test"},
        ) as second:
            response = post_capture(client)

            assert response.status_code == 200
            assert response.json() == {"ok": True, "dashboards": 2}
            assert first.receive_json() == {"type": "capture_request"}
            assert second.receive_json() == {"type": "capture_request"}


def test_capture_websocket_rejects_wrong_asv_id() -> None:
    app = create_app(settings=capture_settings())

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws/capture/other-asv",
                headers={"origin": "https://dashboard.example.test"},
            ):
                pass


def test_capture_websocket_rejects_unapproved_origin() -> None:
    app = create_app(settings=capture_settings())

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws/capture/default",
                headers={"origin": "https://evil.example.test"},
            ):
                pass


def test_post_capture_request_rejects_unapproved_origin() -> None:
    app = create_app(settings=capture_settings())

    with TestClient(app) as client:
        response = post_capture(client, origin="https://evil.example.test")

    assert response.status_code == 403


def test_disconnected_dashboard_is_not_counted() -> None:
    app = create_app(settings=capture_settings())

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/capture/default",
            headers={"origin": "https://dashboard.example.test"},
        ):
            pass

        response = post_capture(client)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "dashboards": 0}


def test_malformed_dashboard_message_does_not_crash_or_leak_state() -> None:
    app = create_app(settings=capture_settings())

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/capture/default",
            headers={"origin": "https://dashboard.example.test"},
        ) as dashboard:
            dashboard.send_text("not json")

            response = post_capture(client)

            assert response.status_code == 200
            assert response.json() == {"ok": True, "dashboards": 1}
            assert dashboard.receive_json() == {"type": "capture_request"}
