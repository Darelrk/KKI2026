"""Bounded in-memory state shared by the local bridge endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class BridgeState:
    """Store only latest status and latest surface JPEG bytes."""

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

    def update_status(self, status: AsvLiveStatus) -> AsvLiveStatus:
        if status.id != self.settings.asv_id:
            raise ValueError(f"status id must be {self.settings.asv_id}")
        self.status = status
        return status

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
            if self._surface_frame is None:
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
                frame = self._surface_frame
                if self._surface_frame_version != last_version or not once:
                    last_version = self._surface_frame_version
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
                        + frame
                        + b"\r\n"
                    )
                    if once:
                        return

            await asyncio.sleep(1.0 / self.settings.max_fps)
