import { useRef, useState } from 'react'

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
import {
  combineCameraFrames,
  downloadCameraCapture,
} from '../lib/camera-capture'

import type { AsvLive, UnderwaterFrame } from '../lib/asv-types'
import type { AsvDataMode } from '../lib/asv-data-mode'
import type { AsvTelemetry } from '../lib/asv-telemetry'
import type { VisionMetadataCache } from '../lib/vision-metadata'
import type { VisionRealtimeStatus } from '../lib/use-vision-metadata'
import type { ConnectionStatus } from './connection-bar'
import type { CameraCaptureHandle } from '../lib/camera-capture'


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
}: DashboardShellProps) {
  const surfaceCaptureRef = useRef<CameraCaptureHandle>(null)
  const underwaterCaptureRef = useRef<CameraCaptureHandle>(null)
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
    requestAnimationFrame(() => {
      try {
        const surface = surfaceCaptureRef.current?.captureFrame()
        const underwater = underwaterCaptureRef.current?.captureFrame()
        if (!surface || !underwater) {
          throw new Error('Camera frame is not ready')
        }
        const filename = downloadCameraCapture(
          combineCameraFrames(surface, underwater),
        )
        setTimeout(() => {
          setCaptureFilename(filename)
          setCaptureState('saved')
        }, 320)
      } catch {
        setTimeout(() => setCaptureState('error'), 320)
      }
    })
  }

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
            ref={surfaceCaptureRef}
            capturing={captureState === 'capturing'}
            streamUrl={surfaceStreamUrl}
            metadataCache={visionMetadataCache}
            metadataStatus={visionMetadataStatus}
          />
          <UnderwaterFallback
            ref={underwaterCaptureRef}
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
            onCapture={captureBothCameras}
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
