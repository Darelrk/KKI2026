import { MapPin, WarningCircle } from '@phosphor-icons/react'

import { CameraStage } from './camera-stage'
import { ConnectionBar } from './connection-bar'
import { SignalRail } from './signal-rail'
import { UnderwaterFallback } from './underwater-fallback'

import { asvStreamUrls } from '../lib/stream-urls'

import type { AsvLive, UnderwaterFrame } from '../lib/asv-types'
import type { ConnectionStatus } from './connection-bar'

type DashboardShellProps = {
  asvId: string
  live: AsvLive | null | undefined
  liveRealtimeStatus: ConnectionStatus
  underwaterFrame: UnderwaterFrame | null
  underwaterRealtimeStatus: ConnectionStatus
  surfaceStreamUrl?: string | null
  underwaterStreamUrl?: string | null
}

export function DashboardShell({
  asvId,
  live,
  liveRealtimeStatus,
  underwaterFrame,
  underwaterRealtimeStatus,
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
        <SignalRail live={live ?? null} />
      </section>

      <section className="navigation-placeholder" aria-labelledby="navigation-title">
        <div className="panel-heading">
          <MapPin aria-hidden="true" />
          <div>
            <p className="eyebrow">Route telemetry</p>
            <h2 id="navigation-title">Navigation view</h2>
          </div>
        </div>
        <p>Navigation feed not connected</p>
        <span>Position, heading, speed, and route data will appear when the ASV bridge publishes telemetry.</span>
      </section>

      <footer className="dashboard-shell__footer">
        <span>Surface channel: {liveRealtimeStatus}</span>
        <span>Fallback channel: {underwaterRealtimeStatus}</span>
      </footer>
    </main>
  )
}
