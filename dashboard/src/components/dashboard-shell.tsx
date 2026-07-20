import { WarningCircle } from '@phosphor-icons/react'

import { MissionStage } from './mission-stage'
import { NavigationMap } from './navigation-map'
import { TelemetryPanel } from './telemetry-panel'
import { CameraStage } from './camera-stage'
import { ConnectionBar } from './connection-bar'
import { SignalRail } from './signal-rail'
import { UnderwaterFallback } from './underwater-fallback'

import { emptyNavigationTelemetry } from '../lib/navigation-types'
import type { NavigationTelemetry } from '../lib/navigation-types'
import { asvStreamUrls } from '../lib/stream-urls'

import type { AsvLive, UnderwaterFrame } from '../lib/asv-types'
import type { ConnectionStatus } from './connection-bar'

type DashboardShellProps = {
  asvId: string
  live: AsvLive | null | undefined
  liveRealtimeStatus: ConnectionStatus
  underwaterFrame: UnderwaterFrame | null
  underwaterRealtimeStatus: ConnectionStatus
  navigation?: NavigationTelemetry
  surfaceStreamUrl?: string | null
  underwaterStreamUrl?: string | null
}

export function DashboardShell({
  asvId,
  live,
  liveRealtimeStatus,
  underwaterFrame,
  underwaterRealtimeStatus,
  navigation = emptyNavigationTelemetry,
  surfaceStreamUrl = asvStreamUrls.surface,
  underwaterStreamUrl = asvStreamUrls.underwater,
}: DashboardShellProps) {
  const online = live?.online ?? false
  const isUnavailable = !live || !online

  return (
    <main className="dashboard-shell">

      <ConnectionBar asvId={asvId} online={online} status={liveRealtimeStatus} />

      {isUnavailable ? (
        <section className="dashboard-shell__alert" role="status">
          <WarningCircle aria-hidden="true" weight="fill" />
          <div>
            <strong>Telemetry unavailable</strong>
            <p>Waiting for a valid ASV status message from the realtime channel.</p>
          </div>
        </section>
      ) : null}

      <section className="dashboard-grid" aria-label="ASV operational dashboard">
        <div className="dashboard-grid__cameras">
          <CameraStage streamUrl={surfaceStreamUrl} />
          <UnderwaterFallback frame={underwaterFrame} streamUrl={underwaterStreamUrl} />
        </div>
          <div className="dashboard-grid__side">
            <SignalRail live={live ?? null} />
            <TelemetryPanel telemetry={navigation} updatedAt={live?.updated_at ?? null} />
          </div>
        </section>

      <NavigationMap telemetry={navigation} />
      <MissionStage />

      <footer className="dashboard-shell__footer">
        <span>Surface channel: {liveRealtimeStatus}</span>
        <span>Fallback channel: {underwaterRealtimeStatus}</span>
      </footer>
    </main>
  )
}
