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
