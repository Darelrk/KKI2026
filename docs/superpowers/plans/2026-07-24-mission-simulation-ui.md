# Mission Simulation UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clearly labeled local mission replay so the dashboard controls can be clicked and the proposal route visibly progresses without sending commands to the boat.

**Architecture:** Keep mission execution out of the Raspberry Pi bridge and out of Supabase. A small pure simulation model owns progress, stage, timer, and control transitions; a React hook runs the clock only while replaying. `DashboardShell` passes the simulation view into the existing map and mission timeline, while real Pixhawk telemetry and the `RC MANUAL` control-source display remain unchanged.

**Tech Stack:** React 19, TypeScript, Vitest, existing SVG/CSS dashboard components.

---

### Task 1: Define the replay model and route

**Files:**
- Create: `dashboard/src/lib/mission-simulation.ts`
- Test: `dashboard/src/lib/mission-simulation.test.ts`

- [ ] Define the proposal route as normalized SVG points, seven stage boundaries, and a fixed replay duration.
- [ ] Implement pure transitions for `start`, `pause`, `stop`, `reset`, and elapsed-time ticks.
- [ ] Clamp progress to `[0, 1]`; transition to `complete` at the route end; never emit MAVLink or network actions.
- [ ] Test idle/start/pause/stop/reset/complete and stage selection at boundaries.

### Task 2: Add the local simulation hook

**Files:**
- Create: `dashboard/src/lib/use-mission-simulation.ts`
- Test: `dashboard/src/lib/use-mission-simulation.test.ts`

- [ ] Expose state, `start`, `pause`, `stop`, and `reset` from a hook backed by the pure model.
- [ ] Use a browser timer only while `status === 'running'`; clean it up on unmount and mode changes.
- [ ] Test that start advances progress, pause freezes it, stop returns to idle, and reset clears the timer/progress.

### Task 3: Make the mission timeline clickable in simulation mode

**Files:**
- Modify: `dashboard/src/components/mission-stage.tsx`
- Modify: `dashboard/src/components/dashboard-shell.tsx`
- Test: `dashboard/src/components/mission-stage.test.tsx`

- [ ] Add `SIMULATION / DEMO` and `RC MANUAL — no MAVLink commands` labels.
- [ ] Add Start, Pause, Stop, and Reset buttons with disabled states derived from the replay status.
- [ ] Highlight the current replay stage and show elapsed time/progress without claiming real vessel movement.
- [ ] Keep the existing mission target summary; stage clicks only select a local preview stage.

### Task 4: Connect replay progress and course filters to the map

**Files:**
- Modify: `dashboard/src/components/navigation-map.tsx`
- Modify: `dashboard/src/components/dashboard-shell.tsx`
- Modify: `dashboard/src/styles.css`
- Test: `dashboard/src/components/navigation-map.test.tsx`

- [ ] Render the simulated boat and simulated track along the fixed proposal route when replay is active.
- [ ] Keep live GPS track rendering unchanged when simulation is idle or absent.
- [ ] Make Navigation, Surface imaging, Underwater imaging, and Finish dock legend rows clickable visibility toggles.
- [ ] Expose accessible checked state and keep all toggles local to the dashboard.

### Task 5: Verify the safe presentation contract

**Files:**
- Modify: `dashboard/src/components/dashboard-client.tsx` only if needed to enable simulation in fixture mode.
- Modify: `dashboard/src/components/signal-rail.tsx` only if needed to preserve explicit `RC MANUAL` text.

- [ ] Confirm no backend route, Pixhawk command, Supabase client, or environment secret is added.
- [ ] Run focused tests, full frontend tests, typecheck, and production build.
- [ ] Run the dashboard in fixture mode and click Start/Pause/Stop/Reset plus all course filters in a browser; verify visible state changes and explicit simulation labels.
