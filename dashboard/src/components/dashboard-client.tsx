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

  return (
    <DashboardShell
      asvId={asvId}
      mode={mode}
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
