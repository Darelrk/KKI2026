import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  captureMediaFrame,
  combineCameraFrames,
  downloadCameraCapture,
} from './camera-capture'

const context = {
  fillStyle: '',
  fillRect: vi.fn(),
  drawImage: vi.fn(),
  save: vi.fn(),
  translate: vi.fn(),
  rotate: vi.fn(),
  restore: vi.fn(),
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    context as unknown as CanvasRenderingContext2D,
  )
})

describe('camera capture', () => {
  it('captures a ready media frame at native dimensions', () => {
    const media = document.createElement('video')
    Object.defineProperties(media, {
      videoWidth: { configurable: true, value: 1280 },
      videoHeight: { configurable: true, value: 720 },
    })

    const canvas = captureMediaFrame(media)

    expect(canvas.width).toBe(1280)
    expect(canvas.height).toBe(720)
    expect(context.drawImage).toHaveBeenCalledWith(media, 0, 0, 1280, 720)
  })

  it('rotates an underwater frame by 180 degrees', () => {
    const media = document.createElement('img')
    Object.defineProperties(media, {
      naturalWidth: { configurable: true, value: 640 },
      naturalHeight: { configurable: true, value: 360 },
    })

    captureMediaFrame(media, { rotate180: true })

    expect(context.translate).toHaveBeenCalledWith(640, 360)
    expect(context.rotate).toHaveBeenCalledWith(Math.PI)
  })

  it('combines both cameras side by side at one bounded height', () => {
    const surface = document.createElement('canvas')
    surface.width = 1280
    surface.height = 720
    const underwater = document.createElement('canvas')
    underwater.width = 640
    underwater.height = 360

    const combined = combineCameraFrames(surface, underwater)

    expect(combined.width).toBe(2560)
    expect(combined.height).toBe(720)
    expect(context.drawImage).toHaveBeenNthCalledWith(
      1,
      surface,
      0,
      0,
      1280,
      720,
    )
    expect(context.drawImage).toHaveBeenNthCalledWith(
      2,
      underwater,
      1280,
      0,
      1280,
      720,
    )
  })

  it('downloads one timestamped jpeg', () => {
    const canvas = document.createElement('canvas')
    const toDataUrl = vi
      .spyOn(canvas, 'toDataURL')
      .mockReturnValue('data:image/jpeg;base64,capture')
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined)

    const filename = downloadCameraCapture(
      canvas,
      new Date('2026-08-09T12:34:56Z'),
    )

    expect(filename).toBe('asv-capture-20260809-123456.jpg')
    expect(toDataUrl).toHaveBeenCalledWith('image/jpeg', 0.92)
    expect(click).toHaveBeenCalledOnce()
  })

  it('rejects media without a decoded frame', () => {
    expect(() => captureMediaFrame(document.createElement('video'))).toThrow(
      'Camera frame is not ready',
    )
  })
})
