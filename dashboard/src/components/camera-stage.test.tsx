import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CameraStage } from './camera-stage'

import type { VisionMetadata, VisionMetadataCache } from '../lib/vision-metadata'

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
  fillText: (...args: unknown[]) => void
  strokeStyle: string
  lineWidth: number
}
let canvasContext: CanvasContextSpies

beforeEach(() => {
  frameCallbacks = []
  canvasContext = {
    clearRect: vi.fn(),
    strokeRect: vi.fn(),
    fillText: vi.fn(),
    strokeStyle: '',
    lineWidth: 0,
  }
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => {
    frameCallbacks.push(callback)
    return frameCallbacks.length
  }))
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    canvasContext as unknown as CanvasRenderingContext2D,
  )
  vi.spyOn(HTMLImageElement.prototype, 'getBoundingClientRect').mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    right: 800,
    bottom: 600,
    left: 0,
    width: 800,
    height: 600,
    toJSON: () => ({}),
  })
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('CameraStage', () => {
  it('keeps the raw image source and layers a non-interactive canvas above it', () => {
    render(
      <CameraStage
        streamUrl="https://camera.example.test/surface"
        metadataCache={cache}
        metadataStatus="connected"
      />,
    )

    const image = screen.getByRole('img', { name: 'Live surface camera' })
    const canvas = document.querySelector('canvas')
    expect(image).toHaveAttribute('src', 'https://camera.example.test/surface')
    expect(canvas).toHaveClass('camera-stage__overlay')
    expect(canvas).toHaveStyle({ pointerEvents: 'none' })
    expect(canvas?.parentElement?.firstElementChild).toBe(image)
  })

  it('draws normalized boxes with letterboxing without changing image src', () => {
    render(
      <CameraStage
        streamUrl="https://camera.example.test/surface"
        metadataCache={cache}
        metadataStatus="connected"
      />,
    )
    const image = screen.getByRole('img', { name: 'Live surface camera' })
    Object.defineProperty(image, 'naturalWidth', { configurable: true, value: 1280 })
    Object.defineProperty(image, 'naturalHeight', { configurable: true, value: 720 })

    frameCallbacks[0](500)

    expect(canvasContext.clearRect).toHaveBeenCalled()
    expect(canvasContext.strokeRect).toHaveBeenCalledWith(320, 255, 160, 90)
    expect(image).toHaveAttribute('src', 'https://camera.example.test/surface')
  })

  it('clears stale metadata while leaving the raw image mounted', () => {
    render(
      <CameraStage
        streamUrl="https://camera.example.test/surface"
        metadataCache={cache}
        metadataStatus="error"
      />,
    )

    frameCallbacks[0](1000)

    expect(canvasContext.clearRect).toHaveBeenCalled()
    expect(canvasContext.strokeRect).not.toHaveBeenCalled()
    expect(screen.getByRole('img', { name: 'Live surface camera' })).toBeInTheDocument()
    expect(screen.getByText('Metadata channel error')).toBeInTheDocument()
  })
})
