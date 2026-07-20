"""Read-only Pixhawk MAVLink telemetry for the ASV dashboard."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import BridgeSettings

logger = logging.getLogger(__name__)

TelemetryPublisher = Callable[[dict[str, Any]], Awaitable[None]]


class GpsPoint(BaseModel):
    """One bounded point in the current in-memory GPS track."""

    model_config = ConfigDict(extra="forbid")

    latitude: float
    longitude: float
    captured_at: datetime

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, value: float) -> float:
        if not math.isfinite(value) or not -90 <= value <= 90:
            raise ValueError("latitude must be between -90 and 90")
        return value

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, value: float) -> float:
        if not math.isfinite(value) or not -180 <= value <= 180:
            raise ValueError("longitude must be between -180 and 180")
        return value


class PixhawkTelemetry(BaseModel):
    """Small dashboard contract; no RC, mode, or autopilot command data."""

    model_config = ConfigDict(extra="forbid")

    connected: bool
    position: GpsPoint | None = None
    heading_deg: float | None = None
    speed_mps: float | None = None
    captured_at: datetime
    heartbeat_at: datetime | None = None
    track: list[GpsPoint] = Field(default_factory=list)


class PixhawkTelemetryReader:
    """Poll MAVLink messages without ever sending a MAVLink command."""

    _MESSAGE_TYPES = [
        "HEARTBEAT",
        "GLOBAL_POSITION_INT",
        "GPS_RAW_INT",
        "VFR_HUD",
    ]

    def __init__(self, settings: BridgeSettings) -> None:
        self.settings = settings
        self._connection: Any | None = None
        self._stop = False
        self._last_heartbeat_monotonic: float | None = None
        self._heartbeat_at: datetime | None = None
        self._position: GpsPoint | None = None
        self._heading_deg: float | None = None
        self._speed_mps: float | None = None
        self._track: list[GpsPoint] = []
        self._last_track_monotonic = float("-inf")
        self._last_position_key: tuple[float, float] | None = None
        self._next_reconnect = 0.0
        self._last_error: str | None = None

    def snapshot(self) -> PixhawkTelemetry:
        now = time.monotonic()
        connected = (
            self._last_heartbeat_monotonic is not None
            and now - self._last_heartbeat_monotonic
            <= self.settings.pixhawk_heartbeat_timeout
        )
        return PixhawkTelemetry(
            connected=connected,
            position=self._position,
            heading_deg=self._heading_deg,
            speed_mps=self._speed_mps,
            captured_at=datetime.now(timezone.utc),
            heartbeat_at=self._heartbeat_at,
            track=list(self._track),
        )

    async def run(self, publish: TelemetryPublisher) -> None:
        """Keep polling and publish one bounded snapshot per configured second."""
        interval = 1.0 / self.settings.pixhawk_update_hz
        next_publish = 0.0
        self._stop = False
        try:
            while not self._stop:
                if self._connection is None:
                    await self._connect_if_due()
                else:
                    try:
                        await asyncio.to_thread(self._drain_messages)
                    except Exception as exc:  # pragma: no cover - hardware-specific
                        self._record_connection_error(exc)

                now = time.monotonic()
                if now >= next_publish:
                    snapshot = self.snapshot()
                    try:
                        await publish(snapshot.model_dump(mode="json"))
                    except Exception:  # pragma: no cover - network-specific
                        logger.exception("Gagal publish telemetry Pixhawk")
                    next_publish = now + interval
                await asyncio.sleep(min(0.1, interval))
        except asyncio.CancelledError:
            raise
        finally:
            await self.close()

    async def close(self) -> None:
        self._stop = True
        connection = self._connection
        self._connection = None
        if connection is not None:
            try:
                await asyncio.to_thread(connection.close)
            except Exception:  # pragma: no cover - hardware-specific
                logger.debug("Gagal menutup koneksi Pixhawk", exc_info=True)

    async def _connect_if_due(self) -> None:
        now = time.monotonic()
        if now < self._next_reconnect:
            return
        self._next_reconnect = now + self.settings.pixhawk_reconnect_seconds
        try:
            from pymavlink import mavutil

            self._connection = await asyncio.to_thread(
                mavutil.mavlink_connection,
                self.settings.pixhawk_endpoint,
                baud=self.settings.pixhawk_baud,
                autoreconnect=True,
                source_system=255,
                source_component=190,
            )
            self._last_error = None
            logger.info("Pixhawk MAVLink reader connected to %s", self.settings.pixhawk_endpoint)
        except Exception as exc:  # pragma: no cover - hardware-specific
            self._connection = None
            self._record_connection_error(exc)

    def _drain_messages(self) -> None:
        if self._connection is None:
            return
        for _ in range(100):
            message = self._connection.recv_match(
                type=self._MESSAGE_TYPES,
                blocking=False,
            )
            if message is None:
                return
            self._consume_message(message, time.monotonic())

    def _consume_message(self, message: Any, now: float) -> None:
        message_type = message.get_type()
        if message_type == "HEARTBEAT":
            self._last_heartbeat_monotonic = now
            self._heartbeat_at = datetime.now(timezone.utc)
            return

        if message_type == "VFR_HUD":
            heading = _finite_number(getattr(message, "heading", None))
            if heading is not None:
                self._heading_deg = heading % 360.0
            speed = _finite_number(getattr(message, "groundspeed", None))
            if speed is not None and speed >= 0:
                self._speed_mps = speed
            return

        if message_type == "GLOBAL_POSITION_INT":
            latitude = _scaled_coordinate(getattr(message, "lat", None))
            longitude = _scaled_coordinate(getattr(message, "lon", None))
            if _valid_position(latitude, longitude):
                self._set_position(latitude, longitude, now)
            heading = _finite_number(getattr(message, "hdg", None))
            if heading is not None and heading != 65535:
                self._heading_deg = (heading / 100.0) % 360.0
            vx = _finite_number(getattr(message, "vx", None))
            vy = _finite_number(getattr(message, "vy", None))
            if vx is not None and vy is not None:
                self._speed_mps = math.hypot(vx, vy) / 100.0
            return

        if message_type == "GPS_RAW_INT":
            fix_type = int(getattr(message, "fix_type", 0) or 0)
            if fix_type < 2:
                return
            latitude = _scaled_coordinate(getattr(message, "lat", None))
            longitude = _scaled_coordinate(getattr(message, "lon", None))
            if _valid_position(latitude, longitude):
                self._set_position(latitude, longitude, now)

    def _set_position(self, latitude: float, longitude: float, now: float) -> None:
        captured_at = datetime.now(timezone.utc)
        point = GpsPoint(
            latitude=latitude,
            longitude=longitude,
            captured_at=captured_at,
        )
        self._position = point
        key = (latitude, longitude)
        if (
            key != self._last_position_key
            and now - self._last_track_monotonic
            >= 1.0 / self.settings.pixhawk_update_hz
        ):
            self._track.append(point)
            self._track = self._track[-self.settings.pixhawk_track_max_points :]
            self._last_track_monotonic = now
            self._last_position_key = key

    def _record_connection_error(self, exc: Exception) -> None:
        message = f"{type(exc).__name__}: {exc}"
        if message != self._last_error:
            logger.warning("Pixhawk belum tersedia (%s); retry otomatis", message)
            self._last_error = message


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _scaled_coordinate(value: Any) -> float | None:
    number = _finite_number(value)
    if number is None or abs(number) > 180 * 10_000_000:
        return None
    coordinate = number / 10_000_000.0
    return coordinate if math.isfinite(coordinate) else None


def _valid_position(latitude: float | None, longitude: float | None) -> bool:
    if latitude is None or longitude is None:
        return False
    return latitude != 0.0 or longitude != 0.0
