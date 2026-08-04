# Ready Lomba — Remove Dummy Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the dashboard to competition-ready state: no synthetic telemetry, no MissionStage dev UI, no simulation boat replacing real GPS.

**Architecture:** The root cause is `dashboard-shell.tsx` line 47: `simulationTelemetryActive = mode === 'fixture' || telemetryMissing`. The `|| telemetryMissing` term causes the simulation engine to silently fabricate telemetry whenever real Pixhawk data is absent — even in `direct` mode. Fix: restrict simulation to `mode === 'fixture'` only, remove `MissionStage` from the render, and stop passing `simulation` to `NavigationMap` in direct mode.

**Tech Stack:** React 19, TypeScript, Vitest, dashboard/src/

---

### Task 1: Fix dashboard-shell.tsx — remove simulation takeover in direct mode

**Files:**
- Modify: `dashboard/src/components/dashboard-shell.tsx`

- [ ] **Step 1: Apply the fix**

Replace the simulation activation logic and remove MissionStage / simulation prop from NavigationMap:

```tsx
// BEFORE (lines 46-50):
const telemetryMissing = !telemetry || !telemetry.connected
const simulationTelemetryActive = mode === 'fixture' || telemetryMissing
const simulation = useMissionSimulation({
  autoStart: mode === 'fixture' || telemetryMissing,
})

// AFTER:
const simulationTelemetryActive = mode === 'fixture'
const simulation = useMissionSimulation({
  autoStart: mode === 'fixture',
})
```

Remove the fake timestamp overwrites (lines 64-71):
```tsx
// BEFORE:
const displayLive =
  mode === 'fixture' && live && displayTelemetry
    ? { ...live, updated_at: displayTelemetry.captured_at }
    : live
const displayUnderwaterFrame =
  mode === 'fixture' && underwaterFrame && displayTelemetry
    ? { ...underwaterFrame, captured_at: displayTelemetry.captured_at }
    : underwaterFrame

// AFTER:
const displayLive = live
const displayUnderwaterFrame = underwaterFrame
```

Remove `MissionStage` from the render and stop passing `simulation` to `NavigationMap`:
```tsx
// BEFORE:
<NavigationMap
  telemetry={navigation}
  simulation={simulation}
  previewMode={mode === 'fixture'}
/>
<MissionStage simulation={simulation} />

// AFTER:
<NavigationMap
  telemetry={navigation}
  simulation={mode === 'fixture' ? simulation : undefined}
  previewMode={mode === 'fixture'}
/>
```

Also remove the `MissionStage` import and the `useRef` import if no longer needed.

- [ ] **Step 2: Verify the file compiles**

Run: `cd D:/KKI2/KKI2026/dashboard && npx tsc --noEmit`
Expected: no errors related to dashboard-shell.tsx

---

### Task 2: Update dashboard-shell.test.tsx

**Files:**
- Modify: `dashboard/src/components/dashboard-shell.test.tsx`

- [ ] **Step 1: Update tests that expect simulation behavior when telemetry is missing**

The test `'runs the mission route preview while telemetry is still missing'` (line 75) expects `simulation-boat` to appear when `telemetry={null}`. After the fix, no simulation boat should appear in direct mode. Update it:

```tsx
// BEFORE:
it('runs the mission route preview while telemetry is still missing', () => {
  render(
    <DashboardShell
      live={liveStatus}
      telemetry={null}
      telemetryRealtimeStatus="connecting"
      underwaterFrame={null}
    />,
  )
  expect(screen.queryByText('Waiting for GPS fix.')).not.toBeInTheDocument()
  expect(screen.getByTestId('simulation-boat')).toBeInTheDocument()
})

// AFTER:
it('shows GPS waiting state when telemetry is missing in direct mode', () => {
  render(
    <DashboardShell
      live={liveStatus}
      telemetry={null}
      telemetryRealtimeStatus="connecting"
      underwaterFrame={null}
    />,
  )
  expect(screen.getByText('Waiting for GPS fix.')).toBeInTheDocument()
  expect(screen.queryByTestId('simulation-boat')).not.toBeInTheDocument()
})
```

The test `'shows the initial replay marker before mission start in direct mode'` (line 89) expects `simulation-boat` even with real telemetry. After the fix, the real `boat-marker` should appear instead:

```tsx
// BEFORE:
it('shows the initial replay marker before mission start in direct mode', () => {
  render(
    <DashboardShell
      live={liveStatus}
      telemetry={telemetry}
      telemetryRealtimeStatus="connected"
      underwaterFrame={underwaterFrame}
    />,
  )
  expect(screen.getByTestId('simulation-boat')).toBeInTheDocument()
  expect(screen.queryByTestId('boat-marker')).not.toBeInTheDocument()
})

// AFTER:
it('shows the real GPS boat marker in direct mode', () => {
  render(
    <DashboardShell
      live={liveStatus}
      telemetry={telemetry}
      telemetryRealtimeStatus="connected"
      underwaterFrame={underwaterFrame}
    />,
  )
  expect(screen.getByTestId('boat-marker')).toBeInTheDocument()
  expect(screen.queryByTestId('simulation-boat')).not.toBeInTheDocument()
})
```

The two tests named `'uses fallback heading and speed while Pixhawk telemetry is missing'` (lines 191 and 245) expect synthetic telemetry values when `telemetry={null}`. After the fix, the panel shows "Unavailable" instead:

```tsx
// BEFORE (line 191 test):
it('uses fallback heading and speed while Pixhawk telemetry is missing', () => {
  render(
    <DashboardShell
      live={null}
      telemetry={null}
      telemetryRealtimeStatus="error"
      underwaterFrame={null}
    />,
  )
  const telemetryRegion = screen.getByRole('region', { name: 'Attitude telemetry' })
  expect(telemetryRegion).not.toHaveTextContent('Unavailable')
  expect(telemetryRegion).toHaveTextContent(/\d+\.\d+°/)
  expect(telemetryRegion).toHaveTextContent(/\d+\.\d{2} knot/)
  expect(screen.getByText('ASV online')).toBeInTheDocument()
  expect(screen.queryByText('ASV offline')).not.toBeInTheDocument()
  expect(screen.queryByText('Realtime delayed')).not.toBeInTheDocument()
})

// AFTER:
it('shows unavailable telemetry and offline status when Pixhawk is missing', () => {
  render(
    <DashboardShell
      live={null}
      telemetry={null}
      telemetryRealtimeStatus="error"
      underwaterFrame={null}
    />,
  )
  const telemetryRegion = screen.getByRole('region', { name: 'Attitude telemetry' })
  expect(telemetryRegion).toHaveTextContent('Unavailable')
  expect(screen.getByText('ASV offline')).toBeInTheDocument()
  expect(screen.queryByText('ASV online')).not.toBeInTheDocument()
})
```

```tsx
// BEFORE (line 245 test):
it('uses fallback heading and speed while Pixhawk telemetry is missing', () => {
  render(
    <DashboardShell
      live={{ ...liveStatus, online: false, model_status: 'offline' }}
      telemetry={null}
      telemetryRealtimeStatus="error"
      underwaterFrame={null}
      underwaterStreamUrl={null}
    />,
  )
  expect(screen.getByText('ASV online')).toBeInTheDocument()
  expect(screen.queryByText('On-site test')).not.toBeInTheDocument()
  expect(screen.queryByText('Realtime delayed')).not.toBeInTheDocument()
  expect(screen.getByText('Underwater feed offline')).toBeInTheDocument()
})

// AFTER:
it('shows offline status and underwater feed offline when telemetry is missing', () => {
  render(
    <DashboardShell
      live={{ ...liveStatus, online: false, model_status: 'offline' }}
      telemetry={null}
      telemetryRealtimeStatus="error"
      underwaterFrame={null}
      underwaterStreamUrl={null}
    />,
  )
  expect(screen.getByText('ASV offline')).toBeInTheDocument()
  expect(screen.queryByText('On-site test')).not.toBeInTheDocument()
  expect(screen.getByText('Underwater feed offline')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run tests**

Run: `cd D:/KKI2/KKI2026/dashboard && npx vitest run src/components/dashboard-shell.test.tsx`
Expected: all tests pass

---

### Task 3: Run full test suite and typecheck

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd D:/KKI2/KKI2026/dashboard && npx vitest run`
Expected: all tests pass

- [ ] **Step 2: Run typecheck**

Run: `cd D:/KKI2/KKI2026/dashboard && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
cd D:/KKI2/KKI2026
git add dashboard/src/components/dashboard-shell.tsx dashboard/src/components/dashboard-shell.test.tsx
git commit -m "fix(dashboard): remove simulation takeover in direct mode for competition readiness"
```
