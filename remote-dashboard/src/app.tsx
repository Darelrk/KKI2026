import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ControlChannel,
  createControlChannel,
  type ControlChannelLike,
  type ControlChannelOptions,
} from './lib/control-channel'
import {
  requestDashboardCapture,
  type CaptureResponse,
} from './lib/capture-request'
import { RemoteControlPanel } from './components/remote-control-panel'
import {
  RemoteSurfaceCamera,
  type RemoteSurfaceCameraProps,
} from './components/remote-surface-camera'

export interface RemoteAppProps {
  backendOrigin: string
  asvId?: string
  createControlChannel?: (options: ControlChannelOptions) => ControlChannelLike
  requestCapture?: (backendOrigin: string) => Promise<CaptureResponse>
  cameraProps?: Omit<RemoteSurfaceCameraProps, 'backendOrigin'>
}

export function RemoteApp({
  backendOrigin,
  asvId = 'default',
  createControlChannel: makeControlChannel = createControlChannel,
  requestCapture: requestCaptureImpl = requestDashboardCapture,
  cameraProps,
}: RemoteAppProps) {
  const [available, setAvailable] = useState(false)
  const [captureInFlight, setCaptureInFlight] = useState(false)
  const [captureStatus, setCaptureStatus] = useState<string | null>(null)
  const captureInFlightRef = useRef(false)
  const channel = useMemo(() => {
    let created: ControlChannelLike
    created = makeControlChannel({
      backendOrigin,
      asvId,
      onStateChange: (state) => setAvailable(state === 'open'),
    })
    return created
  }, [asvId, backendOrigin, makeControlChannel])

  useEffect(() => {
    setAvailable(channel.isAvailable !== false)
    channel.connect()
    return () => channel.close()
  }, [channel])

  const requestCapture = async () => {
    if (captureInFlightRef.current) return
    captureInFlightRef.current = true
    setCaptureInFlight(true)
    setCaptureStatus(null)

    try {
      const { dashboards } = await requestCaptureImpl(backendOrigin)
      setCaptureStatus(dashboards > 0 ? 'Capture dikirim ke dashboard' : 'Dashboard belum terbuka')
    } catch {
      setCaptureStatus('Backend capture tidak tersedia')
    } finally {
      captureInFlightRef.current = false
      setCaptureInFlight(false)
    }
  }

  return (
    <main className="remote-app">
      <RemoteSurfaceCamera backendOrigin={backendOrigin} {...cameraProps} />
      <RemoteControlPanel channel={channel} disabled={!available} />
      <section className="remote-capture" aria-label="Dashboard capture">
        <button type="button" onClick={requestCapture} disabled={captureInFlight}>
          Capture di Dashboard
        </button>
        {captureStatus ? <p role="status" aria-live="polite">{captureStatus}</p> : null}
      </section>
    </main>
  )
}

export { ControlChannel }
