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

export function combineCameraFrames(
  surface: HTMLCanvasElement,
  underwater: HTMLCanvasElement,
): HTMLCanvasElement {
  if (
    surface.width <= 0 ||
    surface.height <= 0 ||
    underwater.width <= 0 ||
    underwater.height <= 0
  ) {
    throw new Error('Camera frame is not ready')
  }

  const height = Math.min(1080, Math.max(surface.height, underwater.height))
  const surfaceWidth = Math.round((surface.width / surface.height) * height)
  const underwaterWidth = Math.round(
    (underwater.width / underwater.height) * height,
  )
  const canvas = document.createElement('canvas')
  canvas.width = surfaceWidth + underwaterWidth
  canvas.height = height
  const context = requiredContext(canvas)
  context.fillStyle = '#050b0e'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(surface, 0, 0, surfaceWidth, height)
  context.drawImage(underwater, surfaceWidth, 0, underwaterWidth, height)
  return canvas
}

export function downloadCameraCapture(
  canvas: HTMLCanvasElement,
  capturedAt = new Date(),
): string {
  const timestamp = [
    capturedAt.getUTCFullYear(),
    twoDigits(capturedAt.getUTCMonth() + 1),
    twoDigits(capturedAt.getUTCDate()),
    '-',
    twoDigits(capturedAt.getUTCHours()),
    twoDigits(capturedAt.getUTCMinutes()),
    twoDigits(capturedAt.getUTCSeconds()),
  ].join('')
  const filename = `asv-capture-${timestamp}.jpg`
  const link = document.createElement('a')
  link.href = canvas.toDataURL('image/jpeg', 0.92)
  link.download = filename
  link.click()
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
