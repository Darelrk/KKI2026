# Manual RC Dashboard Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dashboard show an honest manual-RC/model-monitoring state and draw a continuous boat path through every ordered GPS point, including the newest position.

**Architecture:** Keep the existing metadata WebSocket, telemetry broadcast, schemas, and dashboard composition. Make the path continuity correction inside `NavigationMap`, and make the control-source copy explicit inside `SignalRail`; no backend, model, Pixhawk, RC, or API changes are included.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, existing SVG/CSS dashboard components.

---

## Files and responsibilities

- Modify `dashboard/src/components/navigation-map.tsx`: derive one ordered path list from `telemetry.track` plus a non-duplicate current position, then project that list for the SVG polyline and bounds.
- Modify `dashboard/src/components/signal-rail.tsx`: label the model as monitoring and expose `RC MANUAL` as the fixed control source.
- Modify `dashboard/src/components/navigation-map.test.tsx`: defend that a current position not yet present in `track` is appended to the rendered polyline.
- Create `dashboard/src/components/signal-rail.test.tsx`: defend the monitoring/control-source status copy.
- Modify `dashboard/src/components/dashboard-client.test.tsx`: update the fixture dashboard contract to include the new status copy.

Out of scope: `vision_test.py`, `vision_route.py`, `asv_dashboard_backend/**`, Supabase schema/API, Pixhawk/MAVLink, RC override, model inference, and raw camera transport.

### Task 1: Lock path continuity with a failing frontend test

**Files:**
- Test: `dashboard/src/components/navigation-map.test.tsx`

- [x] **Step 1: Add a regression test with a new current position**

Add a case to `describe('NavigationMap', ...)` using two historical track points and a different current position:

```tsx
it('connects the current position to the end of the GPS path', () => {
  render(
    <NavigationMap
      telemetry={{
        ...emptyNavigationTelemetry,
        position: {
          latitude: -2,
          longitude: 102,
          captured_at: '2026-07-20T09:32:00.000Z',
        },
        track: [
          { latitude: -1, longitude: 100, captured_at: '2026-07-20T09:30:00.000Z' },
          { latitude: -2, longitude: 101, captured_at: '2026-07-20T09:31:00.000Z' },
        ],
      }}
    />,
  )

  const polyline = screen
    .getByRole('img', { name: 'GPS track plot' })
    .querySelector('polyline')

  expect(polyline).not.toBeNull()
  expect(polyline?.getAttribute('points')?.trim().split(/\s+/)).toHaveLength(3)
})
```

- [x] **Step 2: Run only the map test and confirm the regression fails**

Run from `D:\KKI2\KKI2026\dashboard`:

```powershell
npm run test -- --run src/components/navigation-map.test.tsx
```

Expected before implementation: the new test fails because the existing `trackPoints` maps only `telemetry.track` and omits a different current `position`.

### Task 2: Implement the minimal continuous path derivation

**Files:**
- Modify: `dashboard/src/components/navigation-map.tsx`

- [x] **Step 1: Derive one ordered path list and deduplicate the current endpoint**

Replace the separate `projectionPoints`/`trackPoints` source with this logic immediately after `boatPosition` is derived:

```tsx
const currentIsAlreadyLastPoint =
  boatPosition !== null &&
  lastTrackPoint !== undefined &&
  boatPosition.latitude === lastTrackPoint.latitude &&
  boatPosition.longitude === lastTrackPoint.longitude
const pathPoints =
  boatPosition && !currentIsAlreadyLastPoint
    ? [...telemetry.track, boatPosition]
    : telemetry.track
const projectionPoints = pathPoints
```

Use `pathPoints` for both `trackPoints` and the `hasTrackPlot` threshold. Keep the existing `projectPoint`, marker, heading rotation, empty state, and readout behavior unchanged. Do not interpolate or invent GPS points.

- [x] **Step 2: Run the focused map tests**

```powershell
npm run test -- --run src/components/navigation-map.test.tsx
```

Expected: all map tests pass, including the new three-point continuity assertion and the existing one-point/no-fix behavior.

### Task 3: Make manual control explicit in the status rail

**Files:**
- Test: `dashboard/src/components/signal-rail.test.tsx`
- Modify: `dashboard/src/components/signal-rail.tsx`
- Modify: `dashboard/src/components/dashboard-client.test.tsx`

- [x] **Step 1: Add a focused SignalRail test before changing the component**

Create `signal-rail.test.tsx` with a minimal live payload and assert the monitoring/control-source copy:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { SignalRail } from './signal-rail'

const live = {
  id: 'default',
  online: true,
  model_status: 'running' as const,
  camera: 'surface' as const,
  stream_url: null,
  run_id: 'run-1',
  updated_at: '2026-07-23T10:00:00.000Z',
}

describe('SignalRail', () => {
  it('identifies model monitoring and manual RC control', () => {
    render(
      <SignalRail
        live={live}
        telemetryConnected={true}
        telemetryStatus="connected"
      />,
    )

    expect(screen.getByText('MODEL MONITORING')).toBeInTheDocument()
    expect(screen.getByText('MODEL RUNNING')).toBeInTheDocument()
    expect(screen.getByText('Control source')).toBeInTheDocument()
    expect(screen.getByText('RC MANUAL')).toBeInTheDocument()
  })
})
```

- [x] **Step 2: Run the focused SignalRail test and confirm the new copy fails**

```powershell
npm run test -- --run src/components/signal-rail.test.tsx
```

Expected before implementation: the test fails because the existing component says `Autonomy model` and does not render a control-source row.

- [x] **Step 3: Update only the status copy and fixed control-source row**

In `signal-rail.tsx`:

1. Change the eyebrow text from `Autonomy model` to `MODEL MONITORING`.
2. Keep the dynamic `MODEL ${modelStatus.toUpperCase()}` value so offline/error states remain truthful.
3. Add this item to the existing `signal-list`:

```tsx
<div>
  <dt>Control source</dt>
  <dd>RC MANUAL</dd>
</div>
```

Do not add buttons, commands, mode selectors, or Pixhawk writes.

- [x] **Step 4: Update the fixture dashboard assertion**

In `dashboard-client.test.tsx`, keep the existing `MODEL RUNNING` assertion and add:

```tsx
expect(screen.getByText('MODEL MONITORING')).toBeInTheDocument()
expect(screen.getByText('RC MANUAL')).toBeInTheDocument()
```

- [x] **Step 5: Run focused status tests**

```powershell
npm run test -- --run src/components/signal-rail.test.tsx src/components/dashboard-client.test.tsx
```

Expected: all focused status tests pass.

### Task 4: Run frontend verification

**Files:**
- No additional files.

- [x] **Step 1: Run the full frontend test suite**

```powershell
npm run test -- --run
```

Expected: all Vitest tests pass.

- [x] **Step 2: Run TypeScript validation**

```powershell
npm run typecheck
```

Expected: exit code 0 with no TypeScript errors.

- [x] **Step 3: Build the frontend**

```powershell
npm run build
```

Expected: Vite production build completes successfully.

- [x] **Step 4: Review scope**

Confirm the final changes are limited to the listed frontend components/tests plus this spec/plan. Do not run `vision_test.py`, connect to Pixhawk, send RC/MAVLink commands, or modify Raspberry Pi files.
