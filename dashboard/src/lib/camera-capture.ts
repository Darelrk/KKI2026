export type CameraCaptureHandle = {
  captureFrame: () => HTMLCanvasElement
}

export function captureMediaFrame(
  media: HTMLVideoElement | HTMLImageElement,
  { rotate180 = false }: { rotate180?: boolean } = {},
): HTMLCanvasElement {
  const width =
    media instanceof HTMLVideoElement ? media.videoWidth : media.naturalWidth
  const height =
    media instanceof HTMLVideoElement ? media.videoHeight : media.naturalHeight
  if (width <= 0 || height <= 0) {
    throw new Error('Camera frame is not ready')
  }

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = requiredContext(canvas)
  context.fillStyle = '#050b0e'
  context.fillRect(0, 0, width, height)

  if (rotate180) {
    context.save()
    context.translate(width, height)
    context.rotate(Math.PI)
  }
  context.drawImage(media, 0, 0, width, height)
  if (rotate180) context.restore()
  return canvas
}

export type CameraCaptureSource = 'surface' | 'underwater'

export async function downloadCameraCapture(
  source: CameraCaptureSource,
  capturedAt = new Date(),
): Promise<string> {
  const response = await fetch(`/api/camera-frame/${source}`, {
    cache: 'no-store',
  })
  if (!response.ok) throw new Error('Camera frame is unavailable')

  const timestamp = [
    capturedAt.getUTCFullYear(),
    twoDigits(capturedAt.getUTCMonth() + 1),
    twoDigits(capturedAt.getUTCDate()),
    '-',
    twoDigits(capturedAt.getUTCHours()),
    twoDigits(capturedAt.getUTCMinutes()),
    twoDigits(capturedAt.getUTCSeconds()),
  ].join('')
  const filename = `asv-${source}-${timestamp}.jpg`
  const objectUrl = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
  return filename
}

function requiredContext(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas capture is unavailable')
  return context
}

function twoDigits(value: number): string {
  return String(value).padStart(2, '0')
}
