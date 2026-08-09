import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRef } from 'react'

import { CameraStage } from './camera-stage'

import type {
  VisionMetadata,
  VisionMetadataCache,
} from '../lib/vision-metadata'
import type { CameraCaptureHandle } from '../lib/camera-capture'

const metadata = {
  schema_version: 1,
  asv_id: 'default',
  frame_id: 42,
  captured_at: '2026-07-20T10:00:00+00:00',
  source_width: 1280,
  source_height: 720,
  detections: [
    {
      track_id: null,
      label: 'buoy',
      confidence: 0.9,
      x: 0.4,
      y: 0.4,
      width: 0.2,
      height: 0.2,
    },
  ],
} satisfies VisionMetadata

const cache: VisionMetadataCache = { payload: metadata, receivedAtMs: 0 }

let frameCallbacks: FrameRequestCallback[]
type CanvasContextSpies = {
  clearRect: (...args: number[]) => void
  strokeRect: (...args: number[]) => void
  fillRect: (...args: number[]) => void
  drawImage: (...args: unknown[]) => void
  beginPath: () => void
  moveTo: (...args: number[]) => void
  lineTo: (...args: number[]) => void
  stroke: () => void
  fillText: (...args: unknown[]) => void
  fillStyle: string
  font: string
  strokeStyle: string
  lineWidth: number
}
let canvasContext: CanvasContextSpies

class CameraFakeSocket {
  static readonly OPEN = 1
  static readonly instances: CameraFakeSocket[] = []
  readonly url: string
  readyState = 0
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  send = vi.fn()
  close = vi.fn(() => {
    this.readyState = 3
  })

  constructor(url: string) {
    this.url = url
    CameraFakeSocket.instances.push(this)
  }

  open() {
    this.readyState = CameraFakeSocket.OPEN
    this.onopen?.(new Event('open'))
  }

  fail() {
    this.onerror?.(new Event('error'))
  }
}

class CameraFakePeer {
  static readonly instances: CameraFakePeer[] = []
  readonly addTransceiver = vi.fn()
  readonly createOffer = vi
    .fn()
    .mockResolvedValue({ type: 'offer', sdp: 'surface-local-sdp' })
  readonly setLocalDescription = vi.fn(
    async (description: RTCSessionDescriptionInit) => {
      this.localDescription = description
    },
  )
  readonly setRemoteDescription = vi.fn()
  readonly addIceCandidate = vi.fn()
  readonly close = vi.fn()
  localDescription: RTCSessionDescriptionInit | null = null
  iceGatheringState: RTCIceGatheringState = 'complete'
  connectionState: RTCPeerConnectionState = 'new'
  onicecandidate: ((event: RTCPeerConnectionIceEvent) => void) | null = null
  onicegatheringstatechange: (() => void) | null = null
  ontrack: ((event: RTCTrackEvent) => void) | null = null
  onconnectionstatechange: (() => void) | null = null

  constructor() {
    CameraFakePeer.instances.push(this)
  }
}

beforeEach(() => {
  frameCallbacks = []
  CameraFakeSocket.instances.length = 0
  CameraFakePeer.instances.length = 0
  vi.stubGlobal('WebSocket', CameraFakeSocket)
  vi.stubGlobal('RTCPeerConnection', CameraFakePeer)
  canvasContext = {
    clearRect: vi.fn(),
    strokeRect: vi.fn(),
    fillRect: vi.fn(),
    drawImage: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    fillText: vi.fn(),
    fillStyle: '',
    font: '',
    strokeStyle: '',
    lineWidth: 0,
  }
  vi.stubGlobal(
    'requestAnimationFrame',
    vi.fn((callback: FrameRequestCallback) => {
      frameCallbacks.push(callback)
      return frameCallbacks.length
    }),
  )
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    canvasContext as unknown as CanvasRenderingContext2D,
  )
  vi.spyOn(HTMLVideoElement.prototype, 'getBoundingClientRect').mockReturnValue(
    {
      x: 0,
      y: 0,
      top: 0,
      right: 800,
      bottom: 600,
      left: 0,
      width: 800,
      height: 600,
      toJSON: () => ({}),
    },
  )
  vi.spyOn(HTMLImageElement.prototype, 'getBoundingClientRect').mockReturnValue(
    {
      x: 0,
      y: 0,
      top: 0,
      right: 800,
      bottom: 600,
      left: 0,
      width: 800,
      height: 600,
      toJSON: () => ({}),
    },
  )
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

async function flushEffects() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

describe('CameraStage', () => {
  it('renders an autoplaying WebRTC video with a non-interactive canvas above it', async () => {
    render(
      <CameraStage
        streamUrl="https://camera.example.test/surface"
        metadataCache={cache}
        metadataStatus="connected"
      />,
    )
    const video = screen.getByLabelText('Live surface camera')
    const socket = CameraFakeSocket.instances[0]
    const peer = CameraFakePeer.instances[0]
    socket.open()
    await flushEffects()
    const stream = { id: 'surface-stream' } as unknown as MediaStream
    act(() => peer.ontrack?.({ streams: [stream] } as unknown as RTCTrackEvent))

    const canvas = document.querySelector('canvas')
    expect(video).toHaveAttribute('autoplay')
    expect(video).toHaveAttribute('playsinline')
    expect(video).toHaveProperty('muted', true)
    expect(video).toHaveProperty('srcObject', stream)
    expect(canvas).toHaveClass('camera-stage__overlay')
    expect(canvas).toHaveStyle({ pointerEvents: 'none' })
    expect(canvas?.parentElement?.firstElementChild).toBe(video)
  })

  it('draws normalized boxes with letterboxing from video dimensions', () => {
    render(
      <CameraStage
        streamUrl="https://camera.example.test/surface"
        metadataCache={cache}
        metadataStatus="connected"
      />,
    )
    const video = screen.getByLabelText('Live surface camera')
    Object.defineProperty(video, 'videoWidth', {
      configurable: true,
      value: 1280,
    })
    Object.defineProperty(video, 'videoHeight', {
      configurable: true,
      value: 720,
    })

    frameCallbacks[0](500)

    expect(canvasContext.clearRect).toHaveBeenCalled()
    expect(canvasContext.beginPath).not.toHaveBeenCalled()
    expect(canvasContext.moveTo).not.toHaveBeenCalled()
    expect(canvasContext.lineTo).not.toHaveBeenCalled()
    expect(canvasContext.stroke).not.toHaveBeenCalled()
    expect(canvasContext.strokeRect).toHaveBeenCalledWith(320, 255, 160, 90)
  })

  it('clears stale metadata while leaving the raw video mounted', () => {
    render(
      <CameraStage
        streamUrl="https://camera.example.test/surface"
        metadataCache={cache}
        metadataStatus="error"
      />,
    )

    frameCallbacks[0](1000)

    expect(canvasContext.clearRect).toHaveBeenCalled()
    expect(canvasContext.moveTo).not.toHaveBeenCalled()
    expect(canvasContext.lineTo).not.toHaveBeenCalled()
    expect(canvasContext.strokeRect).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Live surface camera')).toBeInTheDocument()
    expect(screen.getByText('Vision error')).toBeInTheDocument()
  })
  it('falls back to the configured MJPEG image on WebRTC error', () => {
    render(
      <CameraStage
        streamUrl="https://camera.example.test/surface"
        metadataCache={cache}
        metadataStatus="connected"
      />,
    )

    act(() => CameraFakeSocket.instances[0].fail())

    expect(
      screen.getByRole('img', { name: 'Live surface camera' }),
    ).toHaveAttribute('src', 'https://camera.example.test/surface')
  })
  it('restarts the player when the configured surface stream changes', () => {
    const rendered = render(
      <CameraStage
        streamUrl="https://camera.example.test/old-surface"
        metadataCache={cache}
        metadataStatus="connected"
      />,
    )
    act(() => CameraFakeSocket.instances[0].fail())
    fireEvent.error(screen.getByRole('img', { name: 'Live surface camera' }))

    rendered.rerender(
      <CameraStage
        streamUrl="https://camera.example.test/new-surface"
        metadataCache={cache}
        metadataStatus="connected"
      />,
    )

    expect(screen.getByLabelText('Live surface camera')).toBeInTheDocument()
    expect(CameraFakeSocket.instances).toHaveLength(2)
    expect(CameraFakePeer.instances).toHaveLength(2)
  })
  it('draws normalized boxes over the MJPEG fallback', () => {
    render(
      <CameraStage
        streamUrl="https://camera.example.test/surface"
        metadataCache={cache}
        metadataStatus="connected"
      />,
    )
    act(() => CameraFakeSocket.instances[0].fail())
    const image = screen.getByRole('img', { name: 'Live surface camera' })
    Object.defineProperty(image, 'naturalWidth', {
      configurable: true,
      value: 1280,
    })
    Object.defineProperty(image, 'naturalHeight', {
      configurable: true,
      value: 720,
    })

    frameCallbacks[0](500)

    expect(canvasContext.strokeRect).toHaveBeenCalledWith(320, 255, 160, 90)
  })
  it('captures the surface frame with fresh detection boxes', () => {
    vi.spyOn(performance, 'now').mockReturnValue(500)
    const captureRef = createRef<CameraCaptureHandle>()
    render(
      <CameraStage
        ref={captureRef}
        streamUrl="https://camera.example.test/surface"
        metadataCache={cache}
        metadataStatus="connected"
      />,
    )
    const video = screen.getByLabelText('Live surface camera')
    Object.defineProperties(video, {
      videoWidth: { configurable: true, value: 1280 },
      videoHeight: { configurable: true, value: 720 },
    })

    const captured = captureRef.current?.captureFrame()

    expect(captured).toBeInstanceOf(HTMLCanvasElement)
    expect(captured).toHaveProperty('width', 1280)
    expect(captured).toHaveProperty('height', 720)
    expect(canvasContext.drawImage).toHaveBeenCalledWith(
      video,
      0,
      0,
      1280,
      720,
    )
    expect(canvasContext.strokeRect).toHaveBeenCalledWith(512, 288, 256, 144)
  })
})
