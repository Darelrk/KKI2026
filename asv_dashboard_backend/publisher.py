"""Supabase publishing boundary with a no-network local fallback."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Protocol

from .config import BridgeSettings


class Publisher(Protocol):
    async def publish_status(self, status: dict[str, Any]) -> None: ...

    async def publish_underwater_frame(self, payload: dict[str, Any]) -> None: ...

    async def close(self) -> None: ...


class NullPublisher:
    """Keep the bridge usable locally when Supabase is intentionally disabled."""

    async def publish_status(self, status: dict[str, Any]) -> None:
        del status

    async def publish_underwater_frame(self, payload: dict[str, Any]) -> None:
        del payload

    async def close(self) -> None:
        return None


class SupabasePublisher:
    """Publish metadata to Postgres and bounded frames to Realtime Broadcast."""

    def __init__(self, client: Any, asv_id: str) -> None:
        self.client = client
        self.asv_id = asv_id
        self._channel: Any | None = None
        self._subscribed = False

    async def publish_status(self, status: dict[str, Any]) -> None:
        await asyncio.to_thread(
            lambda: self.client.table("asv_live")
            .upsert(status)
            .execute()
        )

    async def publish_underwater_frame(self, payload: dict[str, Any]) -> None:
        channel = await self._ensure_channel()
        result = channel.send_broadcast("underwater_frame", payload)
        if inspect.isawaitable(result):
            await result

    async def _ensure_channel(self) -> Any:
        if self._channel is None:
            self._channel = self.client.channel(
                f"asv-camera:{self.asv_id}",
                {"config": {"private": True}},
            )
        if not self._subscribed:
            result = self._channel.subscribe()
            if inspect.isawaitable(result):
                await result
            self._subscribed = True
        return self._channel

    async def close(self) -> None:
        remove = getattr(self.client, "remove_all_channels", None)
        if remove is None:
            return
        result = remove()
        if inspect.isawaitable(result):
            await result


def create_publisher(settings: BridgeSettings) -> Publisher:
    """Create the configured publisher, importing supabase only when enabled."""
    if not settings.supabase_enabled:
        return NullPublisher()

    try:
        from supabase import create_client
    except ImportError as exc:
        raise RuntimeError(
            "SUPABASE_URL is configured but the supabase package is missing"
        ) from exc

    client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return SupabasePublisher(client, settings.asv_id)
