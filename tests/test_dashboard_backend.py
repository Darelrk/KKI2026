from __future__ import annotations

import base64
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from asv_dashboard_backend.config import BridgeSettings
from asv_dashboard_backend.frames import FrameTooLargeError, build_underwater_payload
from asv_dashboard_backend.main import create_app
from asv_dashboard_backend.publisher import NullPublisher
from asv_dashboard_backend.state import BridgeState

SMALL_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCAAJABADASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAABf/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AJpAIAn/2Q=="
)


def settings() -> BridgeSettings:
    return BridgeSettings(
        asv_id="default",
        stream_url="https://camera.example.test/stream.mjpg",
        max_base64_length=180_000,
        max_fps=1.0,
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


def test_status_and_frame_endpoints_publish_bounded_payload() -> None:
    publisher = NullPublisher()
    publisher.publish_status = AsyncMock()  # type: ignore[method-assign]
    publisher.publish_underwater_frame = AsyncMock()  # type: ignore[method-assign]
    app = create_app(settings=settings(), publisher=publisher)

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
    publisher.publish_status.assert_awaited_once()
    publisher.publish_underwater_frame.assert_awaited_once()


def test_status_endpoint_rejects_wrong_asv_id() -> None:
    app = create_app(settings=settings(), publisher=NullPublisher())

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
    app = create_app(settings=settings(), publisher=NullPublisher(), state=state)

    with TestClient(app) as client:
        response = client.get("/stream.mjpg?once=true")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("multipart/x-mixed-replace")
    assert b"Content-Type: image/jpeg" in response.content
    assert response.content.endswith(SMALL_JPEG + b"\r\n")


class FakeSupabaseQuery:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def upsert(self, row: dict[str, object]) -> FakeSupabaseQuery:
        self.rows.append(row)
        return self

    def execute(self) -> None:
        return None


class FakeSupabaseChannel:
    def __init__(self) -> None:
        self.subscriptions = 0
        self.broadcasts: list[tuple[str, dict[str, object]]] = []

    def subscribe(self) -> None:
        self.subscriptions += 1

    def send_broadcast(self, event: str, payload: dict[str, object]) -> None:
        self.broadcasts.append((event, payload))


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.query = FakeSupabaseQuery()
        self.channel_instance = FakeSupabaseChannel()
        self.channel_args: tuple[object, ...] | None = None

    def table(self, name: str) -> FakeSupabaseQuery:
        assert name == "asv_live"
        return self.query

    def channel(self, *args: object) -> FakeSupabaseChannel:
        self.channel_args = args
        return self.channel_instance

    def remove_all_channels(self) -> None:
        return None


def test_supabase_publisher_targets_status_table_and_private_channel() -> None:
    import asyncio

    from asv_dashboard_backend.publisher import SupabasePublisher

    client = FakeSupabaseClient()
    publisher = SupabasePublisher(client, "default")
    payload = {"mime": "image/jpeg", "data_base64": "/9j/", "frame_id": "f-1"}

    async def exercise() -> None:
        await publisher.publish_status({"id": "default", "online": True})
        await publisher.publish_underwater_frame(payload)
        await publisher.publish_underwater_frame(payload)

    asyncio.run(exercise())

    assert client.query.rows == [{"id": "default", "online": True}]
    assert client.channel_args == (
        "asv-camera:default",
        {"config": {"private": True}},
    )
    assert client.channel_instance.subscriptions == 1
    assert client.channel_instance.broadcasts == [
        ("underwater_frame", payload),
        ("underwater_frame", payload),
    ]
