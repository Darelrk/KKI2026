"""Read-only Pixhawk MAVLink telemetry for the ASV dashboard."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import BridgeSettings
from .control import RemoteControlCommand

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
    """Small dashboard contract; no RC, mode, or autopilot control data."""

    model_config = ConfigDict(extra="forbid")

    connected: bool
    position: GpsPoint | None = None
    heading_deg: float | None = None
    speed_mps: float | None = None
    captured_at: datetime
    heartbeat_at: datetime | None = None
    track: list[GpsPoint] = Field(default_factory=list)


class ActuatorCommand(BaseModel):
    """Validated model command accepted by the unified Pixhawk worker."""

    model_config = ConfigDict(extra="forbid")

    steering_pwm: int = Field(ge=1000, le=2000)
    throttle_pwm: int = Field(ge=1000, le=2000)
    enabled: bool = True


class PixhawkTelemetryReader:
    """Own the single Pixhawk link for telemetry and guarded RC override."""

    _MESSAGE_TYPES = [
        "HEARTBEAT",
        "GLOBAL_POSITION_INT",
        "GPS_RAW_INT",
        "VFR_HUD",
        "RC_CHANNELS",
    ]

    def __init__(self, settings: BridgeSettings) -> None:
        self.settings = settings
        self._connection: Any | None = None
        self._mavlink_api: Any | None = None
        self._connection_started_monotonic: float | None = None
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
        self._last_stream_target: tuple[int, int] | None = None
        self._last_rc_monotonic: float | None = None
        self._mode = "UNKNOWN"
        self._last_pilot_input_monotonic: float | None = None
        self._actuator_lock = Lock()
        self._actuator_command: ActuatorCommand | None = None
        self._actuator_command_at = float("-inf")
        self._remote_command: RemoteControlCommand | None = None
        self._remote_session_id: str | None = None
        self._remote_command_at = float("-inf")
        self._override_active = False

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
            # Heading dan speed terakhir tetap terlihat seperti gerakan live di
            # dashboard, jadi laporkan sebagai tidak diketahui selama link mati.
            heading_deg=self._heading_deg if connected else None,
            speed_mps=self._speed_mps if connected else None,
            captured_at=datetime.now(timezone.utc),
            heartbeat_at=self._heartbeat_at,
            track=list(self._track),
        )

    def submit_actuator_command(self, command: ActuatorCommand) -> None:
        """Store the newest short-lived model command for the control loop."""
        with self._actuator_lock:
            self._actuator_command = command
            self._actuator_command_at = time.monotonic()

    def submit_remote_control(
        self,
        command: RemoteControlCommand,
        session_id: str,
        received_at: float,
    ) -> None:
        """Store the newest short-lived remote command for the control loop."""
        with self._actuator_lock:
            if received_at >= self._remote_command_at:
                self._remote_command = command
                self._remote_session_id = session_id
                self._remote_command_at = received_at

    def clear_remote_control(self, session_id: str | None = None) -> bool:
        """Clear the remote command only when the caller owns its session."""
        with self._actuator_lock:
            if (
                session_id is not None
                and self._remote_session_id != session_id
            ):
                return False
            existed = self._remote_command is not None
            should_release = existed or self._override_active
            self._remote_command = None
            self._remote_session_id = None
            self._remote_command_at = float("-inf")
        if should_release:
            self._release_actuator_override()
        return existed

    def remote_control_rejection_reason(self) -> str | None:
        """Return the first reader-level safety gate blocking remote control."""
        if not self.settings.remote_control_enabled:
            return "remote_control_disabled"
        if self._connection is None:
            return "pixhawk_unavailable"
        now = time.monotonic()
        heartbeat_age = (
            float("inf")
            if self._last_heartbeat_monotonic is None
            else now - self._last_heartbeat_monotonic
        )
        if heartbeat_age > self.settings.pixhawk_heartbeat_timeout:
            return "pixhawk_unavailable"
        if self._mode != "MANUAL":
            return "flightmode_not_manual"
        pilot_input_age = (
            float("inf")
            if self._last_pilot_input_monotonic is None
            else now - self._last_pilot_input_monotonic
        )
        if pilot_input_age <= 1.5:
            return "pilot_input_active"
        return None

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
                    except OSError as exc:
                        await self._reset_connection(exc)
                    except Exception as exc:  # pragma: no cover - hardware-specific
                        await self._reset_connection(exc)

                    if self._connection is not None:
                        heartbeat_reference = (
                            self._last_heartbeat_monotonic
                            or self._connection_started_monotonic
                        )
                        if (
                            heartbeat_reference is not None
                            and time.monotonic() - heartbeat_reference
                            > self.settings.pixhawk_heartbeat_timeout
                        ):
                            await self._reset_connection(
                                TimeoutError("heartbeat Pixhawk tidak diterima")
                            )
                        self._apply_actuator_command()

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


    def _apply_actuator_command(self) -> None:
        """Send only fresh MANUAL-mode overrides; otherwise release them."""
        with self._actuator_lock:
            connection = self._connection
            if connection is None:
                self._release_actuator_override_locked()
                return

            now = time.monotonic()
            remote_command = self._remote_command
            if remote_command is not None:
                command = remote_command
                command_age = now - self._remote_command_at
                command_timeout = self.settings.remote_command_timeout
                lane_enabled = self.settings.remote_control_enabled
            else:
                command = self._actuator_command
                command_age = now - self._actuator_command_at
                command_timeout = self.settings.actuator_command_timeout
                lane_enabled = self.settings.model_actuators_enabled

            heartbeat_age = (
                float("inf")
                if self._last_heartbeat_monotonic is None
                else now - self._last_heartbeat_monotonic
            )
            pilot_input_age = (
                float("inf")
                if self._last_pilot_input_monotonic is None
                else now - self._last_pilot_input_monotonic
            )
            if (
                not lane_enabled
                or command is None
                or not command.enabled
                or command_age >= command_timeout
                or heartbeat_age > self.settings.pixhawk_heartbeat_timeout
                or self._mode != "MANUAL"
                or pilot_input_age <= 1.5
            ):
                self._release_actuator_override_locked()
                return

            steering_pwm = getattr(command, "steering_pwm", None)
            throttle_pwm = getattr(command, "throttle_pwm", None)
            if (
                type(steering_pwm) is not int
                or type(throttle_pwm) is not int
                or not 1000 <= steering_pwm <= 2000
                or not 1000 <= throttle_pwm <= 2000
            ):
                self._release_actuator_override_locked()
                return

            try:
                target_sys = getattr(connection, "target_system", 1) or 1
                target_comp = getattr(connection, "target_component", 1) or 1
                connection.mav.rc_channels_override_send(
                    target_sys,
                    target_comp,
                    steering_pwm,
                    65535,
                    throttle_pwm,
                    65535,
                    65535,
                    65535,
                    65535,
                    65535,
                )
                self._override_active = True
            except Exception as exc:  # pragma: no cover - hardware-specific
                self._override_active = False
                logger.warning("Gagal mengirim RC override Pixhawk (%s)", exc)

    def _release_actuator_override(self) -> None:
        """Release channels so the physical RC transmitter regains authority."""
        with self._actuator_lock:
            self._release_actuator_override_locked()

    def _release_actuator_override_locked(self) -> None:
        """Release an active override; caller must hold ``_actuator_lock``."""
        connection = self._connection
        if connection is None or not self._override_active:
            return
        target_sys = getattr(connection, "target_system", 1) or 1
        target_comp = getattr(connection, "target_component", 1) or 1
        self._override_active = False
        try:
            connection.mav.rc_channels_override_send(
                target_sys,
                target_comp,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            )
        except Exception:  # pragma: no cover - hardware-specific
            logger.debug("Gagal melepas RC override Pixhawk", exc_info=True)

    async def close(self) -> None:
        self._stop = True
        self.clear_remote_control()
        self._release_actuator_override()
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

            endpoint = _resolve_pixhawk_endpoint(self.settings.pixhawk_endpoint)
            self._connection = await asyncio.to_thread(
                mavutil.mavlink_connection,
                endpoint,
                baud=self.settings.pixhawk_baud,
                autoreconnect=True,
                source_system=255,
                source_component=190,
            )
            self._last_pilot_input_monotonic = None
            self._mavlink_api = mavutil.mavlink
            self._connection_started_monotonic = time.monotonic()
            self._last_heartbeat_monotonic = None
            self._last_rc_monotonic = None
            self._mode = "UNKNOWN"
            self._override_active = False
            self._last_stream_target = None
            self._request_telemetry_streams()
            self._last_error = None
            logger.info("Pixhawk MAVLink reader connected to %s", endpoint)
        except Exception as exc:  # pragma: no cover - hardware-specific
            self._connection = None
            self._mavlink_api = None
            self._connection_started_monotonic = None
            self._next_reconnect = time.monotonic() + 0.5
            self._record_connection_error(exc)
    def _request_telemetry_streams(self) -> None:
        """Ask ArduPilot for continuous read-only telemetry without QGroundControl."""
        if self._connection is None or self._mavlink_api is None:
            return
        target = (
            getattr(self._connection, "target_system", 0) or 0,
            getattr(self._connection, "target_component", 0) or 0,
        )
        if target == self._last_stream_target:
            return
        try:
            stream_all = self._mavlink_api.MAV_DATA_STREAM_ALL
            self._connection.mav.request_data_stream_send(
                target[0],
                target[1],
                stream_all,
                4,
                1,
            )
            self._last_stream_target = target
        except Exception as exc:  # pragma: no cover - hardware-specific
            logger.warning("Gagal meminta stream telemetry Pixhawk (%s)", exc)

    async def _reset_connection(self, exc: Exception) -> None:
        """Close a broken serial link so the next cycle creates a fresh one."""
        self._record_connection_error(exc)
        connection = self._connection
        self.clear_remote_control()
        self._release_actuator_override()
        self._last_pilot_input_monotonic = None
        self._mavlink_api = None
        self._connection_started_monotonic = None
        self._last_stream_target = None
        self._last_heartbeat_monotonic = None
        self._mode = "UNKNOWN"
        self._next_reconnect = time.monotonic() + 0.5
        self._last_rc_monotonic = None
        if connection is not None:
            try:
                await asyncio.to_thread(connection.close)
            except Exception:  # pragma: no cover - hardware-specific
                logger.debug("Gagal menutup koneksi Pixhawk rusak", exc_info=True)
        self._connection = None
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
            mode_str = str(
                getattr(self._connection, "flightmode", "UNKNOWN") or "UNKNOWN"
            ).upper()
            if mode_str != self._mode:
                logger.info("Pixhawk flightmode berubah ke: %s", mode_str)
            self._mode = mode_str
            self._request_telemetry_streams()
            return

        if message_type == "VFR_HUD":
            heading = _finite_number(getattr(message, "heading", None))
            if heading is not None:
                self._heading_deg = heading % 360.0
            speed = _finite_number(getattr(message, "groundspeed", None))
            if speed is not None and speed >= 0:
                self._speed_mps = speed
            return

        if message_type == "RC_CHANNELS":
            steering = _finite_number(getattr(message, "chan1_raw", None))
            throttle = _finite_number(getattr(message, "chan3_raw", None))
            if (
                steering is not None
                and throttle is not None
                and 900 <= steering <= 2200
                and 900 <= throttle <= 2200
            ):
                self._last_rc_monotonic = now
                if abs(steering - 1500) > 60 or abs(throttle - 1500) > 60:
                    self._last_pilot_input_monotonic = now
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


def _resolve_pixhawk_endpoint(endpoint: str) -> str:
    """Prefer stable ArduPilot USB names and dynamic /dev/ttyACM* re-enumerations."""
    if endpoint.startswith(("tcp:", "udp:", "udpin:", "udpout:")):
        return endpoint

    import glob

    stable_matches = sorted(glob.glob("/dev/serial/by-id/*ArduPilot*"))
    if stable_matches:
        return stable_matches[0]

    configured_matches = sorted(glob.glob(endpoint))
    if configured_matches:
        return configured_matches[0]

    acm_matches = sorted(glob.glob("/dev/ttyACM*"))
    if acm_matches:
        return acm_matches[0]

    return endpoint


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
