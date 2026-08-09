# Dashboard Dual-Camera Capture Design

**Date:** 2026-08-09  
**Target:** `dashboard/` on top of `origin/main` commit `2173ed7`

## Goal

Update the competition dashboard so the surface feed no longer shows the blue center line, the frontend labels `heading_deg` as COG, and one operator action downloads a paired surface/underwater capture.

## Approved behavior

- Remove only the blue surface-camera center line. Detection boxes and labels remain.
- Replace the visible `Heading` label with `COG` (`Course Over Ground`). The frontend continues consuming the existing `heading_deg` field; the backend wire contract does not change.
- Add one **Capture both cameras** button above the two camera panels.
- One click captures both feeds at the same moment and downloads one timestamped JPEG: `asv-capture-YYYYMMDD-HHMMSS.jpg`.
- The surface half includes fresh detection boxes and labels. The underwater half is rotated 180 degrees to match the operator view.
- Both camera panels flash briefly while the capture is taken. The button reports `Capturing…`, then success or failure.
- Capture is all-or-nothing. If either feed is unavailable or browser canvas access is blocked, no partial file is downloaded.

## Approach

Use browser Canvas APIs. Each camera component exposes its current drawable media to the dashboard capture coordinator. The coordinator snapshots the two sources, composites the surface detection overlay, applies the underwater rotation, combines both frames side by side, encodes one JPEG, and triggers one browser download.

This approach adds no dependency, changes no Raspberry Pi endpoint, and stores no image on the Raspberry Pi. A DOM-screenshot dependency would capture unwanted panel UI and retain cross-origin limitations. A backend snapshot endpoint would expand the control surface without helping the requested operator-side download.

## Data flow

1. Operator presses **Capture both cameras**.
2. Dashboard enters the capturing state and starts the flash animation on both panels.
3. Surface camera returns its active video/image frame plus the current fresh detection overlay.
4. Underwater camera returns its active video/image/base64 fallback frame in displayed orientation.
5. The dashboard composes both frames side by side on one bounded canvas.
6. Canvas encodes a JPEG and the browser downloads it with a shared timestamp.
7. Dashboard reports success. Any failure clears the capturing state and reports one concise error without downloading a partial image.

## Stream constraints

- WebRTC video is the primary capture source.
- The existing base64 underwater fallback is capturable.
- A cross-origin MJPEG fallback is capturable only when the browser permits drawing it to Canvas. A tainted Canvas or unready media produces the normal all-or-nothing failure state.
- Stream playback and backend telemetry contracts remain unchanged.

## UI

- The shared capture toolbar spans the camera grid above both panels.
- The button is disabled only while a capture is in progress.
- A short visual flash affects the camera media areas, not the whole dashboard.
- Success and failure status is announced with an accessible live region.
- Existing responsive camera layout remains unchanged below the toolbar.

## Testing

- Surface capture contains fresh detection boxes but no center line.
- Underwater capture applies the existing 180-degree orientation.
- One button invocation requests both frames and produces one timestamped JPEG download.
- Either camera failure prevents a partial download and exposes an accessible error.
- Button and flash states transition correctly.
- Telemetry renders `COG` and no longer renders `Heading`.
- Existing camera playback, telemetry, fixture isolation, typecheck, production build, and browser smoke behavior remain valid.

## Non-goals

- No Raspberry Pi file storage or gallery.
- No new backend capture endpoint.
- No telemetry schema rename.
- No synthetic camera frame fallback.
- No removal of model detection boxes.
