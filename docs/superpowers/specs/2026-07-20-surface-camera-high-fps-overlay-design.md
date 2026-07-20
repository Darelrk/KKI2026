# Surface Camera High-FPS Model Overlay

Date: 2026-07-20

## Decision

Keep the main surface camera on its raw 20–30 FPS stream. Deliver model detections as low-rate metadata at approximately 4 FPS and draw them in a transparent frontend canvas. The model output must never replace the main video frames.

The dashboard must not use `/stream.mjpg` as the main surface video. That endpoint remains a bounded latest-frame fallback/debug stream. The main surface feed uses the configured raw camera URL already consumed by `CameraStage`.

## Goals

- Keep the main surface camera visually smooth at its source FPS (target 20–30 FPS).
- Keep YOLO/model inference near 4 FPS on Raspberry Pi 5.
- Show the latest valid detections over the raw stream without server-side video re-encoding.
- Continue displaying raw video when the model, metadata channel, or overlay fails.
- Clear the overlay when no metadata arrives for 1 second.
- Preserve frame identity and capture timing in every detection payload.
- Avoid adding latency by processing stale frames.

## Non-goals

- No server-side bounding-box drawing or annotated-video re-encoding.
- No automatic upgrade to WebRTC before the raw stream path is benchmarked.
- No invented box interpolation when detections do not have object identity.
- No changes to RC override, throttle, steering, arming, disarming, or ArduPilot mode behavior.
- No persistent detection history or database schema change in the first implementation.

## Current repository constraints

`vision_test.py` currently executes capture, model inference, drawing, JPEG encoding, and `publish_surface_frame()` in one sequential loop. That couples the published surface-frame rate to model throughput.

`BridgeFramePublisher.publish_surface_frame()` already applies a maximum publish interval and drops work while an earlier HTTP request is pending. This protects the bridge from an unbounded publisher backlog, but it does not create an independent raw high-FPS video path.

The backend `BridgeState` stores one latest surface JPEG and `/stream.mjpg` serves it as multipart MJPEG. This endpoint is retained as a fallback/debug path and is not the dashboard's primary surface stream.

## Architecture

```text
Raw camera source, 20–30 FPS
        |
        +--> raw stream URL ----------------------> dashboard <img>
        |                                             |
        +--> latest-frame queue, maxsize=1            +--> transparent canvas
                    |                                      |
                    +--> model worker, ~4 FPS              +--> requestAnimationFrame
                                |
                                +--> detection metadata
                                      |
                                      +--> backend metadata relay
                                            |
                                            +--> WebSocket to dashboard
```

### Raw stream branch

The raw branch owns the user-visible camera feed. It must not pass through model drawing, JPEG annotation, or a slow inference loop. A camera-native MJPEG stream is preferred when the source supports it. Any future USB/CSI capture adapter must preserve the same raw-stream and latest-frame interfaces.

### Inference branch

The capture/inference boundary uses a latest-only queue. When the model is busy, the next capture replaces the queued frame instead of waiting behind old work. Every inference result carries the source frame identifier and timestamp. The model may run at approximately 4 FPS while the raw stream continues at 20–30 FPS.

The first implementation may hold the last detection box between model updates. It must not interpolate movement without an object identity. If smoother motion is later required, the payload must include a stable `track_id` and the tracker/interpolation behavior must be specified and tested separately.

### Metadata transport

The dashboard-facing transport is a WebSocket because it supports a persistent low-rate metadata channel and leaves room for future model controls without coupling them to the video stream. The initial metadata direction is server-to-browser only.

The model runtime may continue to publish to the local backend using the existing non-blocking HTTP publisher pattern. The backend fans out validated metadata to WebSocket clients and retains only the newest payload per ASV/client path.

Suggested endpoint:

```text
GET /ws/vision/{asv_id}
```

The endpoint must validate the ASV identity, close stale/disconnected clients, and avoid an unbounded per-client queue. A slow browser receives the newest metadata rather than every historical detection.

## Detection payload

```json
{
  "schema_version": 1,
  "asv_id": "default",
  "frame_id": 18231,
  "captured_at": "2026-07-20T10:00:00.123Z",
  "source_width": 1280,
  "source_height": 720,
  "detections": [
    {
      "track_id": null,
      "label": "buoy",
      "confidence": 0.91,
      "x": 0.328,
      "y": 0.250,
      "width": 0.094,
      "height": 0.132
    }
  ]
}
```

- `frame_id` identifies the source frame used by the model.
- `captured_at` is the source-frame timestamp, not the WebSocket send time.
- Box coordinates are normalized to 0–1 relative to the source frame.
- `track_id` is optional. A missing `track_id` forbids motion interpolation.
- Invalid coordinates, negative dimensions, invalid confidence, and unknown schema versions are rejected.

## Frontend overlay behavior

`CameraStage` keeps the raw surface `<img>` mounted independently of metadata state. The overlay layer is a sibling canvas positioned above it.

The frontend stores the newest validated metadata in a ref/cache. A `requestAnimationFrame` loop redraws the canvas at display refresh rate; metadata events do not trigger video replacement or video re-rendering.

Each draw cycle:

1. Match the canvas backing dimensions to the displayed raw image and its source aspect ratio.
2. Clear the previous overlay.
3. If the newest metadata is no older than 1 second, transform normalized boxes into canvas coordinates and draw them.
4. If the metadata is stale, draw no boxes and expose a stale-model status.

The canvas uses `pointer-events: none` and does not intercept camera interactions. The raw stream remains visible when the WebSocket is disconnected or model status is offline.

The first implementation does not interpolate box positions. Future interpolation is allowed only when `track_id` is present and a tracker contract defines how identity, disappearance, reappearance, and crossing objects are handled.

## Failure handling

- **Raw stream unavailable:** show the existing camera placeholder; metadata must not create a fake video.
- **WebSocket unavailable:** keep raw video visible, clear stale boxes after 1 second, and expose reconnecting status.
- **Model stopped:** raw video continues; overlay clears after the same stale timeout.
- **Model slower than 4 FPS:** raw video is unaffected; newest metadata replaces older metadata.
- **Capture queue full:** drop the older queued frame; never block the raw stream on inference.
- **Invalid metadata:** reject the payload and retain the last valid payload only until its 1-second stale deadline.
- **Browser resize/aspect change:** resize the canvas backing store and redraw from cached metadata without reloading the video.

Detection metadata used for display must remain separate from the Pixhawk control path. A stale or missing display payload must not silently produce a control command.

## Verification plan

### Backend

- Validate the detection payload schema and normalized box bounds.
- Verify latest-only storage/fan-out does not grow with slow clients.
- Verify disconnected WebSocket clients are removed.
- Verify metadata publication remains non-blocking for the camera/model loop.
- Verify `/stream.mjpg` remains available only as fallback and is not used by the dashboard main camera.

### Frontend

- Verify `CameraStage` renders the raw surface URL independently of metadata state.
- Verify the canvas is layered above the raw `<img>` with `pointer-events: none`.
- Verify metadata events update the cache without replacing the image source.
- Verify `requestAnimationFrame` keeps drawing the cached box between metadata events.
- Verify boxes disappear after 1 second without a new payload.
- Verify raw video remains present when metadata is unavailable.
- Verify no interpolation occurs when `track_id` is absent.
- Verify normalized coordinates remain correct after resize.

### Raspberry Pi smoke test

- Confirm raw surface stream is 20–30 FPS at the dashboard source.
- Confirm model metadata rate is approximately 4 messages/second.
- Confirm inference queue age does not grow over time.
- Confirm CPU, memory, and temperature remain stable during a sustained run.
- Confirm stopping the model does not stop the raw camera stream.
- Confirm no RC/MAVLink behavior changes are introduced by the display path.

## Research references

- FastAPI `StreamingResponse`: https://fastapi.tiangolo.com/advanced/custom-response/
- OpenCV GStreamer capture and latest-frame appsink behavior: https://github.com/opencv/opencv/blob/4.x/modules/videoio/src/cap_gstreamer.cpp
- GStreamer queue limits and leaky behavior: https://github.com/GStreamer/gstreamer/blob/main/subprojects/gstreamer/plugins/elements/gstqueue.c
- GStreamer live video with frame-level metadata: https://blog.dev-threads.de/posts/webrtc-with-gstreamer-and-metadata/
- Raspberry Pi 5 and React low-latency edge AI reference: https://reacts.dev/edge-ai-with-raspberry-pi-5-and-react-building-a-low-latency
