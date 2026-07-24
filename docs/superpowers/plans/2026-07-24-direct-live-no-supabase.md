# Direct Live Tunnel Without Supabase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Vercel-hosted dashboard consume all live status, telemetry, metadata, and camera streams directly from the Raspberry Pi tunnel without Supabase on the live path.

**Architecture:** Keep Vercel as a static frontend host. The browser connects directly to the public HTTPS/WSS tunnel: raw camera URLs stay direct, vision metadata stays on `/ws/vision/{asv_id}`, and status/telemetry use the existing `/api/status` and `/api/telemetry` endpoints with bounded polling. The Raspberry Pi bridge remains the read-only MAVLink owner and may run with Supabase disabled; the existing Supabase mode remains an explicit rollback option but is not selected by the live deployment.

**Tech Stack:** React 19, TanStack Query, Vitest, Zod, FastAPI, Pydantic, pytest, CORS middleware, existing Cloudflare/tunnel HTTPS and WSS endpoints.

---

### Task 1: Add the direct live data contract

**Files:**
- Modify: `dashboard/src/lib/asv-data-mode.ts`
- Modify: `dashboard/src/lib/asv-data-mode.test.ts`
- Modify: `dashboard/src/lib/stream-urls.ts`
- Modify: `dashboard/src/lib/stream-urls.test.ts`
- Create: `dashboard/src/lib/direct-live.ts`
- Create: `dashboard/src/lib/direct-live.test.ts`

- [ ] **Step 1: Write failing mode and URL tests**

Add tests proving `direct` is accepted and the bridge URL trims an explicit environment value while falling back to the existing tunnel origin.

Expected assertions:

```ts
expect(getAsvDataMode('direct')).toBe('direct')
expect(resolveAsvBridgeUrl({ VITE_ASV_BRIDGE_URL: ' https://bridge.example.test/ ' })).toBe(
  'https://bridge.example.test',
)
expect(resolveAsvBridgeUrl({})).toBe('https://monitor-kapal-pora-pora.web.id')
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run from `KKI2026/dashboard`:

```powershell
npm run test -- --run src/lib/asv-data-mode.test.ts src/lib/stream-urls.test.ts
```

Expected: FAIL because `direct` and `resolveAsvBridgeUrl` do not exist.

- [ ] **Step 3: Implement direct mode and validated fetch helpers**

Add `direct` to the data-mode schema. Add `defaultAsvBridgeUrl`, `resolveAsvBridgeUrl`, and `asvBridgeUrl` in `stream-urls.ts`. Create `direct-live.ts` with:

```ts
export async function fetchDirectAsvLive(baseUrl: string, signal?: AbortSignal): Promise<AsvLive>
export async function fetchDirectTelemetry(baseUrl: string, signal?: AbortSignal): Promise<AsvTelemetry>
```

Each helper must request `/api/status` or `/api/telemetry` with `cache: 'no-store'`, reject non-2xx responses, parse with the existing Zod schema, and return no Supabase client.

- [ ] **Step 4: Run focused tests and confirm GREEN**

```powershell
npm run test -- --run src/lib/asv-data-mode.test.ts src/lib/stream-urls.test.ts src/lib/direct-live.test.ts
```

Expected: PASS.

### Task 2: Switch browser live hooks to direct polling

**Files:**
- Modify: `dashboard/src/lib/use-asv-live.ts`
- Modify: `dashboard/src/lib/use-asv-live.test.tsx`
- Modify: `dashboard/src/lib/use-telemetry-broadcast.ts`
- Modify: `dashboard/src/lib/use-telemetry-broadcast.test.tsx`
- Modify: `dashboard/src/lib/use-underwater-broadcast.ts`
- Modify: `dashboard/src/lib/use-underwater-broadcast.test.tsx`
- Modify: `dashboard/src/components/dashboard-client.tsx`

- [ ] **Step 1: Write failing direct-mode hook tests**

Add tests proving:

- `useAsvLive('default', 'direct')` calls the direct `/api/status` helper, never the Supabase helper, and refetches on the configured interval.
- `useTelemetryBroadcast('default', 'direct')` calls the direct `/api/telemetry` helper and reports `connected` after a valid response.
- `useUnderwaterBroadcast('default', 'direct')` does not create a Supabase channel and returns no fallback frame because the raw underwater `<img>` URL is the direct live source.

- [ ] **Step 2: Run hook tests and confirm RED**

```powershell
npm run test -- --run src/lib/use-asv-live.test.tsx src/lib/use-telemetry-broadcast.test.tsx src/lib/use-underwater-broadcast.test.tsx
```

Expected: FAIL because the hooks only recognize `fixture` and `supabase`.

- [ ] **Step 3: Implement direct mode with bounded polling**

Use the existing query for status with `refetchInterval: 2000` in direct mode. Use one direct telemetry fetch per second with cleanup on unmount and no overlapping Supabase channel. Preserve the current Supabase branch for rollback. In direct mode, keep vision metadata on the existing direct WSS hook and let the raw underwater URL remain the source of truth.

- [ ] **Step 4: Run focused hook tests and confirm GREEN**

```powershell
npm run test -- --run src/lib/use-asv-live.test.tsx src/lib/use-telemetry-broadcast.test.tsx src/lib/use-underwater-broadcast.test.tsx
```

Expected: PASS.

### Task 3: Allow browser requests through the Pi tunnel

**Files:**
- Modify: `asv_dashboard_backend/config.py`
- Modify: `asv_dashboard_backend/main.py`
- Modify: `asv_dashboard_backend/tests` only if an existing backend test module covers settings/app creation
- Modify: `deploy/raspberry-pi/asv-dashboard.env.example`
- Modify: `deploy/raspberry-pi/codex-prompt.txt`

- [ ] **Step 1: Write failing CORS configuration tests**

Add backend tests proving `ASV_CORS_ORIGINS` parses comma-separated origins and `create_app()` responds to a preflight request for an allowed origin.

- [ ] **Step 2: Run backend tests and confirm RED**

```powershell
python -m pytest -q tests/test_dashboard_backend.py
```

Expected: FAIL because the setting and middleware do not exist.

- [ ] **Step 3: Implement explicit-origin CORS**

Add a validated `cors_origins` setting loaded from `ASV_CORS_ORIGINS`, configure FastAPI `CORSMiddleware` with the explicit origins, `GET`/`OPTIONS` plus existing browser-safe headers, and no credentialed wildcard. Document a concrete environment shape:

```text
ASV_CORS_ORIGINS=https://<vercel-domain>,http://localhost:3000
```

Do not expose the Supabase service role key to the browser. Keep the write endpoints private at the tunnel/reverse-proxy layer or protected separately; this migration only makes read-only live endpoints browser-readable.

- [ ] **Step 4: Run backend tests and confirm GREEN**

```powershell
python -m pytest -q tests/test_dashboard_backend.py
```

Expected: PASS.

### Task 4: Select direct mode for the deployed dashboard

**Files:**
- Modify: `dashboard/.env.example`
- Modify: `dashboard/.env.local` only for the local ignored deployment configuration
- Modify: `deploy/raspberry-pi/asv-dashboard.env.example`
- Modify: `handover.md`

- [ ] **Step 1: Add direct-mode environment documentation**

Document:

```text
VITE_ASV_DATA_MODE=direct
VITE_ASV_BRIDGE_URL=https://monitor-kapal-pora-pora.web.id
VITE_ASV_SURFACE_STREAM_URL=https://monitor-kapal-pora-pora.web.id/stream/atas
VITE_ASV_UNDERWATER_STREAM_URL=https://monitor-kapal-pora-pora.web.id/stream/bawah
VITE_ASV_VISION_WS_URL=wss://monitor-kapal-pora-pora.web.id
```

Set the ignored local dashboard mode to `direct`. Do not delete Supabase credentials from the ignored file unless the user explicitly wants the rollback mode removed; direct mode must not call them.

- [ ] **Step 2: Document the single MAVLink owner**

State that `ASV_PIXHAWK_ENABLED=true` on the Pi must not share the same Pixhawk serial endpoint with Mission Planner, QGroundControl, or another backend. The direct browser path only reads HTTP/WSS from the tunnel.

### Task 5: Verify the complete direct live path

**Files:**
- Modify: `dashboard/src/components/dashboard-client-state.test.tsx` only if direct-mode state coverage needs an assertion
- Modify: `tests/test_dashboard_backend.py` only if endpoint/CORS coverage needs an assertion

- [ ] **Step 1: Run the complete frontend checks**

From `KKI2026`:

```powershell
npm run typecheck --workspace dashboard
npm run test --workspace dashboard -- --pool=threads --maxWorkers=1 --fileParallelism=false
npm run build --workspace dashboard
```

Expected: PASS, including direct-mode hook tests.

- [ ] **Step 2: Run the complete backend checks**

```powershell
python -m pytest -q
python -m compileall -q asv_dashboard_backend vision_route.py vision_test.py tests
```

Expected: PASS.

- [ ] **Step 3: Smoke-test the tunnel endpoints**

With the Pi bridge and tunnel running, verify:

```powershell
curl.exe -i https://monitor-kapal-pora-pora.web.id/healthz
curl.exe -i https://monitor-kapal-pora-pora.web.id/api/status
curl.exe -i https://monitor-kapal-pora-pora.web.id/api/telemetry
```

Expected: `200` JSON responses and correct CORS headers for the configured Vercel origin. Open both configured camera URLs in the browser and verify the vision WSS reaches `/ws/vision/default`.

- [ ] **Step 4: Confirm Supabase is absent from the live network path**

Run the dashboard in `direct` mode and verify browser network traffic contains only the tunnel’s HTTPS/WSS requests for live data. Supabase may remain installed for rollback, but no live hook should create a Supabase client or channel in direct mode.

---

**Plan self-review:** Direct video was already tunnel-based; this plan changes only status, telemetry, and fallback handling. It does not add a Vercel stream proxy, move RC/MAVLink control into the browser, or remove Supabase schema/dependencies needed for explicit rollback. The main unresolved deployment input is the actual Vercel origin that must be placed in `ASV_CORS_ORIGINS`.
