import { WarningCircle } from '@phosphor-icons/react'

import { DashboardShell } from './dashboard-shell'

import type { AsvDataMode } from '../lib/asv-data-mode'
import { useAsvLive } from '../lib/use-asv-live'
import { useUnderwaterBroadcast } from '../lib/use-underwater-broadcast'
import { useTelemetryBroadcast } from '../lib/use-telemetry-broadcast'

type DashboardClientProps = {
  asvId: string
  mode: AsvDataMode
}

export function DashboardClient({ asvId, mode }: DashboardClientProps) {
  const liveQuery = useAsvLive(asvId, mode)
  const underwater = useUnderwaterBroadcast(asvId, mode)
  const telemetry = useTelemetryBroadcast(asvId, mode)

  if (liveQuery.isPending) {
    return (
      <main className="dashboard-notice" aria-busy="true">
        <p className="eyebrow">ASV Ground Station</p>
        <h1>Synchronising telemetry</h1>
        <p>Loading the current ASV status.</p>
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
      telemetry={telemetry.telemetry}
      telemetryRealtimeStatus={telemetry.realtimeStatus}
      underwaterRealtimeStatus={underwater.realtimeStatus}
    />
  )
}
