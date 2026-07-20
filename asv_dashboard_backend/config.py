"""Environment-backed settings for the Raspberry Pi ASV bridge."""

from __future__ import annotations

from dataclasses import dataclass
from os import environ
from urllib.parse import urlparse


class ConfigError(ValueError):
    """Raised when bridge configuration cannot be used safely."""


@dataclass(frozen=True, slots=True)
class BridgeSettings:
    """Validated runtime settings with safe local defaults."""

    asv_id: str = "default"
    host: str = "0.0.0.0"
    port: int = 8080
    stream_url: str | None = None
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    max_base64_length: int = 180_000
    max_fps: float = 1.0
    frame_wait_timeout: float = 1.0

    def __post_init__(self) -> None:
        if not self.asv_id.strip():
            raise ConfigError("ASV_ID must not be empty")
        if not 1 <= self.port <= 65_535:
            raise ConfigError("ASV_BACKEND_PORT must be between 1 and 65535")
        if self.stream_url is not None:
            _require_https_url(self.stream_url, "ASV_STREAM_URL")
        if bool(self.supabase_url) != bool(self.supabase_service_role_key):
            raise ConfigError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured together"
            )
        if self.max_base64_length < 4:
            raise ConfigError("ASV_FALLBACK_MAX_BASE64 must be at least 4")
        if self.max_fps <= 0:
            raise ConfigError("ASV_FALLBACK_MAX_FPS must be positive")
        if self.frame_wait_timeout <= 0:
            raise ConfigError("ASV_FRAME_WAIT_TIMEOUT must be positive")

    @property
    def supabase_enabled(self) -> bool:
        """Return whether remote publishing is configured."""
        return self.supabase_url is not None

    @classmethod
    def from_env(cls) -> BridgeSettings:
        """Load settings from environment variables used on the Pi."""
        return cls(
            asv_id=environ.get("ASV_ID", "default"),
            host=environ.get("ASV_BACKEND_HOST", "0.0.0.0"),
            port=_int_env("ASV_BACKEND_PORT", 8080),
            stream_url=_optional_env("ASV_STREAM_URL"),
            supabase_url=_optional_env("SUPABASE_URL"),
            supabase_service_role_key=_optional_env("SUPABASE_SERVICE_ROLE_KEY"),
            max_base64_length=_int_env("ASV_FALLBACK_MAX_BASE64", 180_000),
            max_fps=_float_env("ASV_FALLBACK_MAX_FPS", 1.0),
            frame_wait_timeout=_float_env("ASV_FRAME_WAIT_TIMEOUT", 1.0),
        )


def _optional_env(name: str) -> str | None:
    value = environ.get(name)
    return value.strip() if value and value.strip() else None


def _int_env(name: str, default: int) -> int:
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _float_env(name: str, default: float) -> float:
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc


def _require_https_url(value: str, name: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError(f"{name} must be an absolute HTTPS URL")
