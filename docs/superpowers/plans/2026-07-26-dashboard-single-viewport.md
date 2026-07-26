# Dashboard Single-Viewport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fit every remaining desktop dashboard function into one browser viewport while removing the complete Course layout option panel and all `proposal route` copy.

**Architecture:** Keep the existing React component tree and use CSS Grid areas on `.dashboard-shell` for the desktop control-room composition. Delete the route legend state and markup at the source, leave route graphics permanently visible, and preserve the existing flowing mobile layout.

**Tech Stack:** React 19, TypeScript, CSS Grid/Flexbox, Vitest, Testing Library, Vite, Chromium browser smoke tests.

---

### Task 1: Remove Course Layout Options and Proposal Copy

**Files:**
- Modify: `dashboard/src/components/navigation-map.tsx`
- Modify: `dashboard/src/components/navigation-map.test.tsx`
- Modify: `dashboard/src/components/mission-stage.tsx`
- Modify: `dashboard/src/components/mission-stage.test.tsx`

- [ ] **Step 1: Write failing UI assertions**

Update the navigation map test to assert the map graphics remain while the option panel is absent:

```tsx
expect(screen.getAllByTestId('buoy-pair')).toHaveLength(10)
expect(screen.queryByRole('complementary', { name: 'Mission route legend' })).not.toBeInTheDocument()
expect(screen.queryByText('Course layout')).not.toBeInTheDocument()
expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
```

Update the mission test to assert the removed copy is absent:

```tsx
expect(screen.queryByText(/proposal route/i)).not.toBeInTheDocument()
```

- [ ] **Step 2: Run the focused tests and confirm red state**

Run:

```bash
npm run test --workspace dashboard -- --pool=threads --maxWorkers=1 --fileParallelism=false src/components/navigation-map.test.tsx src/components/mission-stage.test.tsx
```

Expected: failures because the Course layout aside/checkboxes and `0% proposal route` still exist.

- [ ] **Step 3: Delete the legend state and markup**

In `navigation-map.tsx`:

- Remove `useState`.
- Remove `LayerVisibility`, `layerLabels`, `visibleLayers`, and `toggleLayer`.
- Render surface zone, underwater zone, buoy pairs, dock labels, and docking balls unconditionally.
- Delete the complete `<aside className="route-legend" ...>` block.
- Keep the live GPS track and simulation track behavior unchanged.

In `mission-stage.tsx`, delete this line completely:

```tsx
<small>{Math.round(simulation.progress * 100)}% proposal route</small>
```

- [ ] **Step 4: Run focused tests and confirm green state**

Run the focused command from Step 2.

Expected: both test files pass.

### Task 2: Compose the Desktop Dashboard in One Viewport

**Files:**
- Modify: `dashboard/src/styles.css`

- [ ] **Step 1: Create the desktop shell grid**

Inside the existing `@media (min-width: 60.0625rem)` block, set:

```css
.dashboard-shell {
  position: relative;
  width: 100%;
  height: 100dvh;
  min-height: 0;
  padding: 0.5rem;
  overflow: hidden;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  grid-template-rows: auto minmax(0, 1fr) auto auto;
  grid-template-areas:
    "connection connection"
    "overview map"
    "mission mission"
    "footer footer";
  gap: 0.5rem;
}

.connection-bar { grid-area: connection; }
.dashboard-grid { grid-area: overview; }
.navigation-map { grid-area: map; }
.mission-stage { grid-area: mission; }
.dashboard-shell__footer { grid-area: footer; }
```

Make `.dashboard-shell__alert` an absolute compact overlay so a disconnected status does not create a fifth grid row.

- [ ] **Step 2: Make every main-row child shrink correctly**

Apply `min-width: 0`, `min-height: 0`, and `overflow: hidden` to the desktop grid panels. Stretch the nested camera/status grids to `height: 100%`; give camera media `height: 100%`, `aspect-ratio: auto`, and `object-fit: contain`. Make `.navigation-map`, `.navigation-map__layout`, and `.navigation-map__canvas` fill their grid cell.

- [ ] **Step 3: Remove obsolete route legend CSS and expand the map**

Delete all `.route-legend*` rules. Change `.navigation-map__layout` to a one-column, full-height grid and preserve the map readout at the bottom.

- [ ] **Step 4: Densify the mission row without hiding controls**

Reduce desktop-only panel padding, gaps, heading margins, mission summary padding, button padding, timeline card height, target spacing, and footer height. Keep all four simulation buttons and all seven timeline steps visible.

- [ ] **Step 5: Preserve narrow-screen flow**

Keep the existing `@media (max-width: 60rem)` rules scrollable. Do not apply `height: 100dvh` or `overflow: hidden` below the desktop breakpoint.

### Task 3: Verify Behavior and Viewport Fit

**Files:**
- Test: existing dashboard test suite
- Verify: browser viewport behavior

- [ ] **Step 1: Run typecheck and the full test suite**

```bash
npm run typecheck --workspace dashboard
npm run test --workspace dashboard -- --pool=threads --maxWorkers=1 --fileParallelism=false
```

Expected: typecheck succeeds and all tests pass.

- [ ] **Step 2: Run production build**

```bash
npm run build --workspace dashboard
```

Expected: Vite and Nitro builds succeed.

- [ ] **Step 3: Smoke test desktop viewports**

Run the fixture dashboard and inspect at 1920×1080 and 1440×1000. For each viewport evaluate:

```js
({
  viewport: [window.innerWidth, window.innerHeight],
  documentHeight: document.documentElement.scrollHeight,
  fits: document.documentElement.scrollHeight <= window.innerHeight,
  panels: [...document.querySelectorAll(
    '.connection-bar, .dashboard-grid, .navigation-map, .mission-stage, .dashboard-shell__footer'
  )].every((element) => element.getBoundingClientRect().bottom <= window.innerHeight),
  legendPresent: document.body.innerText.includes('Course layout'),
  proposalPresent: /proposal route/i.test(document.body.innerText),
})
```

Expected: `fits` and `panels` are `true`; `legendPresent` and `proposalPresent` are `false`.

- [ ] **Step 4: Smoke test mobile fallback**

At 390×844, confirm the document may scroll vertically, all remaining panels are reachable, and no content is clipped by desktop overflow rules.
