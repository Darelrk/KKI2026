import { useEffect, useMemo, useState } from 'react'
import {
  ControlChannel,
  createControlChannel,
  type ControlChannelLike,
  type ControlChannelOptions,
} from './lib/control-channel'
import { RemoteControlPanel } from './components/remote-control-panel'
import {
  RemoteSurfaceCamera,
  type RemoteSurfaceCameraProps,
} from './components/remote-surface-camera'

export interface RemoteAppProps {
  backendOrigin: string
  asvId?: string
  createControlChannel?: (options: ControlChannelOptions) => ControlChannelLike
  cameraProps?: Omit<RemoteSurfaceCameraProps, 'backendOrigin'>
}

export function RemoteApp({
  backendOrigin,
  asvId = 'default',
  createControlChannel: makeControlChannel = createControlChannel,
  cameraProps,
}: RemoteAppProps) {
  const [available, setAvailable] = useState(false)
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

  return (
    <main className="remote-app">
      <RemoteSurfaceCamera backendOrigin={backendOrigin} {...cameraProps} />
      <RemoteControlPanel channel={channel} disabled={!available} />
    </main>
  )
}

export { ControlChannel }
