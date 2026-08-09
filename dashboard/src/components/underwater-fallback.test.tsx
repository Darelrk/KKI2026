import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRef } from 'react'

import { UnderwaterFallback } from './underwater-fallback'

import type { UnderwaterFrame } from '../lib/asv-types'
import type { CameraCaptureHandle } from '../lib/camera-capture'

const frame = {
  mime: 'image/jpeg',
  data_base64: '/9j/abc=',
  captured_at: '2026-07-20T10:00:00+00:00',
  frame_id: 'frame-42',
} satisfies UnderwaterFrame

const canvasContext = {
  fillStyle: '',
  fillRect: vi.fn(),
  drawImage: vi.fn(),
  save: vi.fn(),
  translate: vi.fn(),
  rotate: vi.fn(),
  restore: vi.fn(),
}

class UnderwaterFakeSocket {
  static readonly OPEN = 1
  static readonly instances: UnderwaterFakeSocket[] = []
  readyState = 0
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  close = vi.fn(() => {
    this.readyState = 3
  })
  send = vi.fn()

  constructor(readonly url: string) {
    UnderwaterFakeSocket.instances.push(this)
  }

  fail() {
    this.onerror?.(new Event('error'))
  }
}

class UnderwaterFakePeer {
  static readonly instances: UnderwaterFakePeer[] = []
  addTransceiver = vi.fn()
  createOffer = vi.fn().mockResolvedValue({ type: 'offer', sdp: 'local-sdp' })
  setLocalDescription = vi.fn()
  setRemoteDescription = vi.fn()
  addIceCandidate = vi.fn()
  close = vi.fn()
  localDescription: RTCSessionDescriptionInit | null = null
  iceGatheringState: RTCIceGatheringState = 'complete'
  connectionState: RTCPeerConnectionState = 'new'
  onicecandidate: ((event: RTCPeerConnectionIceEvent) => void) | null = null
  onicegatheringstatechange: (() => void) | null = null
  ontrack: ((event: RTCTrackEvent) => void) | null = null
  onconnectionstatechange: (() => void) | null = null

  constructor() {
    UnderwaterFakePeer.instances.push(this)
  }
}

beforeEach(() => {
  UnderwaterFakeSocket.instances.length = 0
  UnderwaterFakePeer.instances.length = 0
  vi.stubGlobal('WebSocket', UnderwaterFakeSocket)
  vi.stubGlobal('RTCPeerConnection', UnderwaterFakePeer)
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    canvasContext as unknown as CanvasRenderingContext2D,
  )
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('UnderwaterFallback', () => {
  it('renders an inline muted video while WebRTC is connecting', () => {
    render(
      <UnderwaterFallback
        frame={frame}
        streamUrl="https://camera.example.test/bawah"
      />,
    )

    const video = screen.getByLabelText('Live underwater action camera')
    expect(video).toHaveAttribute('autoplay')
    expect(video).toHaveAttribute('playsinline')
    expect(video).toHaveProperty('muted', true)
  })

  it('falls back to the configured underwater MJPEG stream', () => {
    render(
      <UnderwaterFallback
        frame={frame}
        streamUrl="https://camera.example.test/bawah"
      />,
    )

    act(() => UnderwaterFakeSocket.instances[0].fail())

    expect(
      screen.getByRole('img', { name: 'Live underwater action camera' }),
    ).toHaveAttribute('src', 'https://camera.example.test/bawah')
  })

  it('keeps the latest frame when the underwater MJPEG fallback errors', () => {
    render(
      <UnderwaterFallback
        frame={frame}
        streamUrl="https://camera.example.test/bawah"
      />,
    )
    act(() => UnderwaterFakeSocket.instances[0].fail())
    fireEvent.error(
      screen.getByRole('img', { name: 'Live underwater action camera' }),
    )

    expect(
      screen.getByRole('img', { name: 'Latest underwater frame' }),
    ).toHaveAttribute('src', 'data:image/jpeg;base64,/9j/abc=')
    expect(screen.getByText('frame-42')).toBeInTheDocument()
  })
  it('captures the underwater frame in its displayed orientation', () => {
    const captureRef = createRef<CameraCaptureHandle>()
    render(
      <UnderwaterFallback ref={captureRef} frame={frame} streamUrl={null} />,
    )
    const image = screen.getByRole('img', { name: 'Latest underwater frame' })
    Object.defineProperties(image, {
      naturalWidth: { configurable: true, value: 640 },
      naturalHeight: { configurable: true, value: 360 },
    })

    const captured = captureRef.current?.captureFrame()

    expect(captured).toBeInstanceOf(HTMLCanvasElement)
    expect(canvasContext.translate).toHaveBeenCalledWith(640, 360)
    expect(canvasContext.rotate).toHaveBeenCalledWith(Math.PI)
  })
  it('marks the underwater feed for the shared capture animation', () => {
    render(
      <UnderwaterFallback
        capturing
        frame={frame}
        streamUrl={null}
      />,
    )

    expect(
      screen.getByRole('region', { name: 'Underwater action camera' }),
    ).toHaveClass('camera-capture--active')
  })
})
