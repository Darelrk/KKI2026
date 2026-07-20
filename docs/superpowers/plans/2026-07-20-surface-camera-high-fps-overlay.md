# Surface Camera High-FPS Model Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Keep the configured raw surface camera at 20–30 FPS while delivering YOLO detections at approximately 4 FPS as WebSocket metadata rendered by a frontend canvas overlay.

**Architecture:** The raw camera URL remains the dashboard's main `<img>` source; `/stream.mjpg` remains fallback/debug only. A latest-only capture queue feeds a paced model worker. The worker posts validated metadata to FastAPI, which fans out only the newest payload through `/ws/vision/{asv_id}`. React caches the latest payload and redraws a transparent canvas with `requestAnimationFrame`; it never replaces or re-renders the raw video when metadata arrives.

**Tech Stack:** Python 3, FastAPI, Pydantic, asyncio/WebSocket, OpenCV/Ultralytics, React 19, TypeScript, Zod, native WebSocket, Canvas 2D, Vitest, pytest.

---

## Scope and invariants

- Main camera source remains `VITE_ASV_SURFACE_STREAM_URL` / the existing configured raw URL.
- `/stream.mjpg` MUST NOT be used as `CameraStage`'s main `src`.
- Raw video target is 20–30 FPS; model inference target is approximately 4 FPS.
- Inference uses a latest-only queue of size 1; stale frames are dropped rather than processed.
- Detection metadata includes `schema_version`, `asv_id`, `frame_id`, source dimensions, timezone-aware `captured_at`, and normalized boxes.
- `track_id` is optional. No interpolation is allowed when it is absent.
- Frontend holds the latest valid metadata for 1 second, then clears the canvas while retaining raw video.
- No server-side bounding-box draw/re-encode on the main video path.
- Do not change RC override, throttle, steering, arming, disarming, ArduPilot mode, or Pixhawk telemetry behavior.
- Do not add Supabase migrations, detection history, WebRTC, or a tracker in this implementation.

## File map

| Responsibility | Files |
|---|---|
| Detection schema, latest-only state, WebSocket relay | `asv_dashboard_backend/state.py`, `asv_dashboard_backend/main.py` |
| Non-blocking metadata publisher and capture/inference split | `asv_dashboard_backend/vision_publisher.py`, `vision_test.py` |
| Backend tests | `tests/test_dashboard_backend.py`, `tests/test_vision_publisher.py`, new `tests/test_vision_capture.py` |
| Frontend metadata schema/cache/socket | new `dashboard/src/lib/vision-metadata.ts`, new `dashboard/src/lib/use-vision-metadata.ts` |
| Frontend raw camera and overlay | `dashboard/src/components/camera-stage.tsx`, `dashboard/src/components/dashboard-shell.tsx`, `dashboard/src/components/dashboard-client.tsx`, `dashboard/src/styles.css` |
| Frontend tests and fixtures | new `dashboard/src/lib/vision-metadata.test.ts`, new `dashboard/src/lib/use-vision-metadata.test.ts`, new `dashboard/src/components/camera-stage.test.tsx`, existing dashboard tests/fixtures |
| Deployment/config/docs | `dashboard/.env.example`, `deploy/raspberry-pi/asv-dashboard.env.example`, tunnel examples, `docs/superpowers/specs/2026-07-20-asv-dashboard.md` |

---

### Task 1: Add the validated metadata contract and latest-only backend relay

**Files:**
- Modify: `asv_dashboard_backend/state.py`
- Modify: `asv_dashboard_backend/main.py`
- Test: `tests/test_dashboard_backend.py`

- [ ] **Step 1: Add failing backend contract tests**

Add tests covering the observable contract before implementation:

```python
def valid_detection_payload(frame_id: int = 1) -> dict[str, object]:
    return {
        "schema_version": 1,
        "asv_id": "default",
        "frame_id": frame_id,
        "captured_at": "2026-07-20T10:00:00+00:00",
        "source_width": 1280,
        "source_height": 720,
        "detections": [{
            "track_id": None,
            "label": "buoy",
            "confidence": 0.9,
            "x": 0.1,
            "y": 0.1,
            "width": 0.2,
            "height": 0.2,
        }],
    }


def make_client() -> TestClient:
    return TestClient(create_app(settings=settings(), publisher=NullPublisher()))


def test_detection_metadata_rejects_invalid_schema_and_box():
    payload = valid_detection_payload()
    payload["schema_version"] = 2
    payload["detections"][0]["x"] = 0.9
    payload["detections"][0]["width"] = 0.2
    with make_client() as client:
        response = client.post("/api/vision/metadata", json=payload)
    assert response.status_code == 422


def test_detection_metadata_post_broadcasts_to_websocket():
    payload = valid_detection_payload()
    with make_client() as client:
        with client.websocket_connect("/ws/vision/default") as socket:
            response = client.post("/api/vision/metadata", json=payload)
            assert response.status_code == 200
            assert socket.receive_json() == payload


def test_detection_websocket_only_delivers_latest_payload():
    first = valid_detection_payload(frame_id=1)
    second = valid_detection_payload(frame_id=2)
    with make_client() as client:
        with client.websocket_connect("/ws/vision/default") as socket:
            assert client.post("/api/vision/metadata", json=first).status_code == 200
            assert client.post("/api/vision/metadata", json=second).status_code == 200
            assert socket.receive_json()["frame_id"] in (1, 2)
```

Use the existing imports and add explicit assertions for wrong ASV ID, disconnected clients, timezone-less timestamps, invalid confidence, zero dimensions, and boxes that exceed the source frame.


- [ ] **Step 2: Run the focused tests and confirm failure**

Run:

```bash
python -m pytest -q tests/test_dashboard_backend.py -k detection
```

Expected: FAIL because the metadata models and endpoints do not exist yet.

- [ ] **Step 3: Implement strict Pydantic metadata models**

In `state.py`, add models separate from the existing `vision_route.Detection` type:

```python
class VisionDetectionBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    track_id: int | None = None
    label: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def fit_inside_source(self) -> "VisionDetectionBox":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("detection box must fit inside source frame")
        return self


class VisionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    asv_id: str = Field(min_length=1)
    frame_id: int = Field(ge=0)
    captured_at: datetime
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    detections: list[VisionDetectionBox]

    @field_validator("captured_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        return value
```

Import `Literal`, `model_validator`, and the existing Pydantic primitives already used by the module. Keep strict extra-field rejection so frontend/backend contracts cannot silently diverge.

- [ ] **Step 4: Implement latest-only state and relay endpoints**

Extend `BridgeState` with:

```python
self._latest_detection: VisionMetadata | None = None
self._detection_subscribers: set[asyncio.Queue[VisionMetadata]] = set()
```

Implement `publish_detection`, `subscribe_detections`, and `unsubscribe_detections` so every subscriber queue has `maxsize=1`. When full, remove the queued payload before inserting the newest payload. New subscribers receive the latest payload once, if present. Unregister must be idempotent.

In `main.py`:

- Add `POST /api/vision/metadata` accepting `VisionMetadata`.
- Return `409` when `metadata.asv_id` does not equal `BridgeSettings.asv_id`.
- Store validated metadata and return it as JSON.
- Add `@app.websocket("/ws/vision/{asv_id}")`.
- Close wrong ASV IDs with a policy-violation close code.
- Accept valid clients, send only the newest payload, handle `WebSocketDisconnect`, and always unregister in `finally`.
- Do not add an unbounded inbound receive loop.
- Do not modify `Publisher`, Supabase migrations, `/api/frame/surface`, or `/stream.mjpg`.

- [ ] **Step 5: Run backend relay tests**

Run:

```bash
python -m pytest -q tests/test_dashboard_backend.py -k "detection or mjpeg"
```

Expected: all new detection tests and existing MJPEG fallback tests pass.

- [ ] **Step 6: Commit the backend relay**

```bash
git add asv_dashboard_backend/state.py asv_dashboard_backend/main.py tests/test_dashboard_backend.py
git commit -m "feat: add latest-only vision metadata relay"
```

Acceptance:

- Valid payloads are accepted and broadcast as JSON.
- Invalid schema/version/coordinates/timestamps never replace the latest payload.
- Slow clients never accumulate history.
- Disconnected clients are cleaned up.
- `/stream.mjpg` remains a fallback/debug endpoint only.

---

### Task 2: Decouple capture, inference pacing, and metadata publishing

**Files:**
- Modify: `asv_dashboard_backend/vision_publisher.py`
- Modify: `vision_test.py`
- Test: `tests/test_vision_publisher.py`
- Create: `tests/test_vision_capture.py`

- [ ] **Step 1: Add failing publisher and queue tests**

Test these behaviors before implementation:

```python
def test_detection_metadata_publisher_posts_json_without_surface_lane_collision():
    publisher = BridgeFramePublisher("http://bridge.test", asv_id="default")
    assert publisher.publish_detection_metadata(valid_metadata()) is True
    assert publisher.publish_surface_frame(b"\xff\xd8raw\xff\xd9", now=0) is True


def test_latest_frame_queue_replaces_queued_frame():
    queue = LatestFrameQueue()
    queue.put_latest(CapturedFrame(frame_id=1, frame=b"one", captured_at=timestamp()))
    queue.put_latest(CapturedFrame(frame_id=2, frame=b"two", captured_at=timestamp()))
    assert queue.get_nowait().frame_id == 2
```

Also test JSON content type/path, independent surface/metadata in-flight lanes, exact source frame ID/timestamp preservation, and normalized pixel-box conversion without silent clamping.

- [ ] **Step 2: Run focused publisher/capture tests and confirm failure**

```bash
python -m pytest -q tests/test_vision_publisher.py tests/test_vision_capture.py
```

Expected: FAIL because the metadata lane and latest-only capture helper do not exist.

- [ ] **Step 3: Add a non-blocking metadata publisher lane**

In `vision_publisher.py`, add `publish_detection_metadata(payload)` that submits compact JSON to `/api/vision/metadata` with `Content-Type: application/json`. Keep the existing executor and error reporting. Surface and metadata submissions must have independent in-flight state (or equivalent bounded lanes) so a pending fallback-frame upload cannot discard metadata updates.

Preserve `publish_status`, `publish_surface_frame`, `close`, and `last_error` contracts.

- [ ] **Step 4: Add a latest-only capture helper and normalization helper**

In `vision_test.py` or a focused helper module, define:

```python
@dataclass(frozen=True)
class CapturedFrame:
    frame: Any
    frame_id: int
    captured_at: datetime

class LatestFrameQueue:
    def __init__(self) -> None:
        self._items: deque[CapturedFrame] = deque(maxlen=1)
        self._condition = threading.Condition()
        self._closed = False

    def put_latest(self, item: CapturedFrame) -> None:
        with self._condition:
            self._items.clear()
            self._items.append(item)
            self._condition.notify()

    def get(self, timeout: float | None = None) -> CapturedFrame | None:
        with self._condition:
            if not self._items and not self._closed:
                self._condition.wait(timeout)
            if self._items:
                return self._items.popleft()
            return None

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
```

Use the project’s existing `Detection` type to normalize pixel boxes without clamping:

```python
def detection_metadata_from_result(
    detections: Sequence[Detection],
    *,
    asv_id: str,
    frame_id: int,
    captured_at: datetime,
    source_width: int,
    source_height: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "asv_id": asv_id,
        "frame_id": frame_id,
        "captured_at": captured_at.isoformat(),
        "source_width": source_width,
        "source_height": source_height,
        "detections": [
            {
                "track_id": None,
                "label": detection.label,
                "confidence": detection.confidence,
                "x": (detection.x_center - detection.width / 2) / source_width,
                "y": (detection.y_center - detection.height / 2) / source_height,
                "width": detection.width / source_width,
                "height": detection.height / source_height,
            }
            for detection in detections
        ],
    }
```

The helper must preserve source frame identity and must not fabricate `track_id` or clamp invalid model output.

- [ ] **Step 5: Refactor the vision loop without changing RC behavior**

Add `--vision-fps` with a positive default of `4.0`. Split the current camera loop into:

1. A capture producer that reads the camera continuously, assigns a monotonic integer `frame_id` and UTC `captured_at`, and calls `put_latest`.
2. An inference/control consumer paced to at most `--vision-fps`, which gets the newest frame, runs the existing `model.predict`, computes target/steering/throttle exactly as before, and publishes detection metadata for the processed frame.

Preserve all existing `MANUAL` checks, `send_override`, `release_override`, neutralization, and shutdown behavior. The queue changes only which frame is analyzed; it must not introduce a new MAVLink command or alter safety constants.

For local preview, continue to call `draw_detections` and `cv2.imshow` on a copy. If bridge publishing is enabled, publish only an unannotated/raw frame to the fallback lane; never send `annotated` to the main surface path. The dashboard continues using the configured raw URL.

Log `frame_id`, `captured_at`, `queue_age_ms`, and metadata publish status in the existing JSONL log. On shutdown, close the queue, join the producer, release the camera, send neutral override, release override, and close the bridge in the existing safe order.

- [ ] **Step 6: Run focused capture/publisher tests**

```bash
python -m pytest -q tests/test_vision_publisher.py tests/test_vision_capture.py tests/test_vision_route.py
python -m compileall -q asv_dashboard_backend vision_route.py vision_test.py tests
```

Acceptance:

- Producer can follow raw source rate without waiting on inference.
- Queue never holds more than one pending frame.
- Inference is paced near 4 FPS and never processes an old backlog.
- Metadata identifies the exact source frame processed.
- Main video receives no server-side annotations.
- RC/MAVLink behavior and shutdown remain unchanged.

- [ ] **Step 7: Commit the capture/inference split**

```bash
git add asv_dashboard_backend/vision_publisher.py vision_test.py tests/test_vision_publisher.py tests/test_vision_capture.py
git commit -m "feat: decouple raw capture from vision metadata"
```

---

### Task 3: Add frontend metadata validation, cache, and WebSocket hook

**Files:**
- Create: `dashboard/src/lib/vision-metadata.ts`
- Create: `dashboard/src/lib/use-vision-metadata.ts`
- Create: `dashboard/src/lib/vision-metadata.test.ts`
- Create: `dashboard/src/lib/use-vision-metadata.test.ts`
- Modify: `dashboard/src/lib/stream-urls.ts`
- Modify: `dashboard/src/lib/fixture-data.ts`
- Modify: `dashboard/.env.example`
- Test: `dashboard/src/lib/stream-urls.test.ts`, `dashboard/src/lib/fixture-data.test.ts`

- [ ] **Step 1: Add failing schema and hook tests**

Cover:

- unknown `schema_version` rejected;
- invalid confidence, dimensions, coordinates, and extra fields rejected;
- valid normalized box accepted;
- metadata cache stores `receivedAtMs` separately from `captured_at`;
- fixture mode never opens a socket;
- live mode connects to `/ws/vision/{encodedAsvId}`;
- invalid messages do not erase the last valid payload;
- reconnect cleanup leaves one socket and one retry timer;
- stale state clears after 1000 ms;
- missing WebSocket URL leaves raw video available.

- [ ] **Step 2: Run frontend focused tests and confirm failure**

```bash
npm --prefix dashboard run test -- src/lib/vision-metadata.test.ts src/lib/use-vision-metadata.test.ts src/lib/stream-urls.test.ts src/lib/fixture-data.test.ts
```

Expected: FAIL because the new schema/hook/fixture contract does not exist.

- [ ] **Step 3: Define strict Zod metadata schema and projection helpers**

Create `vision-metadata.ts` with a strict Zod schema mirroring backend fields. Store normalized coordinates, source dimensions, optional `track_id`, and a cache type:

```ts
export type VisionMetadataCache = {
  payload: VisionMetadata
  receivedAtMs: number
}

export function isVisionMetadataFresh(
  cache: VisionMetadataCache | null,
  nowMs: number,
  staleAfterMs = 1000,
): boolean {
  return cache !== null && nowMs - cache.receivedAtMs < staleAfterMs
}
```

Add pure projection helpers that account for `object-fit: contain`, source aspect ratio, CSS size, and device pixel ratio. They must not interpolate coordinates.

- [ ] **Step 4: Implement native WebSocket hook**

Create `use-vision-metadata.ts` with statuses `fixture | connecting | connected | error`. Use native `WebSocket`, a ref for the latest cache, one bounded retry timer, and cleanup on unmount. Parse incoming JSON with `safeParse`; invalid messages are ignored. Valid messages replace the cache atomically and set a 1-second stale deadline. Reconnect with bounded exponential backoff after close/error.

Fixture mode uses deterministic fixture metadata and never opens a network connection. Live mode uses a separate `VITE_ASV_VISION_WS_URL`, appends `/ws/vision/${encodeURIComponent(asvId)}`, and does not derive the metadata URL from the raw camera URL.

- [ ] **Step 5: Add fixtures and environment documentation**

Add a valid fixture payload with source `1280x720`, deterministic frame ID, `track_id: null`, and one normalized detection. Add `VITE_ASV_VISION_WS_URL` to `.env.example` with an explicit `ws://`/`wss://` example. Preserve `VITE_ASV_SURFACE_STREAM_URL` as the raw camera URL.

- [ ] **Step 6: Run frontend focused tests and typecheck**

```bash
npm --prefix dashboard run test -- src/lib/vision-metadata.test.ts src/lib/use-vision-metadata.test.ts src/lib/stream-urls.test.ts src/lib/fixture-data.test.ts
npm --prefix dashboard run typecheck
```

Acceptance:

- Valid backend payloads pass frontend validation.
- Invalid payloads never replace the last valid cache.
- WebSocket lifecycle has no duplicate sockets/timers.
- Fixture/live modes remain isolated.
- No new npm dependency is added.

- [ ] **Step 7: Commit metadata hook**

```bash
git add dashboard/src/lib/vision-metadata.ts dashboard/src/lib/use-vision-metadata.ts dashboard/src/lib/vision-metadata.test.ts dashboard/src/lib/use-vision-metadata.test.ts dashboard/src/lib/stream-urls.ts dashboard/src/lib/stream-urls.test.ts dashboard/src/lib/fixture-data.ts dashboard/src/lib/fixture-data.test.ts dashboard/.env.example
git commit -m "feat: add vision metadata websocket hook"
```

---

### Task 4: Render the overlay on top of the raw surface image

**Files:**
- Modify: `dashboard/src/components/camera-stage.tsx`
- Modify: `dashboard/src/components/dashboard-shell.tsx`
- Modify: `dashboard/src/components/dashboard-client.tsx`
- Modify: `dashboard/src/styles.css`
- Create: `dashboard/src/components/camera-stage.test.tsx`
- Test: existing dashboard shell/client/state tests

- [ ] **Step 1: Add failing overlay component tests**

Test that:

- raw `<img>` keeps the configured source while metadata changes;
- canvas is a sibling layered above the image and has `pointer-events: none`;
- rAF redraws cached detections without changing image `src`;
- normalized boxes map correctly with letterboxing and resize;
- stale metadata clears after 1 second;
- raw image remains when WebSocket/model is unavailable;
- no interpolation occurs with `track_id: null`.

Mock only `HTMLCanvasElement.getContext`, `requestAnimationFrame`, `cancelAnimationFrame`, `ResizeObserver`, `getBoundingClientRect`, and image natural dimensions.

- [ ] **Step 2: Run focused component tests and confirm failure**

```bash
npm --prefix dashboard run test -- src/components/camera-stage.test.tsx src/components/dashboard-shell.test.tsx src/components/dashboard-client.test.tsx src/components/dashboard-client-state.test.tsx
```

Expected: FAIL because `CameraStage` currently renders only the raw image/placeholder and has no metadata canvas.

- [ ] **Step 3: Add the raw-image/canvas structure**

Keep the existing raw image branch and wrap it in a relative media container:

```tsx
<div className="camera-stage__media">
  <img ref={imageRef} className="camera-stage__stream" src={streamUrl} alt="Live surface camera" />
  <canvas ref={canvasRef} className="camera-stage__overlay" aria-hidden="true" />
</div>
```

The canvas is never used as a video source and must not trigger `src` updates. Preserve the existing placeholder when `streamUrl` is null.

- [ ] **Step 4: Implement rAF drawing and stale handling**

Start one rAF loop on mount and cancel it on unmount. Each cycle:

1. Read the latest metadata cache.
2. Clear the full canvas.
3. Stop drawing boxes when `performance.now() - receivedAtMs >= 1000`.
4. Match canvas backing dimensions to CSS dimensions times `devicePixelRatio`.
5. Compute the contained source rectangle from `naturalWidth`/`naturalHeight` and the displayed image rect.
6. Project normalized boxes into the source rectangle.
7. Draw the latest positions only; do not interpolate unless a future tracker contract explicitly supplies stable `track_id` behavior.

Use `pointer-events: none` and keep raw video visible for every metadata/socket/model failure. Expose stale/reconnecting state with an accessible status without replacing the image.

- [ ] **Step 5: Wire hook through dashboard components**

Pass metadata cache/status from `DashboardClient` through `DashboardShell` to `CameraStage`. Keep `surfaceStreamUrl` defaulting to `asvStreamUrls.surface`. Do not pass `/stream.mjpg` or derive a new main source from backend frame fallback. Do not alter telemetry, mission, or Pixhawk status logic.

- [ ] **Step 6: Add minimal CSS**

Add only the camera media/overlay styles:

```css
.camera-stage__media {
  position: relative;
}

.camera-stage__overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
```

Preserve existing camera dimensions/object-fit and make sure the canvas uses the same displayed rectangle as the image.

- [ ] **Step 7: Run component tests**

```bash
npm --prefix dashboard run test -- src/components/camera-stage.test.tsx src/components/dashboard-shell.test.tsx src/components/dashboard-client.test.tsx src/components/dashboard-client-state.test.tsx
npm --prefix dashboard run test -- src/lib/vision-metadata.test.ts src/lib/use-vision-metadata.test.ts
```

Acceptance:

- Raw `<img>` remains mounted with the configured raw URL through metadata changes/errors.
- Canvas redraw is driven by rAF and not by replacing video frames.
- Boxes clear after 1 second of no new metadata.
- Aspect ratio, letterboxing, resize, and devicePixelRatio produce correct positions.
- No interpolation happens without `track_id`.

- [ ] **Step 8: Commit frontend overlay**

```bash
git add dashboard/src/components/camera-stage.tsx dashboard/src/components/dashboard-shell.tsx dashboard/src/components/dashboard-client.tsx dashboard/src/components/camera-stage.test.tsx dashboard/src/components/dashboard-shell.test.tsx dashboard/src/components/dashboard-client.test.tsx dashboard/src/components/dashboard-client-state.test.tsx dashboard/src/styles.css
git commit -m "feat: render detections over raw surface camera"
```

---

### Task 5: Align deployment documentation and raw-stream configuration

**Files:**
- Modify: `dashboard/.env.example`
- Modify: `deploy/raspberry-pi/asv-dashboard.env.example`
- Modify: `deploy/raspberry-pi/cloudflared-config.example.yml`
- Modify: `deploy/raspberry-pi/codex-prompt.txt`
- Modify: `deploy/raspberry-pi/handover-live-boat-track.md`
- Test: `dashboard/src/lib/stream-urls.test.ts`, dashboard shell/client tests

- [ ] **Step 1: Add a regression test for the main source**

Assert that `CameraStage`/dashboard fixture source is the configured raw surface URL and never `/stream.mjpg`.

- [ ] **Step 2: Update configuration documentation**

Document separately:

- `VITE_ASV_SURFACE_STREAM_URL`: browser-compatible raw 20–30 FPS surface source;
- `VITE_ASV_VISION_WS_URL`: metadata WebSocket base URL;
- `/stream.mjpg`: bounded bridge fallback/debug only.

Do not invent a new raw camera port/path. Keep the existing configured raw URL where it is valid. Ensure tunnel examples can route `/ws/vision/{asv_id}` with WebSocket upgrade and do not force the raw dashboard source through `/stream.mjpg`.

- [ ] **Step 3: Review docs for stale annotated-stream claims**

Run:

```bash
git grep -n "stream\.mjpg" -- dashboard/src deploy docs/superpowers/specs vision_test.py
```

Every remaining occurrence must be explicitly labeled fallback/debug or regression test. No main camera config or `CameraStage` source may reference it.

- [ ] **Step 4: Run config regressions**

```bash
npm --prefix dashboard run test -- src/lib/stream-urls.test.ts src/components/dashboard-shell.test.tsx src/components/dashboard-client.test.tsx
```

- [ ] **Step 5: Commit deployment docs/config**

```bash
git add dashboard/.env.example deploy/ docs/superpowers/specs/2026-07-20-asv-dashboard.md
 git commit -m "docs: separate raw camera and vision metadata paths"
```

Acceptance:

- Main camera is always the configured raw URL.
- WebSocket metadata has explicit configuration and tunnel documentation.
- `/stream.mjpg` is never described or used as the primary surface video.

---

### Task 6: Run full verification and Raspberry Pi smoke test

**Files:**
- No new source files; only fix failures in files from Tasks 1–5.

- [ ] **Step 1: Run backend focused verification**

```bash
python -m pytest -q tests/test_dashboard_backend.py tests/test_vision_publisher.py tests/test_vision_capture.py tests/test_vision_route.py
python -m compileall -q asv_dashboard_backend vision_route.py vision_test.py tests
```

- [ ] **Step 2: Run frontend focused verification**

```bash
npm --prefix dashboard run test -- src/lib/vision-metadata.test.ts src/lib/use-vision-metadata.test.ts src/components/camera-stage.test.tsx src/components/dashboard-shell.test.tsx src/components/dashboard-client.test.tsx src/components/dashboard-client-state.test.tsx src/lib/stream-urls.test.ts src/lib/fixture-data.test.ts
```

- [ ] **Step 3: Run static checks and builds**

```bash
npm --prefix dashboard run typecheck
npm --prefix dashboard run build
npm --prefix dashboard run lint
```

- [ ] **Step 4: Run regression suites**

```bash
python -m pytest -q
npm test
```

- [ ] **Step 5: Smoke-test dashboard behavior**

Start the existing dashboard dev server in fixture mode. Confirm:

- the main `<img>` uses the configured raw camera URL;
- no `/stream.mjpg` appears in the main image `src`;
- the canvas is layered above the image and has `pointer-events: none`;
- fixture metadata draws a box;
- the image remains when metadata is invalid/disconnected;
- the box clears after 1 second without a new payload;
- the image source never changes when metadata events arrive.

- [ ] **Step 6: Smoke-test Raspberry Pi behavior**

On the Pi, use the configured service/runtime without `--reload`:

```bash
curl -fsS http://127.0.0.1:8080/healthz
systemctl status asv-dashboard
journalctl -u asv-dashboard --since -5m
```

During at least a 30-second test:

- measure the configured raw source at 20–30 FPS;
- count WebSocket metadata at approximately 4 messages/second;
- inspect `frame_id`, `queue_age_ms`, and metadata publish errors;
- verify queue age does not grow;
- monitor CPU, RSS, and temperature.

Stop only the model process and confirm raw video remains available while the canvas clears at 1 second. Confirm no new RC/MAVLink commands or safety behavior changes.

- [ ] **Step 7: Commit only necessary verification fixes**

Do not create formatter-only or cosmetic commits. If verification exposes a real defect, fix the smallest root cause, rerun the affected checks, and commit with a behavior-specific message.

Final acceptance:

- Raw main camera is smooth at 20–30 FPS from its configured raw URL.
- YOLO runs near 4 FPS without creating a stale inference backlog.
- Metadata is validated, latest-only, timestamped, and delivered through `/ws/vision/{asv_id}`.
- Canvas redraws with rAF and holds the latest valid box for at most 1 second.
- No interpolation occurs without `track_id`.
- Raw video remains visible when model/metadata/WebSocket fails.
- `/stream.mjpg` remains fallback/debug only.
- No server-side annotated-video re-encode is used for the main camera.
- All backend/frontend tests, static checks, builds, and Pi smoke checks pass.
- Pixhawk/RC/MAVLink behavior is unchanged.

## Risk controls

- If the configured raw URL cannot actually sustain 20–30 FPS, benchmark and fix the camera source/deployment separately; do not use `/stream.mjpg` or server-side re-encoding as a shortcut.
- If a public tunnel cannot upgrade WebSocket connections, fix routing/configuration before changing frontend fallback behavior.
- If publisher lanes collide, keep metadata and fallback-frame backpressure independent.
- If capture shutdown races with Pixhawk cleanup, preserve the existing neutralize/release ordering and add a bounded producer shutdown.
- If canvas letterboxing or devicePixelRatio causes drift, fix the projection helper and add a deterministic aspect-ratio test; do not alter detection coordinates at the model source.
- If the model provides no stable object identity, retain the last box without synthetic motion.
- Any future tracker/interpolation work is a separate spec and must not be smuggled into this implementation.

## References

- Design spec: `docs/superpowers/specs/2026-07-20-surface-camera-high-fps-overlay-design.md`
- FastAPI StreamingResponse: https://fastapi.tiangolo.com/advanced/custom-response/
- OpenCV GStreamer/appsink behavior: https://github.com/opencv/opencv/blob/4.x/modules/videoio/src/cap_gstreamer.cpp
- GStreamer queue limits/leaky behavior: https://github.com/GStreamer/gstreamer/blob/main/subprojects/gstreamer/plugins/elements/gstqueue.c
- GStreamer video with metadata: https://blog.dev-threads.de/posts/webrtc-with-gstreamer-and-metadata/
