import { act, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RemoteApp } from '../src/app'
import type { CaptureResponse } from '../src/lib/capture-request'
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
  it('owns one control channel and renders one capture button, one raw camera, plus two sliders', () => {
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
    expect(screen.getByRole('button', { name: 'Capture di Dashboard' })).toBeInTheDocument()
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

  it('reports a successful dashboard capture', async () => {
    const channel = makeChannel()
    const requestCapture = vi.fn(async () => ({ dashboards: 2 }))
    const origin = 'https://remote.example.test'

    render(
      <RemoteApp
        backendOrigin={origin}
        createControlChannel={() => channel}
        requestCapture={requestCapture}
        cameraProps={{ disabled: true }}
      />,
    )

    const button = screen.getByRole('button', { name: 'Capture di Dashboard' })
    const releaseCallsBeforeCapture = vi.mocked(channel.release).mock.calls.length
    await act(async () => {
      fireEvent.click(button)
    })

    expect(requestCapture).toHaveBeenCalledWith(origin)
    expect(screen.getByText('Capture dikirim ke dashboard')).toBeInTheDocument()
    expect(channel.engage).not.toHaveBeenCalled()
    expect(channel.setPwmPair).not.toHaveBeenCalled()
    expect(vi.mocked(channel.release)).toHaveBeenCalledTimes(releaseCallsBeforeCapture)
  })

  it('reports when no dashboard is open', async () => {
    const requestCapture = vi.fn(async () => ({ dashboards: 0 }))

    render(
      <RemoteApp
        backendOrigin="https://remote.example.test"
        createControlChannel={() => makeChannel()}
        requestCapture={requestCapture}
        cameraProps={{ disabled: true }}
      />,
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Capture di Dashboard' }))
    })

    expect(screen.getByText('Dashboard belum terbuka')).toBeInTheDocument()
  })

  it('reports when the capture backend is unavailable', async () => {
    const requestCapture = vi.fn(async () => {
      throw new Error('backend unavailable')
    })

    render(
      <RemoteApp
        backendOrigin="https://remote.example.test"
        createControlChannel={() => makeChannel()}
        requestCapture={requestCapture}
        cameraProps={{ disabled: true }}
      />,
    )

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Capture di Dashboard' }))
    })

    expect(screen.getByText('Backend capture tidak tersedia')).toBeInTheDocument()
  })

  it('suppresses a second click while capture is in flight', async () => {
    const channel = makeChannel()
    let resolveCapture: ((response: CaptureResponse) => void) | undefined
    const requestCapture = vi.fn(
      () => new Promise<CaptureResponse>((resolve) => {
        resolveCapture = resolve
      }),
    )

    render(
      <RemoteApp
        backendOrigin="https://remote.example.test"
        createControlChannel={() => channel}
        requestCapture={requestCapture}
        cameraProps={{ disabled: true }}
      />,
    )

    const button = screen.getByRole('button', { name: 'Capture di Dashboard' })
    await act(async () => {
      fireEvent.click(button)
      fireEvent.click(button)
    })

    expect(requestCapture).toHaveBeenCalledTimes(1)
    expect(button).toBeDisabled()

    await act(async () => {
      resolveCapture?.({ dashboards: 1 })
    })
    expect(button).not.toBeDisabled()
  })
})
