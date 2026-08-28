import { DashboardShell } from './dashboard-shell'

import type { AsvDataMode } from '../lib/asv-data-mode'
import { useAsvLive } from '../lib/use-asv-live'
import { useUnderwaterBroadcast } from '../lib/use-underwater-broadcast'
import { useTelemetryBroadcast } from '../lib/use-telemetry-broadcast'
import { useVisionMetadata } from '../lib/use-vision-metadata'
import { useControlMode } from '../lib/use-control-mode'

type DashboardClientProps = {
  asvId: string
  mode: AsvDataMode
}
export function DashboardClient({ asvId, mode }: DashboardClientProps) {
  const liveQuery = useAsvLive(asvId, mode)
  const underwater = useUnderwaterBroadcast(asvId, mode)
  const telemetry = useTelemetryBroadcast(asvId, mode)
  const vision = useVisionMetadata(asvId, mode)
  const controlMode = useControlMode(asvId, mode)

  return (
    <DashboardShell
      mode={mode}
      live={liveQuery.data}
      underwaterFrame={underwater.frame}
      visionMetadataCache={vision.cache}
      visionMetadataStatus={vision.realtimeStatus}
      telemetry={telemetry.telemetry}
      telemetryRealtimeStatus={telemetry.realtimeStatus}
      controlMode={controlMode.mode}
      controlModeCanEdit={controlMode.canEdit}
      controlModeLoading={controlMode.isLoading}
      controlModeReadOnly={controlMode.readOnly}
      controlModeUpdating={controlMode.isUpdating}
      controlModeError={controlMode.error}
      onControlModeChange={controlMode.updateMode}
    />
  )
}
