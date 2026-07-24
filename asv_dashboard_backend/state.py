"""Bounded in-memory state shared by the local bridge endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import BridgeSettings


class AsvLiveStatus(BaseModel):
    """Status row mirrored to the dashboard's ``asv_live`` table."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    online: bool
    model_status: Literal["offline", "starting", "running", "error"]
    camera: Literal["surface", "underwater"]
    stream_url: str | None = None
    run_id: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("stream_url")
    @classmethod
    def validate_stream_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("stream_url must be an absolute HTTPS URL")
        return value

    @field_validator("run_id")
    @classmethod
    def normalize_run_id(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None



class VisionDetectionBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: int | None = None
    label: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def fit_inside_source(self) -> "VisionDetectionBox":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("detection box must fit inside source frame")
        return self


class VisionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    asv_id: str = Field(min_length=1)
    frame_id: int = Field(ge=0)
    captured_at: datetime
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    detections: list[VisionDetectionBox]

    @field_validator("captured_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        return value

class BridgeState:
    """Store latest status, surface JPEG, and vision metadata only."""

    def __init__(self, settings: BridgeSettings) -> None:
        self.settings = settings
        self.status = AsvLiveStatus(
            id=settings.asv_id,
            online=False,
            model_status="offline",
            camera="surface",
            stream_url=settings.stream_url,
            run_id=None,
        )
        self._surface_frame: bytes | None = None
        self._surface_frame_version = 0
        self._frame_event = asyncio.Event()
        self._latest_detection: VisionMetadata | None = None
        self._detection_subscribers: set[asyncio.Queue[VisionMetadata]] = set()
        self._latest_telemetry: dict[str, Any] | None = None
        self._telemetry_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def update_status(self, status: AsvLiveStatus) -> AsvLiveStatus:
        if status.id != self.settings.asv_id:
            raise ValueError(f"status id must be {self.settings.asv_id}")
        self.status = status
        return status

    def publish_detection(self, metadata: VisionMetadata) -> None:
        if metadata.asv_id != self.settings.asv_id:
            raise ValueError(f"metadata asv_id must be {self.settings.asv_id}")
        self._latest_detection = metadata
        for queue in tuple(self._detection_subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(metadata)

    def subscribe_detections(self) -> asyncio.Queue[VisionMetadata]:
        queue: asyncio.Queue[VisionMetadata] = asyncio.Queue(maxsize=1)
        self._detection_subscribers.add(queue)
        if self._latest_detection is not None:
            queue.put_nowait(self._latest_detection)
        return queue

    def unsubscribe_detections(self, queue: asyncio.Queue[VisionMetadata]) -> None:
        self._detection_subscribers.discard(queue)

    def publish_telemetry(self, payload: dict[str, Any]) -> None:
        self._latest_telemetry = payload
        for queue in tuple(self._telemetry_subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(payload)

    def subscribe_telemetry(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        self._telemetry_subscribers.add(queue)
        if self._latest_telemetry is not None:
            queue.put_nowait(self._latest_telemetry)
        return queue

    def unsubscribe_telemetry(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._telemetry_subscribers.discard(queue)

    def update_surface_frame(self, jpeg_bytes: bytes) -> None:
        if not jpeg_bytes.startswith(b"\xff\xd8") or b"\xff\xd9" not in jpeg_bytes:
            raise ValueError("surface frame must be a complete JPEG")
        self._surface_frame = jpeg_bytes[: jpeg_bytes.rfind(b"\xff\xd9") + 2]
        self._surface_frame_version += 1
        self._frame_event.set()

    def latest_surface_frame(self) -> bytes | None:
        return self._surface_frame

    async def mjpeg_stream(self, *, once: bool = False) -> AsyncIterator[bytes]:
        """Yield a browser-compatible MJPEG stream without buffering history."""
        last_version = -1
        while True:
            if self._surface_frame_version == last_version:
                try:
                    await asyncio.wait_for(
                        self._frame_event.wait(),
                        timeout=self.settings.frame_wait_timeout,
                    )
                except asyncio.TimeoutError:
                    if once:
                        return
                self._frame_event.clear()

            if self._surface_frame is not None:
                if self._surface_frame_version != last_version or not once:
                    last_version = self._surface_frame_version
                    frame = self._surface_frame
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
                        + frame
                        + b"\r\n"
                    )
                    if once:
                        return

            await asyncio.sleep(0.01)
