"""Strict remote-control protocol models and in-memory session ownership."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MAX_SAFE_INTEGER = 9_007_199_254_740_991
RejectReason = Literal[
    "stale_sequence",
    "remote_control_disabled",
    "runtime_mode_autonomous",
    "pixhawk_unavailable",
    "flightmode_not_manual",
    "pilot_input_active",
    "superseded",
]
REJECT_REASONS = frozenset(
    {
        "stale_sequence",
        "remote_control_disabled",
        "runtime_mode_autonomous",
        "pixhawk_unavailable",
        "flightmode_not_manual",
        "pilot_input_active",
        "superseded",
    }
)
ControlErrorCode = Literal["invalid_json", "invalid_message", "origin_not_allowed"]
class RemoteControlCommand(BaseModel):
    """One strict direct-PWM command received on the remote channel."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["control"]
    seq: int = Field(gt=0, le=MAX_SAFE_INTEGER)
    client_sent_at_ms: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    steering_pwm: int = Field(ge=1000, le=2000)
    throttle_pwm: int = Field(ge=1000, le=2000)
    enabled: bool



class ControlAck(BaseModel):
    """Internal acknowledgement for a parsed control command."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["ack"]
    seq: int = Field(gt=0, le=MAX_SAFE_INTEGER)
    accepted: bool
    reason: RejectReason | None
    client_sent_at_ms: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    server_received_at_ms: int = Field(ge=0, le=MAX_SAFE_INTEGER)

    @model_validator(mode="after")
    def validate_reason_coherence(self) -> "ControlAck":
        if self.accepted != (self.reason is None):
            raise ValueError("accepted must be true exactly when reason is null")
        return self


class ControlError(BaseModel):
    """Internal parse/handshake error that never exposes implementation detail."""

    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["error"]
    code: ControlErrorCode
    message: str = Field(min_length=1)


@dataclass(slots=True)
class _ActiveSession:
    asv_id: str
    session_id: str
    last_sequence: int = 0


class ControlSessionRegistry:
    """Keep one current control session and sequence cursor per ASV."""

    def __init__(self) -> None:
        self._sessions: dict[str, _ActiveSession] = {}
        self._lock = Lock()

    def open(self, asv_id: str, session_id: str) -> tuple[str, str | None]:
        """Make ``session_id`` current and return it plus the previous owner."""
        if not asv_id.strip():
            raise ValueError("asv_id must not be empty")
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        with self._lock:
            previous = self._sessions.get(asv_id)
            self._sessions[asv_id] = _ActiveSession(asv_id, session_id)
        return session_id, previous.session_id if previous else None

    def validate_sequence(self, session_id: str, sequence: int) -> RejectReason | None:
        """Advance a current session only when its sequence strictly increases."""
        with self._lock:
            session = next(
                (candidate for candidate in self._sessions.values() if candidate.session_id == session_id),
                None,
            )
            if session is None:
                return "superseded"
            if (
                type(sequence) is not int
                or sequence <= session.last_sequence
                or sequence <= 0
                or sequence > MAX_SAFE_INTEGER
            ):
                return "stale_sequence"
            session.last_sequence = sequence
            return None

    def is_owner(self, asv_id: str, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(asv_id)
            return session is not None and session.session_id == session_id

    def release(self, asv_id: str, session_id: str) -> bool:
        """Release only if ``session_id`` still owns ``asv_id``."""
        with self._lock:
            session = self._sessions.get(asv_id)
            if session is None or session.session_id != session_id:
                return False
            del self._sessions[asv_id]
            return True

    def owner(self, asv_id: str) -> str | None:
        """Return the current owner for tests and lifecycle coordination."""
        with self._lock:
            session = self._sessions.get(asv_id)
            return session.session_id if session else None
