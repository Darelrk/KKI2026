from __future__ import annotations

from datetime import datetime, timezone

from vision_route import Detection
from vision_test import (
    CapturedFrame,
    LatestFrameQueue,
    detection_metadata_from_result,
)


def test_latest_frame_queue_replaces_queued_frame() -> None:
    queue = LatestFrameQueue()
    captured_at = datetime.now(timezone.utc)
    queue.put_latest(CapturedFrame(frame=b"one", frame_id=1, captured_at=captured_at))
    queue.put_latest(CapturedFrame(frame=b"two", frame_id=2, captured_at=captured_at))

    latest = queue.get(timeout=0)

    assert latest is not None
    assert latest.frame_id == 2
    assert latest.frame == b"two"
    assert queue.get(timeout=0) is None


def test_detection_metadata_preserves_identity_and_normalizes_pixel_box() -> None:
    captured_at = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
    detection = Detection(
        label="buoy",
        confidence=0.9,
        x_center=640,
        y_center=360,
        width=256,
        height=144,
    )

    payload = detection_metadata_from_result(
        [detection],
        asv_id="default",
        frame_id=42,
        captured_at=captured_at,
        source_width=1280,
        source_height=720,
    )

    assert payload["frame_id"] == 42
    assert payload["captured_at"] == "2026-07-20T10:00:00+00:00"
    assert payload["detections"] == [
        {
            "track_id": None,
            "label": "buoy",
            "confidence": 0.9,
            "x": 0.4,
            "y": 0.4,
            "width": 0.2,
            "height": 0.2,
        }
    ]


def test_detection_metadata_does_not_clamp_invalid_model_output() -> None:
    detection = Detection(
        label="buoy",
        x_center=1500,
        confidence=0.9,
        y_center=360,
        width=256,
        height=144,
    )

    payload = detection_metadata_from_result(
        [detection],
        asv_id="default",
        frame_id=1,
        captured_at=datetime.now(timezone.utc),
        source_width=1280,
        source_height=720,
    )

    assert payload["detections"][0]["x"] > 1
