import { useEffect, useRef, useState } from 'react'

import { MissionStage } from './mission-stage'
import { NavigationMap } from './navigation-map'
import { TelemetryPanel } from './telemetry-panel'
import { CameraStage } from './camera-stage'
import { ConnectionBar } from './connection-bar'
import { SignalRail } from './signal-rail'
import { UnderwaterFallback } from './underwater-fallback'

import { emptyNavigationTelemetry } from '../lib/navigation-types'
import { missionTelemetryAt } from '../lib/mission-site'
import { asvStreamUrls } from '../lib/stream-urls'
import { useMissionSimulation } from '../lib/use-mission-simulation'
import { downloadCameraCapture } from '../lib/camera-capture'

import type { AsvLive, UnderwaterFrame } from '../lib/asv-types'
import type { AsvDataMode } from '../lib/asv-data-mode'
import type { AsvTelemetry } from '../lib/asv-telemetry'
import type { VisionMetadataCache } from '../lib/vision-metadata'
import type { VisionRealtimeStatus } from '../lib/use-vision-metadata'
import type { ConnectionStatus } from './connection-bar'

type DashboardShellProps = {
  mode?: AsvDataMode
  live: AsvLive | null | undefined
  telemetry?: AsvTelemetry | null
  telemetryRealtimeStatus?: ConnectionStatus
  underwaterFrame: UnderwaterFrame | null
  visionMetadataCache?: VisionMetadataCache | null
  visionMetadataStatus?: VisionRealtimeStatus
  surfaceStreamUrl?: string | null
  underwaterStreamUrl?: string | null
  captureRequestCount?: number
}

export function DashboardShell({
  mode = 'direct',
  live,
  telemetry = null,
  telemetryRealtimeStatus = 'connecting',
  underwaterFrame,
  visionMetadataCache = null,
  visionMetadataStatus = 'error',
  surfaceStreamUrl = asvStreamUrls.surface,
  underwaterStreamUrl = asvStreamUrls.underwater,
  captureRequestCount = 0,
}: DashboardShellProps) {
  const [captureState, setCaptureState] = useState<
    'idle' | 'capturing' | 'saved' | 'error'
  >('idle')
  const [captureFilename, setCaptureFilename] = useState('')
  const simulationTelemetryActive = mode === 'fixture'
  const simulation = useMissionSimulation({
    autoStart: mode === 'fixture',
  })
  const fixtureStartedAtMs = useRef(Date.now())
  const displayTelemetry = simulationTelemetryActive
    ? missionTelemetryAt({
        progress: simulation.progress,
        elapsedMs: simulation.elapsedMs,
        status: simulation.status,
        startedAtMs: fixtureStartedAtMs.current,
      })
    : telemetry
  const displayTelemetryStatus: ConnectionStatus = simulationTelemetryActive
    ? 'fixture'
    : telemetryRealtimeStatus
  const navigation = displayTelemetry ?? emptyNavigationTelemetry
  const displayLive =
    mode === 'fixture' && live && displayTelemetry
      ? { ...live, updated_at: displayTelemetry.captured_at }
      : live
  const displayUnderwaterFrame =
    mode === 'fixture' && underwaterFrame && displayTelemetry
      ? { ...underwaterFrame, captured_at: displayTelemetry.captured_at }
      : underwaterFrame

  const captureBothCameras = () => {
    if (captureState === 'capturing') return
    setCaptureState('capturing')
    setCaptureFilename('')
    const capturedAt = new Date()

    void Promise.allSettled([
      downloadCameraCapture('surface', capturedAt),
      downloadCameraCapture('underwater', capturedAt),
    ]).then((results) => {
      const filenames = results.flatMap((result) =>
        result.status === 'fulfilled' ? [result.value] : [],
      )
      setTimeout(() => {
        if (filenames.length === 0) {
          setCaptureState('error')
          return
        }
        setCaptureFilename(filenames.join(', '))
        setCaptureState('saved')
      }, 320)
    })
  }

  const latestCaptureRef = useRef(captureBothCameras)
  latestCaptureRef.current = captureBothCameras
  const lastRequestCount = useRef(captureRequestCount)

  useEffect(() => {
    if (captureRequestCount === lastRequestCount.current) return
    lastRequestCount.current = captureRequestCount
    latestCaptureRef.current()
  }, [captureRequestCount])

  return (
    <main className="dashboard-shell">
      <ConnectionBar
        online={displayTelemetry?.connected ?? false}
        status={simulationTelemetryActive ? null : displayTelemetryStatus}
      />

      <section
        className="dashboard-grid"
        aria-label="ASV operational dashboard"
      >
        <div className="dashboard-grid__cameras">
          <CameraStage
            capturing={captureState === 'capturing'}
            streamUrl={surfaceStreamUrl}
            metadataCache={visionMetadataCache}
            metadataStatus={visionMetadataStatus}
          />
          <UnderwaterFallback
            capturing={captureState === 'capturing'}
            frame={displayUnderwaterFrame}
            streamUrl={underwaterStreamUrl}
          />
        </div>
        <div className="dashboard-grid__side">
          <SignalRail
            live={displayLive ?? null}
            telemetryConnected={telemetry?.connected ?? null}
            telemetryStatus={displayTelemetryStatus}
          />
          <TelemetryPanel
            telemetry={navigation}
            updatedAt={displayTelemetry?.captured_at ?? null}
            captureState={captureState}
            captureFilename={captureFilename}
          />
        </div>
      </section>

      <NavigationMap
        telemetry={navigation}
        simulation={mode === 'fixture' ? simulation : undefined}
        previewMode={mode === 'fixture'}
      />
      <MissionStage simulation={simulation} />
    </main>
  )
}
