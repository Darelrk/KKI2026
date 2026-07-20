"""Non-blocking local HTTP publisher for the existing vision process."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen


class BridgeFramePublisher:
    """Send local bridge updates without blocking Pixhawk control or inference."""

    def __init__(
        self,
        bridge_url: str,
        *,
        asv_id: str,
        stream_url: str | None = None,
        max_surface_fps: float = 5.0,
        timeout_seconds: float = 2.0,
    ) -> None:
        if not bridge_url.startswith("http://") and not bridge_url.startswith("https://"):
            raise ValueError("bridge_url must be an HTTP or HTTPS URL")
        if not asv_id.strip():
            raise ValueError("asv_id must not be empty")
        if max_surface_fps <= 0:
            raise ValueError("max_surface_fps must be positive")
        self.base_url = bridge_url.rstrip("/")
        self.asv_id = asv_id
        self.stream_url = stream_url
        self.max_surface_interval = 1.0 / max_surface_fps
        self.timeout_seconds = timeout_seconds
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asv-bridge")
        self._lock = threading.Lock()
        self._future: Future[None] | None = None
        self._last_surface_at = float("-inf")

    def publish_status(
        self,
        *,
        online: bool,
        model_status: str,
        camera: str = "surface",
        run_id: str | None = None,
    ) -> bool:
        payload = {
            "id": self.asv_id,
            "online": online,
            "model_status": model_status,
            "camera": camera,
            "stream_url": self.stream_url,
            "run_id": run_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        return self._submit(
            "PUT",
            "/api/status",
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            "application/json",
        )

    def publish_surface_frame(self, jpeg_bytes: bytes, *, now: float | None = None) -> bool:
        """Queue at most the configured FPS; continuous video stays on local HTTP."""
        current = time.monotonic() if now is None else now
        with self._lock:
            if current - self._last_surface_at < self.max_surface_interval:
                return False
            self._last_surface_at = current
        return self._submit("POST", "/api/frame/surface", jpeg_bytes, "image/jpeg")

    def publish_underwater_frame(
        self,
        jpeg_bytes: bytes,
        *,
        frame_id: str,
    ) -> bool:
        return self._submit(
            "POST",
            "/api/frame/underwater",
            jpeg_bytes,
            "image/jpeg",
            {"X-Frame-ID": frame_id},
        )

    def _submit(
        self,
        method: str,
        path: str,
        body: bytes,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
    ) -> bool:
        with self._lock:
            if self._future is not None and not self._future.done():
                return False
            headers = {"Content-Type": content_type, **(extra_headers or {})}
            self._future = self._executor.submit(
                self._send,
                method,
                path,
                body,
                headers,
            )
        return True

    def _send(
        self,
        method: str,
        path: str,
        body: bytes,
        headers: dict[str, str],
    ) -> None:
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            response.read()
    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    def last_error(self) -> BaseException | None:
        """Return the last async error without interrupting the vision loop."""
        with self._lock:
            if self._future is None or not self._future.done():
                return None
            return self._future.exception()
