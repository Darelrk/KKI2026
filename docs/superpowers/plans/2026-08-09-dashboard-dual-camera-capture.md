# Dashboard Dual-Camera Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the surface center line, relabel heading as COG, and let one operator button download one combined surface/underwater JPEG with a capture flash.

**Architecture:** Small Canvas helpers capture native camera media, rotate underwater output, combine the two canvases, and trigger one download. `CameraStage` and `UnderwaterFallback` expose the current frame through refs; `DashboardShell` owns the single button, state, animation trigger, all-or-nothing orchestration, and accessible result message.

**Tech Stack:** React 19, TypeScript 6, native Canvas/DOM download APIs, Vitest, Testing Library, existing CSS.

---

### Task 1: Remove the center line and relabel telemetry

**Files:**
- Modify: `dashboard/src/components/camera-stage.tsx`
- Modify: `dashboard/src/components/camera-stage.test.tsx`
- Modify: `dashboard/src/components/telemetry-panel.tsx`
- Modify: `dashboard/src/components/dashboard-shell.test.tsx`

- [ ] **Step 1: Change tests to require no center line and a COG label**

In `camera-stage.test.tsx`, replace the center-line assertions with:

```tsx
expect(canvasContext.beginPath).not.toHaveBeenCalled()
expect(canvasContext.moveTo).not.toHaveBeenCalled()
expect(canvasContext.lineTo).not.toHaveBeenCalled()
expect(canvasContext.stroke).not.toHaveBeenCalled()
expect(canvasContext.strokeRect).toHaveBeenCalledWith(320, 255, 160, 90)
```

For stale metadata, assert that neither line nor boxes are drawn:

```tsx
expect(canvasContext.moveTo).not.toHaveBeenCalled()
expect(canvasContext.lineTo).not.toHaveBeenCalled()
expect(canvasContext.strokeRect).not.toHaveBeenCalled()
```

In the live telemetry test in `dashboard-shell.test.tsx`, add:

```tsx
expect(screen.getByText('COG')).toBeInTheDocument()
expect(screen.queryByText('Heading')).not.toBeInTheDocument()
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
npx vitest run src/components/camera-stage.test.tsx src/components/dashboard-shell.test.tsx
```

Expected: center-line assertions and `COG` assertion fail against `2173ed7`.

- [ ] **Step 3: Remove the center-line drawing and rename the label**

Delete the fixed-center block from `CameraStage`:

```tsx
const centerX = (sourceRect.x + sourceRect.width / 2) * dpr
context.strokeStyle = '#2f80ed'
context.lineWidth = 2 * dpr
context.beginPath()
context.moveTo(centerX, sourceRect.y * dpr)
context.lineTo(centerX, (sourceRect.y + sourceRect.height) * dpr)
context.stroke()
```

Change the telemetry `<dt>` text only:

```tsx
<Compass aria-hidden="true" size={14} />
COG
```

Keep `telemetry.heading_deg` unchanged so the backend contract is untouched.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: both files pass.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/camera-stage.tsx dashboard/src/components/camera-stage.test.tsx dashboard/src/components/telemetry-panel.tsx dashboard/src/components/dashboard-shell.test.tsx
git commit -m "fix(dashboard): remove surface center line"
```

### Task 2: Add native frame capture and composition helpers

**Files:**
- Create: `dashboard/src/lib/camera-capture.ts`
- Create: `dashboard/src/lib/camera-capture.test.ts`

- [ ] **Step 1: Write failing helper tests**

Cover these observable contracts:

```tsx
it('captures a ready media frame at native dimensions', () => {
  const media = document.createElement('video')
  Object.defineProperties(media, {
    videoWidth: { value: 1280 },
    videoHeight: { value: 720 },
  })
  const canvas = captureMediaFrame(media)
  expect(canvas.width).toBe(1280)
  expect(canvas.height).toBe(720)
  expect(context.drawImage).toHaveBeenCalledWith(media, 0, 0, 1280, 720)
})

it('rotates an underwater frame by 180 degrees', () => {
  const media = document.createElement('img')
  Object.defineProperties(media, {
    naturalWidth: { value: 640 },
    naturalHeight: { value: 360 },
  })
  captureMediaFrame(media, { rotate180: true })
  expect(context.translate).toHaveBeenCalledWith(640, 360)
  expect(context.rotate).toHaveBeenCalledWith(Math.PI)
})

it('combines both cameras and downloads one timestamped jpeg', () => {
  const combined = combineCameraFrames(surfaceCanvas, underwaterCanvas)
  downloadCameraCapture(combined, new Date('2026-08-09T12:34:56Z'))
  expect(anchor.download).toBe('asv-capture-20260809-123456.jpg')
  expect(anchor.click).toHaveBeenCalledOnce()
})

it('rejects media without a decoded frame', () => {
  expect(() => captureMediaFrame(document.createElement('video'))).toThrow(
    'Camera frame is not ready',
  )
})
```

- [ ] **Step 2: Run the helper test and verify RED**

```bash
npx vitest run src/lib/camera-capture.test.ts
```

Expected: module import fails because `camera-capture.ts` does not exist.

- [ ] **Step 3: Implement the minimal native helper**

Create `camera-capture.ts` with these public contracts:

```tsx
export type CameraCaptureHandle = {
  captureFrame: () => HTMLCanvasElement
}

export function captureMediaFrame(
  media: HTMLVideoElement | HTMLImageElement,
  { rotate180 = false }: { rotate180?: boolean } = {},
): HTMLCanvasElement

export function combineCameraFrames(
  surface: HTMLCanvasElement,
  underwater: HTMLCanvasElement,
): HTMLCanvasElement

export function downloadCameraCapture(
  canvas: HTMLCanvasElement,
  capturedAt = new Date(),
): string
```

`captureMediaFrame` must read `videoWidth/videoHeight` or `naturalWidth/naturalHeight`, reject zero dimensions, draw a black background, and rotate around the full canvas only for underwater. `combineCameraFrames` must preserve each aspect ratio, use one shared height capped at 1080 pixels, and place surface left/underwater right. `downloadCameraCapture` must call `canvas.toDataURL('image/jpeg', 0.92)`, click one temporary anchor, and return the filename for UI status.

- [ ] **Step 4: Run helper tests and verify GREEN**

Run the Step 2 command. Expected: all helper contracts pass.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/lib/camera-capture.ts dashboard/src/lib/camera-capture.test.ts
git commit -m "feat(dashboard): compose dual-camera captures"
```

### Task 3: Expose surface and underwater frame capture

**Files:**
- Modify: `dashboard/src/components/camera-stage.tsx`
- Modify: `dashboard/src/components/camera-stage.test.tsx`
- Modify: `dashboard/src/components/underwater-fallback.tsx`
- Modify: `dashboard/src/components/underwater-fallback.test.tsx`

- [ ] **Step 1: Write failing component-handle tests**

Add refs in each test:

```tsx
const captureRef = createRef<CameraCaptureHandle>()
render(<CameraStage ref={captureRef} streamUrl="https://camera.example.test/surface" />)
const frame = captureRef.current?.captureFrame()
expect(frame).toBeInstanceOf(HTMLCanvasElement)
expect(canvasContext.strokeRect).toHaveBeenCalled()
```

For underwater:

```tsx
const captureRef = createRef<CameraCaptureHandle>()
render(<UnderwaterFallback ref={captureRef} frame={frame} streamUrl={null} />)
const image = screen.getByRole('img', { name: 'Latest underwater frame' })
Object.defineProperties(image, {
  naturalWidth: { value: 640 },
  naturalHeight: { value: 360 },
})
captureRef.current?.captureFrame()
expect(canvasContext.rotate).toHaveBeenCalledWith(Math.PI)
```

- [ ] **Step 2: Run focused tests and verify RED**

```bash
npx vitest run src/components/camera-stage.test.tsx src/components/underwater-fallback.test.tsx
```

Expected: component refs do not expose `captureFrame`.

- [ ] **Step 3: Add capture handles**

Convert both components with `forwardRef<CameraCaptureHandle, Props>` and `useImperativeHandle`.

Surface behavior:

```tsx
const media = player.mode === 'mjpeg' ? imageRef.current : player.videoRef.current
if (!media) throw new Error('Surface camera frame is not ready')
const canvas = captureMediaFrame(media)
// Draw only fresh detection boxes/labels across the full native source rect.
return canvas
```

Extract the existing detection-box drawing into one local `drawVisionDetections` function so the live overlay and capture use identical normalized coordinates. Do not restore the blue center line.

Underwater behavior:

```tsx
const media = player.mode === 'mjpeg' ? imageRef.current : player.videoRef.current
if (!media) throw new Error('Underwater camera frame is not ready')
return captureMediaFrame(media, { rotate180: true })
```

Attach one `imageRef` to both the raw MJPEG and base64 fallback `<img>` alternatives.

Add an optional `capturing?: boolean` prop to both sections and conditionally append `camera-capture--active` for the shared flash state.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: both component test files pass.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/camera-stage.tsx dashboard/src/components/camera-stage.test.tsx dashboard/src/components/underwater-fallback.tsx dashboard/src/components/underwater-fallback.test.tsx
git commit -m "feat(dashboard): expose camera capture frames"
```

### Task 4: Add the shared capture button, animation, and failure state

**Files:**
- Modify: `dashboard/src/components/dashboard-shell.tsx`
- Modify: `dashboard/src/components/dashboard-shell.test.tsx`
- Modify: `dashboard/src/styles.css`

- [ ] **Step 1: Write failing orchestration tests**

Mock or inject the two capture handles, click one button, and assert:

```tsx
fireEvent.click(screen.getByRole('button', { name: 'Capture both cameras' }))
await waitFor(() => {
  expect(screen.getByRole('status')).toHaveTextContent('Capture saved')
})
expect(downloadCameraCapture).toHaveBeenCalledOnce()
expect(screen.getByRole('button', { name: 'Capture both cameras' })).toBeEnabled()
```

Add the failure contract:

```tsx
surfaceCapture.mockImplementation(() => {
  throw new Error('Surface camera frame is not ready')
})
fireEvent.click(screen.getByRole('button', { name: 'Capture both cameras' }))
await waitFor(() => {
  expect(screen.getByRole('alert')).toHaveTextContent(
    'Capture failed. Verify both camera feeds.',
  )
})
expect(downloadCameraCapture).not.toHaveBeenCalled()
```

Also assert both camera sections receive `camera-capture--active` while the promise is pending.

- [ ] **Step 2: Run the dashboard shell test and verify RED**

```bash
npx vitest run src/components/dashboard-shell.test.tsx
```

Expected: the shared capture button and capture states do not exist.

- [ ] **Step 3: Implement orchestration and UI**

In `DashboardShell`:

```tsx
const surfaceCaptureRef = useRef<CameraCaptureHandle>(null)
const underwaterCaptureRef = useRef<CameraCaptureHandle>(null)
const [captureState, setCaptureState] = useState<'idle' | 'capturing' | 'saved' | 'error'>('idle')

const captureBoth = async () => {
  setCaptureState('capturing')
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  try {
    const surface = surfaceCaptureRef.current?.captureFrame()
    const underwater = underwaterCaptureRef.current?.captureFrame()
    if (!surface || !underwater) throw new Error('Camera frame is not ready')
    downloadCameraCapture(combineCameraFrames(surface, underwater))
    setCaptureState('saved')
  } catch {
    setCaptureState('error')
  }
}
```

Place one `grid-column: 1 / -1` toolbar before the camera panels. Use one native `<button type="button">` with a camera icon, disable only during `capturing`, and expose a polite success status or assertive error message. Pass the refs and capturing state to both camera components.

Add CSS:

```css
.camera-capture-toolbar {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.65rem;
}

.camera-capture--active .camera-stage__stream,
.camera-capture--active .underwater-fallback__stream,
.camera-capture--active .underwater-fallback__frame img {
  animation: camera-capture-flash 320ms ease-out;
}

@keyframes camera-capture-flash {
  0%, 100% { filter: none; }
  45% { filter: brightness(2); }
}
```

Reuse the existing compact button visual tokens; do not add a dependency or modal.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: capture success, failure, all-or-nothing, and COG tests pass.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/dashboard-shell.tsx dashboard/src/components/dashboard-shell.test.tsx dashboard/src/styles.css
git commit -m "feat(dashboard): add paired camera capture"
```

### Task 5: Verify the complete dashboard behavior

**Files:**
- Verify all files changed in Tasks 1–4.

- [ ] **Step 1: Run focused camera and telemetry regressions**

```bash
npx vitest run src/lib/camera-capture.test.ts src/components/camera-stage.test.tsx src/components/underwater-fallback.test.tsx src/components/dashboard-shell.test.tsx
```

Expected: all focused tests pass with zero failures.

- [ ] **Step 2: Run the full dashboard verification**

```bash
npx vitest run --pool=threads --maxWorkers=1
npx tsc --noEmit
npm run build
```

Expected: 25+ test files pass, TypeScript exits 0, and Vite/Nitro production build exits 0.

- [ ] **Step 3: Smoke-test in a browser**

Start the dashboard with the production-like direct configuration, open it in Chromium, and verify:

```text
- No blue center line appears over the surface feed.
- Detection boxes remain visible when fresh metadata exists.
- Telemetry label reads COG.
- One Capture both cameras button appears above both feeds.
- Clicking it flashes both feeds and downloads exactly one combined JPEG.
- The downloaded image has surface left with detections and underwater right, rotated 180°.
```

- [ ] **Step 4: Inspect final worktree state**

```bash
git status -sb
git log --oneline origin/main..HEAD
```

Expected: only intended commits are ahead of `origin/main`; no generated capture or build output is tracked.
