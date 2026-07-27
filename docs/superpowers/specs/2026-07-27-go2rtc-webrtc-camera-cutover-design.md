# go2rtc WebRTC Camera Cutover Design

**Date:** 2026-07-27
**Status:** Approved for implementation

## Goal

Replace the dashboard's surface-camera MJPEG-first playback with native go2rtc WebRTC playback in a `<video>` element, while keeping MJPEG as an automatic legacy fallback after a three-second connection budget. The URL helper also exposes the prepared `bawah` endpoints without changing the underwater component.

## Scope and invariants

- The surface `CameraStage` uses the WebRTC lifecycle for source `atas`; the underwater component remains on its existing path.
- WebRTC signaling uses go2rtc's public WebSocket API:
  - connect to `/api/ws?src=<source>`;
  - send `{ "type": "webrtc/offer", "value": "<sdp>" }`;
  - apply `{ "type": "webrtc/answer", "value": "<sdp>" }`;
  - accept/send `{ "type": "webrtc/candidate", "value": "<candidate>" }` when present.
- The peer connection adds a video receive-only transceiver before creating the offer.
- The `<video>` element always includes `autoPlay`, `playsInline`, and `muted`.
- If WebRTC does not reach a usable media track within three seconds, the component closes the active resources and renders the configured MJPEG URL in `<img>`.
- A custom raw stream URL remains the legacy fallback when supplied; otherwise the helper-generated `/stream/atas` or `/stream/bawah` URL is used.
- MSE URL generation is exposed by the URL helper for go2rtc-compatible callers, but MSE is not inserted as an unrequested intermediate fallback in this cutover.
- Surface YOLO metadata continues to render on the transparent canvas above the video. Source dimensions use `videoWidth`/`videoHeight`, falling back to metadata dimensions when unavailable.
- No underwater component, telemetry, MAVLink, Pixhawk, mission, RC override, steering, throttle, arming, or disarming code changes.

## URL contract

`stream-urls.ts` will define a source type (`atas` or `bawah`) and a `getGo2rtcUrls(bridgeUrl, source)` helper. It normalizes the bridge URL once and derives:

- WebRTC WebSocket URL (`http` → `ws`, `https` → `wss`): `/api/ws?src=<encoded source>`;
- WebRTC HTTP URL: `/api/webrtc?src=<encoded source>`;
- MSE URL: `/api/stream.mp4?src=<encoded source>`;
- legacy MJPEG URL: `/stream/<encoded source>`.

`CameraStage` consumes the resolved bridge-derived `atas` endpoints and the existing configured surface stream URL. The helper also exposes `bawah` for the registered second source without changing current consumers. This preserves custom deployment overrides without hardcoding a second host.

## Playback lifecycle

A `CameraStage` playback effect owns the browser resources and tracks the current transport (`connecting`, `webrtc`, or `mjpeg`). On mount or source change it:

1. creates `RTCPeerConnection` and `addTransceiver('video', { direction: 'recvonly' })`;
2. opens the go2rtc WebSocket for `src=atas`;
3. waits for local ICE gathering sufficiently for the offer, sends the JSON offer, and applies answer/candidate messages;
4. attaches the received `MediaStream` to `video.srcObject` and calls `play()` opportunistically;
5. marks WebRTC ready only after a remote media track/usable connection;
6. falls back exactly once after an error, close, failed state, or three-second timeout.

Every exit path clears the timeout, removes handlers, closes the WebSocket, and closes the peer connection. Late signaling messages cannot revive a fallback instance. A stream change creates a fresh lifecycle.

## Component integration

- `CameraStage` receives source `atas`, renders the shared video or MJPEG fallback, and keeps its existing canvas wrapper and metadata status bar.
- `UnderwaterFallback` is unchanged.
- The existing camera media CSS is extended to apply equally to `video` and `img`; the overlay remains absolute, full-size, and pointer-transparent.

## Testing

- URL tests cover default and custom bridge URLs, both sources, websocket scheme conversion, URL encoding, and custom legacy stream URLs.
- `CameraStage` tests stub WebSocket and RTCPeerConnection to verify transceiver direction, offer/answer flow, required video attributes, track attachment, cleanup, three-second fallback, and stream changes.
- Camera overlay tests verify canvas remains the sibling above the video, uses video dimensions when available, and preserves normalized bounding-box placement.
- Existing dashboard tests, typecheck, and production build must pass. No underwater, telemetry, or manual RC test behavior is changed.

## Acceptance criteria

1. The surface camera panel renders `<video>` during a healthy WebRTC session.
2. A failed or stalled WebRTC session renders the correct legacy MJPEG stream within three seconds.
3. Canvas detection boxes remain aligned with the displayed surface video.
4. Unmount and stream changes leave no active peer connection, WebSocket, or timeout.
5. Existing dashboard tests and build pass, with no underwater, telemetry, or RC-control regression.
