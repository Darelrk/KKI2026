from __future__ import annotations

from typing import Any

import pytest

from asv_dashboard_backend.vision_publisher import BridgeFramePublisher


def test_surface_publisher_applies_fps_limit_without_network() -> None:
    publisher = BridgeFramePublisher(
        "http://127.0.0.1:8080",
        asv_id="default",
        max_surface_fps=2.0,
    )
    calls: list[tuple[Any, ...]] = []
    publisher._submit = lambda *args, **kwargs: calls.append(args) or True  # type: ignore[method-assign]

    assert publisher.publish_surface_frame(b"jpeg", now=0.0) is True
    assert publisher.publish_surface_frame(b"jpeg", now=0.1) is False
    assert publisher.publish_surface_frame(b"jpeg", now=0.5) is True
    publisher.close()

    assert len(calls) == 2
    assert all(call[1] == "/api/frame/surface" for call in calls)


def test_publisher_rejects_invalid_bridge_url() -> None:
    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        BridgeFramePublisher("mqtt://boat", asv_id="default")


def valid_metadata() -> dict[str, object]:
    return {
        "schema_version": 1,
        "asv_id": "default",
        "frame_id": 7,
        "captured_at": "2026-07-20T10:00:00+00:00",
        "source_width": 1280,
        "source_height": 720,
        "detections": [],
    }


def test_detection_metadata_publisher_uses_independent_json_lane() -> None:
    publisher = BridgeFramePublisher("http://127.0.0.1:8080", asv_id="default")
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    publisher._submit = (  # type: ignore[method-assign]
        lambda *args, **kwargs: calls.append((args, kwargs)) or True
    )

    assert publisher.publish_detection_metadata(valid_metadata()) is True
    assert publisher.publish_surface_frame(b"\xff\xd8raw\xff\xd9", now=0) is True
    publisher.close()

    metadata_args, metadata_kwargs = calls[0]
    assert metadata_args[:2] == ("POST", "/api/vision/metadata")
    assert metadata_args[3] == "application/json"
    assert metadata_kwargs["lane"] == "metadata"
    assert metadata_args[2].decode() == '{"schema_version":1,"asv_id":"default","frame_id":7,"captured_at":"2026-07-20T10:00:00+00:00","source_width":1280,"source_height":720,"detections":[]}'
    surface_args, surface_kwargs = calls[1]
    assert surface_args[:2] == ("POST", "/api/frame/surface")
    assert surface_kwargs["lane"] == "surface"
