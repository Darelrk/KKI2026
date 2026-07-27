import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useGo2rtcVideo, type Go2rtcPlaybackMode } from './use-go2rtc-video'

import type { Go2rtcUrls } from './stream-urls'

const urls: Go2rtcUrls = {
  webrtcWs: 'wss://bridge.example.test/api/ws?src=atas',
  webrtcHttp: 'https://bridge.example.test/api/webrtc?src=atas',
  mse: 'https://bridge.example.test/api/stream.mp4?src=atas',
  mjpeg: 'https://bridge.example.test/stream/atas',
}

class FakeWebSocket {
  static readonly OPEN = 1
  static readonly instances: FakeWebSocket[] = []
  readonly sent: string[] = []
  readonly url: string
  readyState = 0
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  close = vi.fn(() => {
    this.readyState = 3
  })

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  send = vi.fn((message: string) => {
    this.sent.push(message)
  })

  open() {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.(new Event('open'))
  }

  message(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent)
  }

  fail() {
    this.onerror?.(new Event('error'))
  }
}

class FakePeerConnection {
  static readonly instances: FakePeerConnection[] = []
  readonly addTransceiver = vi.fn()
  readonly createOffer = vi
    .fn()
    .mockResolvedValue({ type: 'offer', sdp: 'local-sdp' })
  readonly setLocalDescription = vi.fn(
    async (description: RTCSessionDescriptionInit) => {
      this.localDescription = description
    },
  )
  readonly setRemoteDescription = vi.fn(
    async (description: RTCSessionDescriptionInit) => {
      this.remoteDescription = description
    },
  )
  readonly addIceCandidate = vi.fn()
  readonly close = vi.fn()
  localDescription: RTCSessionDescriptionInit | null = null
  remoteDescription: RTCSessionDescriptionInit | null = null
  connectionState: RTCPeerConnectionState = 'new'
  iceGatheringState: RTCIceGatheringState = 'complete'
  onicecandidate: ((event: RTCPeerConnectionIceEvent) => void) | null = null
  ontrack: ((event: RTCTrackEvent) => void) | null = null
  onconnectionstatechange: (() => void) | null = null

  constructor() {
    FakePeerConnection.instances.push(this)
  }
}

function Harness({
  enabled = true,
  fallbackUrl = 'legacy-1',
}: {
  enabled?: boolean
  fallbackUrl?: string
}) {
  const player = useGo2rtcVideo({ urls, enabled, fallbackUrl })
  return (
    <>
      <video ref={player.videoRef} aria-label="test video" />
      <output data-testid="mode">{player.mode}</output>
      <output data-testid="mjpeg-failed">{String(player.mjpegFailed)}</output>
      <button type="button" onClick={player.onMjpegError}>
        legacy-error
      </button>
    </>
  )
}

async function flushEffects() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

describe('useGo2rtcVideo', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeWebSocket.instances.length = 0
    FakePeerConnection.instances.length = 0
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.stubGlobal('RTCPeerConnection', FakePeerConnection)
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('creates a receive-only video offer through the go2rtc socket', async () => {
    render(<Harness />)
    const socket = FakeWebSocket.instances[0]
    const peer = FakePeerConnection.instances[0]

    expect(socket.url).toBe(urls.webrtcWs)
    socket.open()
    await flushEffects()

    expect(peer.addTransceiver).toHaveBeenCalledWith('video', {
      direction: 'recvonly',
    })
    expect(socket.send).toHaveBeenCalledWith(
      JSON.stringify({ type: 'webrtc/offer', value: 'local-sdp' }),
    )
  })

  it('exchanges local and remote ICE candidates', async () => {
    render(<Harness />)
    const socket = FakeWebSocket.instances[0]
    const peer = FakePeerConnection.instances[0]
    socket.open()
    await flushEffects()

    const localCandidate = {
      candidate: 'candidate:local',
    } as unknown as RTCIceCandidate
    act(() =>
      peer.onicecandidate?.({
        candidate: localCandidate,
      } as unknown as RTCPeerConnectionIceEvent),
    )
    socket.message({
      type: 'webrtc/candidate',
      value: 'candidate:remote',
    })
    await flushEffects()

    expect(socket.send).toHaveBeenCalledWith(
      JSON.stringify({
        type: 'webrtc/candidate',
        value: 'candidate:local',
      }),
    )
    expect(peer.addIceCandidate).toHaveBeenCalledWith({
      candidate: 'candidate:remote',
    })
  })

  it('attaches the answered remote stream and enters WebRTC mode', async () => {
    render(<Harness />)
    const socket = FakeWebSocket.instances[0]
    const peer = FakePeerConnection.instances[0]
    socket.open()
    await flushEffects()

    socket.message({ type: 'webrtc/answer', value: 'remote-sdp' })
    await flushEffects()
    const stream = { id: 'remote-stream' } as MediaStream
    act(() => peer.ontrack?.({ streams: [stream] } as unknown as RTCTrackEvent))

    expect(peer.setRemoteDescription).toHaveBeenCalledWith({
      type: 'answer',
      sdp: 'remote-sdp',
    })
    expect(screen.getByLabelText('test video')).toHaveProperty(
      'srcObject',
      stream,
    )
    expect(screen.getByTestId('mode')).toHaveTextContent('webrtc')
  })

  it('falls back immediately when browser WebRTC support is missing', async () => {
    vi.stubGlobal('RTCPeerConnection', undefined)
    render(<Harness />)
    await flushEffects()

    expect(screen.getByTestId('mode')).toHaveTextContent('mjpeg')
    expect(FakeWebSocket.instances).toHaveLength(0)
  })

  it('falls back after three seconds and ignores late signaling', async () => {
    render(<Harness />)
    const socket = FakeWebSocket.instances[0]
    const peer = FakePeerConnection.instances[0]
    act(() => vi.advanceTimersByTime(3000))
    expect(screen.getByTestId('mode')).toHaveTextContent('mjpeg')
    expect(socket.close).toHaveBeenCalled()
    expect(peer.close).toHaveBeenCalled()

    const stream = { id: 'late-stream' } as MediaStream
    act(() => peer.ontrack?.({ streams: [stream] } as unknown as RTCTrackEvent))
    expect(screen.getByTestId('mode')).toHaveTextContent('mjpeg')
    expect(screen.getByLabelText('test video')).not.toHaveProperty(
      'srcObject',
      stream,
    )
  })

  it('closes the socket and peer when unmounted', () => {
    const rendered = render(<Harness />)
    const socket = FakeWebSocket.instances[0]
    const peer = FakePeerConnection.instances[0]

    rendered.unmount()

    expect(socket.close).toHaveBeenCalled()
    expect(peer.close).toHaveBeenCalled()
  })

  it('tracks the MJPEG failure after the legacy image errors', () => {
    render(<Harness />)
    expect(screen.getByTestId('mode')).toHaveTextContent(
      'connecting' satisfies Go2rtcPlaybackMode,
    )
    expect(screen.getByTestId('mjpeg-failed')).toHaveTextContent('false')
    act(() => screen.getByRole('button', { name: 'legacy-error' }).click())
    expect(screen.getByTestId('mjpeg-failed')).toHaveTextContent('true')
  })

  it('restarts the player when the configured fallback URL changes', () => {
    const rendered = render(<Harness fallbackUrl="legacy-1" />)
    const firstSocket = FakeWebSocket.instances[0]
    const firstPeer = FakePeerConnection.instances[0]

    rendered.rerender(<Harness fallbackUrl="legacy-2" />)

    expect(firstSocket.close).toHaveBeenCalled()
    expect(firstPeer.close).toHaveBeenCalled()
    expect(FakeWebSocket.instances).toHaveLength(2)
    expect(FakePeerConnection.instances).toHaveLength(2)
    expect(screen.getByTestId('mode')).toHaveTextContent('connecting')
  })
})
