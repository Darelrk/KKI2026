"""Validation and bounded encoding for the underwater Realtime fallback."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any


class FrameTooLargeError(ValueError):
    """Raised when a JPEG cannot fit the configured Realtime budget."""


def build_underwater_payload(
    jpeg_bytes: bytes,
    *,
    frame_id: str,
    captured_at: datetime | None = None,
    max_base64_length: int = 180_000,
) -> dict[str, str]:
    """Return a validated full-color JPEG payload within the Realtime budget."""
    if not frame_id.strip():
        raise ValueError("frame_id must not be empty")
    if max_base64_length < 4:
        raise ValueError("max_base64_length must be at least 4")

    normalized = _normalize_jpeg(jpeg_bytes)
    encoded = base64.b64encode(normalized).decode("ascii")
    if len(encoded) > max_base64_length:
        normalized = _reencode_until_bounded(normalized, max_base64_length)
        encoded = base64.b64encode(normalized).decode("ascii")

    if len(encoded) > max_base64_length:
        raise FrameTooLargeError(
            f"JPEG payload exceeds {max_base64_length} base64 characters"
        )

    timestamp = captured_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return {
        "mime": "image/jpeg",
        "data_base64": encoded,
        "captured_at": timestamp.isoformat(),
        "frame_id": frame_id,
    }


def _normalize_jpeg(jpeg_bytes: bytes) -> bytes:
    if not isinstance(jpeg_bytes, bytes):
        raise TypeError("jpeg_bytes must be bytes")
    if not jpeg_bytes.startswith(b"\xff\xd8"):
        raise ValueError("frame must be a JPEG")
    end = jpeg_bytes.rfind(b"\xff\xd9")
    if end < 2:
        raise ValueError("frame must be a complete JPEG")
    return jpeg_bytes[: end + 2]


def _reencode_until_bounded(jpeg_bytes: bytes, max_base64_length: int) -> bytes:
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise FrameTooLargeError(
            "OpenCV is required to recompress an oversized JPEG"
        ) from exc

    image = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("frame is not a decodable JPEG")

    for scale in (1.0, 0.75, 0.5, 0.33, 0.25, 0.2, 0.125):
        if scale == 1.0:
            candidate = image
        else:
            height, width = image.shape[:2]
            candidate = cv2.resize(
                image,
                (max(1, round(width * scale)), max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
        for quality in (85, 70, 55, 40, 30, 20, 10):
            ok, buffer = cv2.imencode(
                ".jpg",
                candidate,
                [cv2.IMWRITE_JPEG_QUALITY, quality],
            )
            if ok and len(base64.b64encode(buffer)) <= max_base64_length:
                return bytes(buffer)

    raise FrameTooLargeError(
        f"JPEG could not be reduced below {max_base64_length} base64 characters"
    )


def frame_size_bytes(payload: dict[str, Any]) -> int:
    """Return decoded payload size for logging and diagnostics."""
    return len(base64.b64decode(payload["data_base64"], validate=True))
