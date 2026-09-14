export interface Go2RtcUrls {
  signaling: string
  webrtc: string
  streamMp4: string
  mjpeg: string
}

export function normalizeVideoOrigin(origin: string): string {
  const value = new URL(origin)
  if (!['http:', 'https:', 'ws:', 'wss:'].includes(value.protocol)) {
    throw new Error('backend origin must use http, https, ws, or wss')
  }
  if (value.protocol === 'ws:') value.protocol = 'http:'
  if (value.protocol === 'wss:') value.protocol = 'https:'
  return value.origin
}

function signalingOrigin(origin: string): string {
  const value = new URL(origin)
  if (!['http:', 'https:', 'ws:', 'wss:'].includes(value.protocol)) {
    throw new Error('backend origin must use http, https, ws, or wss')
  }
  if (value.protocol === 'http:') value.protocol = 'ws:'
  if (value.protocol === 'https:') value.protocol = 'wss:'
  return value.origin
}

export function buildGo2RtcUrls(origin: string): Go2RtcUrls {
  const httpOrigin = normalizeVideoOrigin(origin)
  const wsOrigin = signalingOrigin(origin)
  return {
    signaling: new URL('/api/ws?src=atas', wsOrigin).toString(),
    webrtc: new URL('/api/webrtc', httpOrigin).toString(),
    streamMp4: new URL('/api/stream.mp4', httpOrigin).toString(),
    mjpeg: new URL('/api/stream.mjpeg?src=atas', httpOrigin).toString(),
  }
}
