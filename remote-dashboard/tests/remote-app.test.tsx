import { act, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RemoteApp } from '../src/app'
import type {
  ControlChannelLike,
  ControlChannelOptions,
  ControlChannelState,
} from '../src/lib/control-channel'
import type { RemoteSurfaceCameraProps } from '../src/components/remote-surface-camera'

const makeChannel = (): ControlChannelLike => ({
  connect: vi.fn(),
  close: vi.fn(),
  engage: vi.fn(),
  release: vi.fn(),
  setPwmPair: vi.fn(),
  isAvailable: true,
})

describe('RemoteApp', () => {
  it('owns one control channel and renders only one raw camera plus two sliders', () => {
    const channel = makeChannel()
    const cameraProps: RemoteSurfaceCameraProps = { disabled: true }
    const createChannel = vi.fn(() => channel)
    const { container, unmount } = render(
      <RemoteApp
        backendOrigin="https://remote.example.test"
        asvId="default"
        createControlChannel={createChannel}
        cameraProps={cameraProps}
      />,
    )

    expect(createChannel).toHaveBeenCalledTimes(1)
    expect(channel.connect).toHaveBeenCalledTimes(1)
    expect(container.querySelectorAll('video, img')).toHaveLength(1)
    expect(container.querySelectorAll('input[type="range"]')).toHaveLength(2)
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.queryByText(/telemetry|status|latency|ack|autonomous|underwater|vision|model|overlay/i)).toBeNull()
    unmount()
    expect(channel.close).toHaveBeenCalledTimes(1)
  })

  it('disables both sliders while control reconnects and re-enables after open', () => {
    const channel = makeChannel()
    let onStateChange: ((state: ControlChannelState) => void) | undefined
    const createChannel = vi.fn((options: ControlChannelOptions) => {
      onStateChange = options.onStateChange
      return channel
    })
    const { container } = render(
      <RemoteApp
        backendOrigin="https://remote.example.test"
        asvId="default"
        createControlChannel={createChannel}
        cameraProps={{ disabled: true }}
      />,
    )

    const sliders = container.querySelectorAll('input[type="range"]')
    expect(sliders).toHaveLength(2)
    expect(sliders[0]).not.toBeDisabled()
    expect(sliders[1]).not.toBeDisabled()

    act(() => onStateChange?.('reconnecting'))
    expect(sliders[0]).toBeDisabled()
    expect(sliders[1]).toBeDisabled()

    act(() => onStateChange?.('open'))
    expect(sliders[0]).not.toBeDisabled()
    expect(sliders[1]).not.toBeDisabled()
  })
})
