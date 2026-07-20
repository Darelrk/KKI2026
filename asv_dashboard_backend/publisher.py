"""Supabase publishing boundary with a no-network local fallback."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Protocol

from .config import BridgeSettings


class Publisher(Protocol):
    async def publish_status(self, status: dict[str, Any]) -> None: ...

    async def publish_underwater_frame(self, payload: dict[str, Any]) -> None: ...

    async def publish_telemetry(self, telemetry: dict[str, Any]) -> None: ...

    async def close(self) -> None: ...


class NullPublisher:
    """Keep the bridge usable locally when Supabase is intentionally disabled."""

    async def publish_status(self, status: dict[str, Any]) -> None:
        del status

    async def publish_underwater_frame(self, payload: dict[str, Any]) -> None:
        del payload

    async def publish_telemetry(self, telemetry: dict[str, Any]) -> None:
        del telemetry

    async def close(self) -> None:
        return None


class SupabasePublisher:
    """Publish metadata to Postgres and bounded frames to Realtime Broadcast."""

    def __init__(
        self,
        client: Any,
        asv_id: str,
        *,
        realtime_client: Any | None = None,
        realtime_url: str | None = None,
        realtime_key: str | None = None,
    ) -> None:
        self.client = client
        self.asv_id = asv_id
        self._realtime_client = realtime_client
        self._realtime_url = realtime_url
        self._realtime_key = realtime_key
        self._channels: dict[str, Any] = {}
        self._subscribed_topics: set[str] = set()

    async def publish_status(self, status: dict[str, Any]) -> None:
        await asyncio.to_thread(
            lambda: self.client.table("asv_live")
            .upsert(status)
            .execute()
        )

    async def publish_underwater_frame(self, payload: dict[str, Any]) -> None:
        channel = await self._ensure_channel(f"asv-camera:{self.asv_id}")
        result = channel.send_broadcast("underwater_frame", payload)
        if inspect.isawaitable(result):
            await result

    async def publish_telemetry(self, telemetry: dict[str, Any]) -> None:
        channel = await self._ensure_channel(f"asv-telemetry:{self.asv_id}")
        result = channel.send_broadcast("telemetry", telemetry)
        if inspect.isawaitable(result):
            await result

    async def _ensure_channel(self, topic: str) -> Any:
        if topic not in self._channels:
            realtime_client = await self._get_realtime_client()
            self._channels[topic] = realtime_client.channel(
                topic,
                {"config": {"private": True}},
            )
        if topic not in self._subscribed_topics:
            result = self._channels[topic].subscribe()
            if inspect.isawaitable(result):
                await result
            self._subscribed_topics.add(topic)
        return self._channels[topic]

    async def _get_realtime_client(self) -> Any:
        if self._realtime_client is not None:
            return self._realtime_client
        if self._realtime_url is None or self._realtime_key is None:
            # Injectable tests and local fakes can use one client for both APIs.
            return self.client

        try:
            from supabase import create_async_client
        except ImportError as exc:
            raise RuntimeError(
                "Supabase async client is required for Realtime Broadcast"
            ) from exc

        self._realtime_client = await create_async_client(
            self._realtime_url,
            self._realtime_key,
        )
        return self._realtime_client

    async def close(self) -> None:
        if self._realtime_client is not None:
            clients = [self._realtime_client]
        elif self._realtime_url is None or self._realtime_key is None:
            # Injectable tests and local fakes can use one client for both APIs.
            clients = [self.client]
        else:
            # The async Realtime client was never opened, so there is nothing
            # to close. The sync client is used only for Postgres upserts.
            clients = []
        for client in clients:
            remove = getattr(client, "remove_all_channels", None)
            if remove is None:
                continue
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
    return SupabasePublisher(
        client,
        settings.asv_id,
        realtime_url=settings.supabase_url,
        realtime_key=settings.supabase_service_role_key,
    )
