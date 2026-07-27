# go2rtc WebRTC Camera Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace both dashboard camera panels' MJPEG-first playback with go2rtc WebRTC `<video>` playback and a deterministic three-second MJPEG fallback.

**Architecture:** Keep URL derivation pure in `stream-urls.ts`. Put WebSocket signaling, peer lifecycle, timeout, and fallback state in one reusable `useGo2rtcVideo` hook. `CameraStage` owns the surface canvas overlay; `UnderwaterFallback` consumes the same player lifecycle and retains its existing latest-frame fallback when MJPEG fails.

**Tech Stack:** React 19, TypeScript, browser `RTCPeerConnection`, browser `WebSocket`, go2rtc v1.9.14 WebSocket signaling, Canvas 2D, Vitest, Testing Library.

---

## File map

- Modify `dashboard/src/lib/stream-urls.ts`: typed go2rtc source and URL derivation for `atas` and `bawah`.
- Modify `dashboard/src/lib/stream-urls.test.ts`: URL and scheme regression coverage.
- Create `dashboard/src/lib/use-go2rtc-video.ts`: reusable WebRTC signaling/player lifecycle.
- Create `dashboard/src/lib/use-go2rtc-video.test.ts`: deterministic WebSocket/RTCPeerConnection lifecycle tests.
- Modify `dashboard/src/components/camera-stage.tsx`: surface video, fallback image, and canvas sizing from video dimensions.
- Modify `dashboard/src/components/camera-stage.test.tsx`: video attributes, handshake, fallback, and overlay coverage.
- Modify `dashboard/src/components/underwater-fallback.tsx`: underwater player and existing frame fallback integration.
- Create `dashboard/src/components/underwater-fallback.test.tsx`: underwater WebRTC/MJPEG/frame behavior.
- Modify `dashboard/src/styles.css`: apply existing media sizing to `<video>`.

No backend, MAVLink, telemetry, RC, mission, or package dependency files change.

---

### Task 1: Add typed go2rtc URL derivation

**Files:**
- Modify: `dashboard/src/lib/stream-urls.ts`
- Test: `dashboard/src/lib/stream-urls.test.ts`

- [ ] **Step 1: Add failing URL assertions**

Extend `stream-urls.test.ts` with:

```ts
import { getGo2rtcUrls } from './stream-urls'

it('derives all go2rtc endpoints from a custom HTTPS bridge', () => {
  expect(getGo2rtcUrls(' https://bridge.example.test/ ', 'atas')).toEqual({
    webrtcWs: 'wss://bridge.example.test/api/ws?src=atas',
    webrtcHttp: 'https://bridge.example.test/api/webrtc?src=atas',
    mse: 'https://bridge.example.test/api/stream.mp4?src=atas',
    mjpeg: 'https://bridge.example.test/stream/atas',
  })
})

it('converts HTTP bridges to WS and encodes the source', () => {
  expect(getGo2rtcUrls('http://bridge.example.test/base/', 'bawah')).toEqual({
    webrtcWs: 'ws://bridge.example.test/base/api/ws?src=bawah',
    webrtcHttp: 'http://bridge.example.test/base/api/webrtc?src=bawah',
    mse: 'http://bridge.example.test/base/api/stream.mp4?src=bawah',
    mjpeg: 'http://bridge.example.test/base/stream/bawah',
  })
})
```

Use the existing `atas`/`bawah` source values so encoding remains observable without inventing arbitrary production source names.

- [ ] **Step 2: Run the focused URL test and confirm failure**

Run from `KKI2026`:

```bash
npm run test --workspace dashboard -- --pool=threads --maxWorkers=1 --fileParallelism=false src/lib/stream-urls.test.ts
```

Expected: FAIL because `getGo2rtcUrls` is not exported yet.

- [ ] **Step 3: Implement the pure helper**

Add these exported types and function to `stream-urls.ts`:

```ts
export type Go2rtcSource = 'atas' | 'bawah'

export type Go2rtcUrls = {
  webrtcWs: string
  webrtcHttp: string
  mse: string
  mjpeg: string
}

export function getGo2rtcUrls(
  bridgeUrl: string,
  source: Go2rtcSource,
): Go2rtcUrls {
  const baseUrl = bridgeUrl.trim().replace(/\/+$/, '')
  const parsed = new URL(baseUrl)
  const wsProtocol = parsed.protocol === 'https:' ? 'wss:' : 'ws:'
  const origin = parsed.origin.replace(/\/$/, '')
  const basePath = parsed.pathname.replace(/\/+$/, '')
  const prefix = `${origin}${basePath}`
  const encodedSource = encodeURIComponent(source)

  return {
    webrtcWs: `${wsProtocol}//${parsed.host}${basePath}/api/ws?src=${encodedSource}`,
    webrtcHttp: `${prefix}/api/webrtc?src=${encodedSource}`,
    mse: `${prefix}/api/stream.mp4?src=${encodedSource}`,
    mjpeg: `${prefix}/stream/${encodedSource}`,
  }
}
```

Export environment-derived defaults:

```ts
export const asvGo2rtcUrls = {
  surface: getGo2rtcUrls(asvBridgeUrl, 'atas'),
  underwater: getGo2rtcUrls(asvBridgeUrl, 'bawah'),
} as const
```

Use the already resolved `asvBridgeUrl`; do not duplicate the tunnel host. Preserve all existing raw stream and telemetry URL exports.

- [ ] **Step 4: Run the focused URL test and confirm pass**

Run the same command from Step 2. Expected: all URL tests pass.

- [ ] **Step 5: Commit the URL contract**

```bash
git add dashboard/src/lib/stream-urls.ts dashboard/src/lib/stream-urls.test.ts
git commit -m "feat(camera): add go2rtc stream URLs"
```

---

### Task 2: Implement the reusable go2rtc player lifecycle

**Files:**
- Create: `dashboard/src/lib/use-go2rtc-video.ts`
- Test: `dashboard/src/lib/use-go2rtc-video.test.ts`

- [ ] **Step 1: Write deterministic failing lifecycle tests**

Create test doubles for browser APIs and verify these contracts:

```ts
type FakePeer = {
  addTransceiver: ReturnType<typeof vi.fn>
  createOffer: ReturnType<typeof vi.fn>
  setLocalDescription: ReturnType<typeof vi.fn>
  setRemoteDescription: ReturnType<typeof vi.fn>
  addIceCandidate: ReturnType<typeof vi.fn>
  close: ReturnType<typeof vi.fn>
  ontrack: ((event: RTCTrackEvent) => void) | null
  onconnectionstatechange: (() => void) | null
  connectionState: RTCPeerConnectionState
}
```

Render a small harness that calls `useGo2rtcVideo({ urls, enabled: true })`, then assert:

- the initial media mode is `connecting` and a video ref is returned;
- `addTransceiver('video', { direction: 'recvonly' })` is called before the offer is sent;
- the WebSocket receives `JSON.stringify({ type: 'webrtc/offer', value: 'local-sdp' })`;
- a `webrtc/answer` message invokes `setRemoteDescription({ type: 'answer', sdp: 'remote-sdp' })`;
- a remote `track` attaches its stream to `video.srcObject` and changes mode to `webrtc`;
- a rejected WebSocket or missing `RTCPeerConnection` changes mode to `mjpeg` without waiting;
- advancing fake timers by 3000 ms changes mode to `mjpeg`, and subsequent late messages do not attach a stream;
- unmount calls `clearTimeout`, `WebSocket.close()`, and `RTCPeerConnection.close()`.

- [ ] **Step 2: Run the lifecycle tests and confirm failure**

```bash
npm run test --workspace dashboard -- --pool=threads --maxWorkers=1 --fileParallelism=false src/lib/use-go2rtc-video.test.ts
```

Expected: FAIL because the hook does not exist.

- [ ] **Step 3: Implement the hook with a strict three-second budget**

Use this public interface:

```ts
export type Go2rtcPlaybackMode = 'connecting' | 'webrtc' | 'mjpeg'

export type UseGo2rtcVideoOptions = {
  urls: Go2rtcUrls
  enabled: boolean
}

export type UseGo2rtcVideoResult = {
  videoRef: RefObject<HTMLVideoElement | null>
  mode: Go2rtcPlaybackMode
  mjpegFailed: boolean
  onMjpegError: () => void
}
```

Implementation requirements:

1. Initialize mode to `connecting` only when `enabled`; otherwise initialize/return `mjpeg` without opening browser resources.
2. In `useEffect`, immediately call `fallback()` when `WebSocket` or `RTCPeerConnection` is unavailable. This makes jsdom and unsupported browsers deterministic.
3. Create the peer and call `addTransceiver('video', { direction: 'recvonly' })` before `createOffer()`.
4. Open `new WebSocket(urls.webrtcWs)`. On open, create/set the local offer and send the go2rtc JSON `webrtc/offer` message. Use `onicecandidate` to send non-empty local candidates as `webrtc/candidate` messages when the socket is open.
5. On incoming JSON:
   - `webrtc/answer`: `setRemoteDescription({ type: 'answer', sdp: message.value })`;
   - non-empty `webrtc/candidate`: `addIceCandidate({ candidate: message.value })`;
   - ignore malformed/unknown messages without throwing out of the event handler.
6. On `ontrack`, attach `event.streams[0]` (or a `MediaStream` containing the track when available), call `video.play()` without making autoplay rejection fatal, then mark mode `webrtc`.
7. Set a three-second timer at connection start. `fallback()` must be idempotent, mark the lifecycle stopped, clear the timer, detach handlers, close the WebSocket and peer, clear any `srcObject`, and set mode `mjpeg`.
8. Fallback on WebSocket error/close and peer `failed`/`closed` state. Do not allow late async offer/answer work to change state after fallback.
9. The effect cleanup runs the same resource closure and never leaves a timeout, peer, or socket alive. Reset `mjpegFailed` when `urls` or `enabled` changes.

- [ ] **Step 4: Run the lifecycle tests and confirm pass**

Run the command from Step 2. Expected: all hook lifecycle tests pass.

- [ ] **Step 5: Commit the player lifecycle**

```bash
git add dashboard/src/lib/use-go2rtc-video.ts dashboard/src/lib/use-go2rtc-video.test.ts
git commit -m "feat(camera): add go2rtc WebRTC player lifecycle"
```

---

### Task 3: Cut over the surface camera and preserve YOLO overlay

**Files:**
- Modify: `dashboard/src/components/camera-stage.tsx`
- Modify: `dashboard/src/components/camera-stage.test.tsx`
- Modify: `dashboard/src/styles.css`

- [ ] **Step 1: Update failing CameraStage tests**

Replace raw image assumptions with these observable contracts:

```ts
const video = screen.getByRole('video', { name: 'Live surface camera' })
expect(video).toHaveAttribute('autoplay')
expect(video).toHaveAttribute('playsinline')
expect(video).toHaveProperty('muted', true)
expect(canvas?.parentElement?.firstElementChild).toBe(video)
```

Add a fallback test that renders the player with a fake peer whose connection never tracks, advances timers by 3000 ms, and asserts:

```ts
expect(screen.getByRole('img', { name: 'Live surface camera' })).toHaveAttribute(
  'src',
  'https://camera.example.test/surface',
)
expect(screen.queryByRole('video', { name: 'Live surface camera' })).not.toBeInTheDocument()
```

Add an overlay test that sets `video.videoWidth = 1280`, `video.videoHeight = 720`, invokes the stored animation callback, and asserts the existing `strokeRect(320, 255, 160, 90)` result.

- [ ] **Step 2: Run CameraStage tests and confirm failure**

```bash
npm run test --workspace dashboard -- --pool=threads --maxWorkers=1 --fileParallelism=false src/components/camera-stage.test.tsx
```

Expected: FAIL because CameraStage still renders `<img>` as its primary element.

- [ ] **Step 3: Integrate the hook and change the media element**

Import `asvGo2rtcUrls` and `useGo2rtcVideo`. Call:

```ts
const player = useGo2rtcVideo({
  urls: asvGo2rtcUrls.surface,
  enabled: Boolean(streamUrl),
})
```

Render `<video ref={player.videoRef} className="camera-stage__stream" autoPlay playsInline muted aria-label="Live surface camera" />` while `player.mode !== 'mjpeg'`; render the legacy `<img>` with `src={streamUrl ?? asvGo2rtcUrls.surface.mjpeg}` once the player enters MJPEG mode. Keep the canvas as the second child in `.camera-stage__media`, and render the existing placeholder only when there is no configured stream or the legacy image has failed.

Change the animation draw source from `HTMLImageElement` to `HTMLVideoElement`. Use:

```ts
const sourceWidth = video.videoWidth || cache.payload.source_width
const sourceHeight = video.videoHeight || cache.payload.source_height
```

Keep the existing letterbox calculation, metadata freshness check, canvas clearing, and text/box projection unchanged.

- [ ] **Step 4: Extend CSS without changing layout**

Change the media selector to include `video`:

```css
.camera-stage__stream,
.underwater-fallback__stream,
.underwater-fallback__frame img {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  object-fit: contain;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: #050b0e;
}
```

No overlay geometry or pointer-event rule changes.

- [ ] **Step 5: Run CameraStage tests and confirm pass**

Run the command from Step 2. Expected: all surface camera tests pass.

- [ ] **Step 6: Commit the surface cutover**

```bash
git add dashboard/src/components/camera-stage.tsx dashboard/src/components/camera-stage.test.tsx dashboard/src/styles.css
git commit -m "feat(camera): play surface feed through WebRTC"
```

---

### Task 4: Cut over underwater playback while preserving frame fallback

**Files:**
- Modify: `dashboard/src/components/underwater-fallback.tsx`
- Create: `dashboard/src/components/underwater-fallback.test.tsx`

- [ ] **Step 1: Write failing underwater behavior tests**

Render `UnderwaterFallback` with a configured stream and fake healthy WebRTC player; assert a muted autoplay inline `<video>` with accessible name `Live underwater action camera` and no raw image initially. Advance the fake three-second timer and assert the MJPEG `<img>` uses the configured underwater stream URL. Trigger that image's `error` event and assert the existing `Latest underwater frame` image and frame id/time remain visible.

- [ ] **Step 2: Run the underwater test and confirm failure**

```bash
npm run test --workspace dashboard -- --pool=threads --maxWorkers=1 --fileParallelism=false src/components/underwater-fallback.test.tsx
```

Expected: FAIL because UnderwaterFallback still renders `<img>` immediately and has no player lifecycle test.

- [ ] **Step 3: Integrate the shared player**

Call:

```ts
const player = useGo2rtcVideo({
  urls: asvGo2rtcUrls.underwater,
  enabled: Boolean(streamUrl),
})
```

Render the same video attributes/class while `player.mode !== 'mjpeg'`. Render the existing MJPEG `<img>` with `src={streamUrl ?? asvGo2rtcUrls.underwater.mjpeg}` while in MJPEG mode, wiring `onError={player.onMjpegError}`. When `player.mjpegFailed` is true, use the existing `frame` branch; if no frame exists, retain the existing offline status block. Reset player/image state when `streamUrl` changes through the hook's dependency lifecycle.

- [ ] **Step 4: Run the underwater test and confirm pass**

Run the command from Step 2. Expected: all underwater playback and frame fallback tests pass.

- [ ] **Step 5: Commit the underwater cutover**

```bash
git add dashboard/src/components/underwater-fallback.tsx dashboard/src/components/underwater-fallback.test.tsx
git commit -m "feat(camera): play underwater feed through WebRTC"
```

---

### Task 5: Run the complete regression suite

**Files:**
- Test: all dashboard tests and typecheck/build outputs
- Inspect: `dashboard/src/components/dashboard-shell.tsx`, telemetry and manual-control source files

- [ ] **Step 1: Run focused camera and URL tests together**

```bash
npm run test --workspace dashboard -- --pool=threads --maxWorkers=1 --fileParallelism=false src/lib/stream-urls.test.ts src/lib/use-go2rtc-video.test.ts src/components/camera-stage.test.tsx src/components/underwater-fallback.test.tsx
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the entire dashboard test suite**

```bash
npm run test --workspace dashboard -- --pool=threads --maxWorkers=1 --fileParallelism=false
```

Expected: every existing and new test passes; no telemetry, mission, or RC test fails.

- [ ] **Step 3: Run typecheck and production build**

```bash
npm run typecheck --workspace dashboard && npm run build --workspace dashboard
```

Expected: TypeScript emits no diagnostics and Vite/Nitro produces a production bundle.

- [ ] **Step 4: Inspect the final diff for scope**

```bash
git diff --name-only HEAD~4..HEAD
```

Expected changed runtime files are limited to stream URL helpers, the shared player, the two camera components, their tests, and camera media CSS; no backend, telemetry, or manual RC files appear.

- [ ] **Step 5: Commit verification evidence if any test-only adjustment remains**

If Steps 1–4 require a test correction, run the affected focused test again, then commit only that correction:

```bash
git add dashboard/src
git commit -m "test(camera): stabilize go2rtc playback coverage"
```

Do not add dependencies or modify backend/control paths for test convenience.
