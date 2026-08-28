"""FastAPI application for the Raspberry Pi ASV camera bridge."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from .config import BridgeSettings
from .control import (
    ControlAck,
    ControlError,
    ControlSessionRegistry,
    RemoteControlCommand,
)
from .frames import FrameTooLargeError, build_underwater_payload
from .state import AsvLiveStatus, BridgeState, ControlModePayload, VisionMetadata
from .telemetry import ActuatorCommand, PixhawkTelemetry, PixhawkTelemetryReader

def create_app(
    *,
    settings: BridgeSettings | None = None,
    state: BridgeState | None = None,
    telemetry_reader: PixhawkTelemetryReader | None = None,
) -> FastAPI:
    """Create an app with injectable local state for deterministic tests."""
    resolved_settings = settings or BridgeSettings.from_env()
    resolved_state = state or BridgeState(resolved_settings)
    resolved_telemetry = telemetry_reader or PixhawkTelemetryReader(resolved_settings)
    control_registry = ControlSessionRegistry()
    control_sockets: dict[str, WebSocket] = {}

    def clear_remote_control(session_id: str | None = None) -> None:
        clear = getattr(resolved_telemetry, "clear_remote_control", None)
        if callable(clear):
            clear(session_id)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async def publish_telemetry_payload(payload: dict[str, object]) -> None:
            resolved_state.publish_telemetry(payload)

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
        allow_methods=["GET", "PUT"],
        allow_headers=["Accept", "Content-Type"],
    )
    app.state.settings = resolved_settings
    app.state.bridge_state = resolved_state

    @app.get("/healthz")
    async def healthz() -> dict[str, object]:
        return {"ok": True, "service": "asv-dashboard-bridge"}

    @app.get("/api/status", response_model=AsvLiveStatus)
    async def get_status() -> AsvLiveStatus:
        return resolved_state.status

    @app.get("/api/control/mode", response_model=ControlModePayload)
    async def get_control_mode() -> ControlModePayload:
        return ControlModePayload(mode=resolved_state.control_mode)

    @app.put("/api/control/mode", response_model=ControlModePayload)
    async def put_control_mode(update: ControlModePayload) -> ControlModePayload:
        mode = resolved_state.set_control_mode(update.mode)
        if mode == "AUTONOMOUS":
            clear_remote_control()
        return ControlModePayload(mode=mode)

    @app.get("/api/telemetry", response_model=PixhawkTelemetry)
    async def get_telemetry() -> PixhawkTelemetry:
        return resolved_telemetry.snapshot()

    @app.post("/api/control/actuator")
    async def post_actuator_command(
        command: ActuatorCommand,
        request: Request,
    ) -> dict[str, object]:
        if not resolved_settings.model_actuators_enabled:
            raise HTTPException(status_code=503, detail="model actuators disabled")
        expected_token = resolved_settings.actuator_control_token
        provided_token = request.headers.get("x-asv-control-token", "")
        if expected_token is None or not secrets.compare_digest(
            provided_token, expected_token
        ):
            raise HTTPException(status_code=403, detail="invalid control token")
        resolved_telemetry.submit_actuator_command(command)
        return {"ok": True, "accepted": True}

    @app.put("/api/status", response_model=AsvLiveStatus)
    async def put_status(status: AsvLiveStatus) -> AsvLiveStatus:
        if status.id != resolved_settings.asv_id:
            raise HTTPException(status_code=409, detail="ASV id does not match bridge")
        resolved_state.update_status(status)
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

        return payload

    @app.post("/api/vision/metadata", response_model=VisionMetadata)
    async def post_vision_metadata(metadata: VisionMetadata) -> VisionMetadata:
        if metadata.asv_id != resolved_settings.asv_id:
            raise HTTPException(status_code=409, detail="ASV id does not match bridge")
        resolved_state.publish_detection(metadata)
        return metadata
    @app.websocket("/ws/control/{asv_id}")
    async def control_websocket(websocket: WebSocket, asv_id: str) -> None:
        origin = websocket.headers.get("origin")
        if (
            asv_id != resolved_settings.asv_id
            or not origin
            or origin not in resolved_settings.cors_origins
            or not resolved_settings.remote_control_enabled
        ):
            await websocket.close(code=1008)
            return

        await websocket.accept()
        session_id = secrets.token_urlsafe(18)
        _, previous_owner = control_registry.open(asv_id, session_id)
        control_sockets[session_id] = websocket
        if previous_owner is not None:
            clear_remote_control(previous_owner)
            previous_socket = control_sockets.get(previous_owner)
            if previous_socket is not None:
                try:
                    await previous_socket.close(code=4001)
                except (RuntimeError, WebSocketDisconnect):
                    pass

        async def send_error(code: str, message: str) -> None:
            error = ControlError(type="error", code=code, message=message)
            await websocket.send_json(error.model_dump(mode="json"))

        async def send_ack(
            command: RemoteControlCommand,
            accepted: bool,
            reason: str | None,
            server_received_at_ms: int,
        ) -> None:
            ack = ControlAck(
                type="ack",
                seq=command.seq,
                accepted=accepted,
                reason=reason,
                client_sent_at_ms=command.client_sent_at_ms,
                server_received_at_ms=server_received_at_ms,
            )
            await websocket.send_json(ack.model_dump(mode="json"))

        def reader_rejection_reason() -> str | None:
            check = getattr(resolved_telemetry, "remote_control_rejection_reason", None)
            if not callable(check):
                return None
            try:
                reason = check()
            except Exception:
                return "pixhawk_unavailable"
            return reason if reason in {
                "remote_control_disabled",
                "runtime_mode_autonomous",
                "pixhawk_unavailable",
                "flightmode_not_manual",
                "pilot_input_active",
            } else ("pixhawk_unavailable" if reason is not None else None)

        try:
            while True:
                try:
                    incoming = await websocket.receive()
                except WebSocketDisconnect:
                    break
                if incoming.get("type") == "websocket.disconnect":
                    break
                text = incoming.get("text")
                if not isinstance(text, str):
                    await send_error(
                        "invalid_message",
                        "control frame must be a text JSON object",
                    )
                    continue
                try:
                    payload = json.loads(text)
                except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
                    await send_error(
                        "invalid_json",
                        "control frame must be valid JSON",
                    )
                    continue
                try:
                    command = RemoteControlCommand.model_validate(payload)
                except ValidationError:
                    await send_error(
                        "invalid_message",
                        "control frame does not match the control schema",
                    )
                    continue

                server_received_at_ms = time.time_ns() // 1_000_000
                sequence_reason = control_registry.validate_sequence(
                    session_id, command.seq
                )
                if sequence_reason is not None:
                    await send_ack(
                        command,
                        accepted=False,
                        reason=sequence_reason,
                        server_received_at_ms=server_received_at_ms,
                    )
                    continue

                received_at = time.monotonic()
                if not command.enabled:
                    clear_remote_control(session_id)
                    await send_ack(
                        command,
                        accepted=True,
                        reason=None,
                        server_received_at_ms=server_received_at_ms,
                    )
                    continue

                reason: str | None = None
                if not resolved_settings.remote_control_enabled:
                    reason = "remote_control_disabled"
                elif resolved_state.control_mode != "MANUAL":
                    reason = "runtime_mode_autonomous"
                else:
                    reason = reader_rejection_reason()

                submit = getattr(resolved_telemetry, "submit_remote_control", None)
                if reason is None and not callable(submit):
                    reason = "pixhawk_unavailable"
                if reason is None:
                    try:
                        submit(command, session_id, received_at)
                    except Exception:
                        reason = "pixhawk_unavailable"

                await send_ack(
                    command,
                    accepted=reason is None,
                    reason=reason,
                    server_received_at_ms=server_received_at_ms,
                )
        finally:
            if control_registry.is_owner(asv_id, session_id):
                clear_remote_control(session_id)
                control_registry.release(asv_id, session_id)
            if control_sockets.get(session_id) is websocket:
                del control_sockets[session_id]


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
