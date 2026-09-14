import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { captureMediaFrame, downloadCameraCapture } from './camera-capture'

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

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
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

  it('downloads a source-specific jpeg from the same-origin snapshot route', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(new Blob(['jpeg'], { type: 'image/jpeg' }), {
          status: 200,
        }),
      )
    const createObjectURL = vi.fn().mockReturnValue('blob:capture')
    const revokeObjectURL = vi.fn()
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined)
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })

    const filename = await downloadCameraCapture(
      'surface',
      new Date('2026-08-09T12:34:56Z'),
    )
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(filename).toBe('asv-surface-20260809-123456.jpg')
    expect(fetchMock).toHaveBeenCalledWith('/api/camera-frame/surface', {
      cache: 'no-store',
    })
    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(click).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:capture')
  })

  it('rejects media without a decoded frame', () => {
    expect(() => captureMediaFrame(document.createElement('video'))).toThrow(
      'Camera frame is not ready',
    )
  })
})
