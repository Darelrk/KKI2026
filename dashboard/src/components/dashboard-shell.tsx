import { WarningCircle } from '@phosphor-icons/react'
import { useRef } from 'react'

import { MissionStage } from './mission-stage'
import { NavigationMap } from './navigation-map'
import { TelemetryPanel } from './telemetry-panel'
import { CameraStage } from './camera-stage'
import { ConnectionBar } from './connection-bar'
import { SignalRail } from './signal-rail'
import { UnderwaterFallback } from './underwater-fallback'

import { emptyNavigationTelemetry } from '../lib/navigation-types'
import { kolamDeliSite, missionTelemetryAt } from '../lib/mission-site'
import { asvStreamUrls } from '../lib/stream-urls'
import { useMissionSimulation } from '../lib/use-mission-simulation'

import type { AsvLive, UnderwaterFrame } from '../lib/asv-types'
import type { AsvDataMode } from '../lib/asv-data-mode'
import type { AsvTelemetry } from '../lib/asv-telemetry'
import type { VisionMetadataCache } from '../lib/vision-metadata'
import type { VisionRealtimeStatus } from '../lib/use-vision-metadata'
import type { ConnectionStatus } from './connection-bar'

type DashboardShellProps = {
  asvId: string
  mode?: AsvDataMode
  live: AsvLive | null | undefined
  liveRealtimeStatus: ConnectionStatus
  telemetry?: AsvTelemetry | null
  telemetryRealtimeStatus?: ConnectionStatus
  underwaterFrame: UnderwaterFrame | null
  underwaterRealtimeStatus: ConnectionStatus
  visionMetadataCache?: VisionMetadataCache | null
  visionMetadataStatus?: VisionRealtimeStatus
  surfaceStreamUrl?: string | null
  underwaterStreamUrl?: string | null
}

export function DashboardShell({
  asvId,
  mode = 'direct',
  live,
  liveRealtimeStatus,
  telemetry = null,
  telemetryRealtimeStatus = 'connecting',
  underwaterFrame,
  underwaterRealtimeStatus,
  visionMetadataCache = null,
  visionMetadataStatus = 'error',
  surfaceStreamUrl = asvStreamUrls.surface,
  underwaterStreamUrl = asvStreamUrls.underwater,
}: DashboardShellProps) {
  const simulation = useMissionSimulation({ autoStart: mode === 'fixture' })
  const fixtureStartedAtMs = useRef(Date.now())
  const displayTelemetry =
    mode === 'fixture'
      ? missionTelemetryAt({
          progress: simulation.progress,
          elapsedMs: simulation.elapsedMs,
          status: simulation.status,
          startedAtMs: fixtureStartedAtMs.current,
        })
      : telemetry
  const isUnavailable = !displayTelemetry || !displayTelemetry.connected
  const navigation = displayTelemetry ?? emptyNavigationTelemetry
  const displayLive =
    mode === 'fixture' && live && displayTelemetry
      ? { ...live, updated_at: displayTelemetry.captured_at }
      : live
  const displayUnderwaterFrame =
    mode === 'fixture' && underwaterFrame && displayTelemetry
      ? { ...underwaterFrame, captured_at: displayTelemetry.captured_at }
      : underwaterFrame
  const displayChannelStatus = (status: ConnectionStatus) =>
    status === 'fixture' ? 'active' : status

  return (
    <main className="dashboard-shell">
      <ConnectionBar
        asvId={asvId}
        online={displayTelemetry?.connected ?? false}
        status={telemetryRealtimeStatus}
      />

      {isUnavailable ? (
        <section className="dashboard-shell__alert" role="status">
          <WarningCircle aria-hidden="true" weight="fill" />
          <div>
            <strong>Telemetry unavailable</strong>
            <p>
              Waiting for a valid Pixhawk telemetry message from the realtime
              channel.
            </p>
          </div>
        </section>
      ) : null}

      <section
        className="dashboard-grid"
        aria-label="ASV operational dashboard"
      >
        <div className="dashboard-grid__cameras">
          <CameraStage
            streamUrl={surfaceStreamUrl}
            metadataCache={visionMetadataCache}
            metadataStatus={visionMetadataStatus}
          />
          <UnderwaterFallback
            frame={displayUnderwaterFrame}
            streamUrl={underwaterStreamUrl}
          />
        </div>
        <div className="dashboard-grid__side">
          <SignalRail
            live={displayLive ?? null}
            telemetryConnected={displayTelemetry?.connected ?? null}
            telemetryStatus={telemetryRealtimeStatus}
          />
          <TelemetryPanel
            telemetry={navigation}
            updatedAt={displayTelemetry?.captured_at ?? null}
          />
        </div>
      </section>

      <NavigationMap
        telemetry={navigation}
        simulation={simulation}
        previewMode={mode === 'fixture'}
      />
      <MissionStage simulation={simulation} />

      <footer className="dashboard-shell__footer">
        {mode === 'fixture' ? (
          <span>Test site: {kolamDeliSite.name} · Lintasan A</span>
        ) : null}
        <span>Surface channel: {displayChannelStatus(liveRealtimeStatus)}</span>
        <span>
          Fallback channel: {displayChannelStatus(underwaterRealtimeStatus)}
        </span>
        <span>
          Telemetry channel: {displayChannelStatus(telemetryRealtimeStatus)}
        </span>
      </footer>
    </main>
  )
}
