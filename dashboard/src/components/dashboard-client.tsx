import { WarningCircle } from '@phosphor-icons/react'

import { DashboardShell } from './dashboard-shell'

import type { AsvDataMode } from '../lib/asv-data-mode'
import { useAsvLive } from '../lib/use-asv-live'
import { useUnderwaterBroadcast } from '../lib/use-underwater-broadcast'
import { useTelemetryBroadcast } from '../lib/use-telemetry-broadcast'
import { useVisionMetadata } from '../lib/use-vision-metadata'

type DashboardClientProps = {
  asvId: string
  mode: AsvDataMode
}

export function DashboardClient({ asvId, mode }: DashboardClientProps) {
  const liveQuery = useAsvLive(asvId, mode)
  const underwater = useUnderwaterBroadcast(asvId, mode)
  const telemetry = useTelemetryBroadcast(asvId, mode)
  const vision = useVisionMetadata(asvId, mode)
  if (liveQuery.isPending) {
    return (
      <main className="dashboard-shell" aria-busy="true">
        <div className="dashboard-skeleton-bar" />
        <section className="dashboard-grid" aria-label="Loading ASV dashboard">
          <div className="dashboard-grid__cameras">
            <div className="dashboard-skeleton dashboard-skeleton--camera" />
            <div className="dashboard-skeleton dashboard-skeleton--camera" />
          </div>
          <div className="dashboard-grid__side">
            <div className="dashboard-skeleton dashboard-skeleton--panel" />
            <div className="dashboard-skeleton dashboard-skeleton--panel" />
          </div>
        </section>
        <div className="dashboard-skeleton dashboard-skeleton--map" />
      </main>
    )
  }

  if (liveQuery.isError) {
    return (
      <main className="dashboard-notice dashboard-notice--error" role="alert">
        <WarningCircle aria-hidden="true" weight="fill" size={40} />
        <p className="eyebrow">ASV Ground Station</p>
        <h1>Telemetry link unavailable</h1>
        <p>The dashboard could not retrieve the current ASV status.</p>
        <button type="button" onClick={() => void liveQuery.refetch()}>
          Retry connection
        </button>
      </main>
    )
  }

  return (
    <DashboardShell
      asvId={asvId}
      live={liveQuery.data}
      liveRealtimeStatus={liveQuery.realtimeStatus}
      underwaterFrame={underwater.frame}
      visionMetadataCache={vision.cache}
      visionMetadataStatus={vision.realtimeStatus}
      telemetry={telemetry.telemetry}
      telemetryRealtimeStatus={telemetry.realtimeStatus}
      underwaterRealtimeStatus={underwater.realtimeStatus}
    />
  )
}
