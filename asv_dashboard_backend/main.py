"""FastAPI application for the Raspberry Pi ASV camera bridge."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .config import BridgeSettings
from .frames import FrameTooLargeError, build_underwater_payload
from .publisher import Publisher, create_publisher
from .state import AsvLiveStatus, BridgeState, VisionMetadata
from .telemetry import PixhawkTelemetry, PixhawkTelemetryReader


def create_app(
    *,
    settings: BridgeSettings | None = None,
    publisher: Publisher | None = None,
    state: BridgeState | None = None,
    telemetry_reader: PixhawkTelemetryReader | None = None,
) -> FastAPI:
    """Create an app with injectable state and publisher for deterministic tests."""
    resolved_settings = settings or BridgeSettings.from_env()
    resolved_state = state or BridgeState(resolved_settings)
    resolved_publisher = publisher or create_publisher(resolved_settings)
    resolved_telemetry = telemetry_reader or PixhawkTelemetryReader(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async def publish_telemetry_payload(payload: dict[str, object]) -> None:
            resolved_state.publish_telemetry(payload)
            await resolved_publisher.publish_telemetry(payload)

        telemetry_task = None
        if resolved_settings.pixhawk_enabled:
            telemetry_task = asyncio.create_task(
                resolved_telemetry.run(publish_telemetry_payload)
            )
        try:
            yield
        finally:
            await resolved_telemetry.close()
            if telemetry_task is not None:
                telemetry_task.cancel()
                await asyncio.gather(telemetry_task, return_exceptions=True)
            await resolved_publisher.close()

    app = FastAPI(
        title="ASV Raspberry Pi Bridge",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Accept", "Content-Type"],
    )
    app.state.settings = resolved_settings
    app.state.bridge_state = resolved_state
    app.state.publisher = resolved_publisher

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        return {"ok": True, "service": "asv-dashboard-bridge"}

    @app.get("/api/status", response_model=AsvLiveStatus)
    async def get_status() -> AsvLiveStatus:
        return resolved_state.status

    @app.get("/api/telemetry", response_model=PixhawkTelemetry)
    async def get_telemetry() -> PixhawkTelemetry:
        return resolved_telemetry.snapshot()

    @app.put("/api/status", response_model=AsvLiveStatus)
    async def put_status(status: AsvLiveStatus) -> AsvLiveStatus:
        if status.id != resolved_settings.asv_id:
            raise HTTPException(status_code=409, detail="ASV id does not match bridge")
        resolved_state.update_status(status)
        await resolved_publisher.publish_status(status.model_dump(mode="json"))
        return status

    @app.post("/api/frame/surface")
    async def post_surface_frame(request: Request) -> dict[str, object]:
        frame = await request.body()
        try:
            resolved_state.update_surface_frame(frame)
        except ValueError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        return {"ok": True, "size_bytes": len(frame)}

    @app.post("/api/frame/underwater")
    async def post_underwater_frame(request: Request) -> dict[str, str]:
        frame = await request.body()
        if not frame:
            raise HTTPException(status_code=400, detail="JPEG body is required")
        frame_id = request.headers.get("x-frame-id") or _generated_frame_id()
        try:
            payload = build_underwater_payload(
                frame,
                frame_id=frame_id,
                captured_at=datetime.now(timezone.utc),
                max_base64_length=resolved_settings.max_base64_length,
            )
        except FrameTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc

        await resolved_publisher.publish_underwater_frame(payload)
        return payload

    @app.post("/api/vision/metadata", response_model=VisionMetadata)
    async def post_vision_metadata(metadata: VisionMetadata) -> VisionMetadata:
        if metadata.asv_id != resolved_settings.asv_id:
            raise HTTPException(status_code=409, detail="ASV id does not match bridge")
        resolved_state.publish_detection(metadata)
        return metadata

    @app.websocket("/ws/vision/{asv_id}")
    async def vision_metadata_websocket(websocket: WebSocket, asv_id: str) -> None:
        if asv_id != resolved_settings.asv_id:
            await websocket.close(code=1008)
            return

        await websocket.accept()
        queue = resolved_state.subscribe_detections()

        async def send_loop() -> None:
            try:
                while True:
                    metadata = await queue.get()
                    await websocket.send_json(metadata.model_dump(mode="json"))
            except WebSocketDisconnect:
                return

        async def receive_loop() -> None:
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                return

        send_task = asyncio.create_task(send_loop())
        try:
            await receive_loop()
        finally:
            send_task.cancel()
            await asyncio.gather(send_task, return_exceptions=True)
            resolved_state.unsubscribe_detections(queue)

    @app.websocket("/ws/telemetry/{asv_id}")
    async def telemetry_websocket(websocket: WebSocket, asv_id: str) -> None:
        if asv_id != resolved_settings.asv_id:
            await websocket.close(code=1008)
            return

        await websocket.accept()
        queue = resolved_state.subscribe_telemetry()

        async def send_loop() -> None:
            try:
                while True:
                    payload = await queue.get()
                    await websocket.send_json(payload)
            except WebSocketDisconnect:
                return

        async def receive_loop() -> None:
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                return

        send_task = asyncio.create_task(send_loop())
        try:
            await receive_loop()
        finally:
            send_task.cancel()
            await asyncio.gather(send_task, return_exceptions=True)
            resolved_state.unsubscribe_telemetry(queue)
    @app.get("/stream.mjpg")
    async def stream_mjpeg(once: bool = False) -> StreamingResponse:
        return StreamingResponse(
            resolved_state.mjpeg_stream(once=once),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
            },
        )

    return app


def _generated_frame_id() -> str:
    return f"frame-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"


app = create_app()
