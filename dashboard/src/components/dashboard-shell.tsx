import { WarningCircle } from '@phosphor-icons/react'

import { MissionStage } from './mission-stage'
import { NavigationMap } from './navigation-map'
import { TelemetryPanel } from './telemetry-panel'
import { CameraStage } from './camera-stage'
import { ConnectionBar } from './connection-bar'
import { SignalRail } from './signal-rail'
import { UnderwaterFallback } from './underwater-fallback'

import { emptyNavigationTelemetry } from '../lib/navigation-types'
import { asvStreamUrls } from '../lib/stream-urls'

import type { AsvLive, UnderwaterFrame } from '../lib/asv-types'
import type { AsvTelemetry } from '../lib/asv-telemetry'
import type { VisionMetadataCache } from '../lib/vision-metadata'
import type { VisionRealtimeStatus } from '../lib/use-vision-metadata'
import type { ConnectionStatus } from './connection-bar'

type DashboardShellProps = {
  asvId: string
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
  const isUnavailable = !telemetry || !telemetry.connected
  const navigation = telemetry ?? emptyNavigationTelemetry

  return (
    <main className="dashboard-shell">
      <ConnectionBar
        asvId={asvId}
        online={telemetry?.connected ?? false}
        status={telemetryRealtimeStatus}
      />

      {isUnavailable ? (
        <section className="dashboard-shell__alert" role="status">
          <WarningCircle aria-hidden="true" weight="fill" />
          <div>
            <strong>Telemetry unavailable</strong>
            <p>Waiting for a valid Pixhawk telemetry message from the realtime channel.</p>
          </div>
        </section>
      ) : null}

      <section className="dashboard-grid" aria-label="ASV operational dashboard">
        <div className="dashboard-grid__cameras">
          <CameraStage
            streamUrl={surfaceStreamUrl}
            metadataCache={visionMetadataCache}
            metadataStatus={visionMetadataStatus}
          />
          <UnderwaterFallback frame={underwaterFrame} streamUrl={underwaterStreamUrl} />
        </div>
        <div className="dashboard-grid__side">
          <SignalRail
            live={live ?? null}
            telemetryConnected={telemetry?.connected ?? null}
            telemetryStatus={telemetryRealtimeStatus}
          />
          <TelemetryPanel
            telemetry={navigation}
            updatedAt={telemetry?.captured_at ?? null}
          />
        </div>
      </section>

      <NavigationMap telemetry={navigation} />
      <MissionStage />

      <footer className="dashboard-shell__footer">
        <span>Surface channel: {liveRealtimeStatus}</span>
        <span>Fallback channel: {underwaterRealtimeStatus}</span>
        <span>Telemetry channel: {telemetryRealtimeStatus}</span>
      </footer>
    </main>
  )
}
