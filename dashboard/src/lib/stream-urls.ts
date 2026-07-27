export const defaultAsvBridgeUrl = 'https://monitor-kapal-pora-pora.web.id'

export type Go2rtcSource = 'atas' | 'bawah'

export type Go2rtcUrls = {
  webrtcWs: string
  webrtcHttp: string
  mse: string
  mjpeg: string
}

export function getGo2rtcUrls(
  bridgeUrl: string,
  source: Go2rtcSource,
): Go2rtcUrls {
  const parsed = new URL(bridgeUrl.trim())
  const basePath = parsed.pathname.replace(/\/+$/, '')
  const httpPrefix = `${parsed.origin.replace(/\/+$/, '')}${basePath}`
  const wsProtocol = parsed.protocol === 'https:' ? 'wss:' : 'ws:'
  const encodedSource = encodeURIComponent(source)

  return {
    webrtcWs: `${wsProtocol}//${parsed.host}${basePath}/api/ws?src=${encodedSource}`,
    webrtcHttp: `${httpPrefix}/api/webrtc?src=${encodedSource}`,
    mse: `${httpPrefix}/api/stream.mp4?src=${encodedSource}`,
    mjpeg: `${httpPrefix}/stream/${encodedSource}`,
  }
}

export const defaultAsvStreamUrls = {
  surface: 'https://monitor-kapal-pora-pora.web.id/stream/atas',
  underwater: 'https://monitor-kapal-pora-pora.web.id/stream/bawah',
} as const

export const defaultAsvVisionWsUrl = 'wss://monitor-kapal-pora-pora.web.id'

type AsvStreamEnv = Partial<{
  VITE_ASV_BRIDGE_URL: string
  VITE_ASV_SURFACE_STREAM_URL: string
  VITE_ASV_UNDERWATER_STREAM_URL: string
  VITE_ASV_VISION_WS_URL: string
  VITE_ASV_TELEMETRY_WS_URL: string
}>

export function resolveAsvStreamUrls(env: AsvStreamEnv): {
  surface: string
  underwater: string
} {
  return {
    surface:
      env.VITE_ASV_SURFACE_STREAM_URL?.trim() || defaultAsvStreamUrls.surface,
    underwater:
      env.VITE_ASV_UNDERWATER_STREAM_URL?.trim() ||
      defaultAsvStreamUrls.underwater,
  }
}

export function resolveAsvBridgeUrl(env: AsvStreamEnv): string {
  return (
    env.VITE_ASV_BRIDGE_URL?.trim().replace(/\/+$/, '') || defaultAsvBridgeUrl
  )
}

export function resolveAsvVisionWsUrl(env: AsvStreamEnv): string {
  return env.VITE_ASV_VISION_WS_URL?.trim() || defaultAsvVisionWsUrl
}
export function resolveAsvTelemetryWsUrl(env: AsvStreamEnv): string {
  return (
    env.VITE_ASV_TELEMETRY_WS_URL?.trim() ||
    env.VITE_ASV_VISION_WS_URL?.trim() ||
    defaultAsvVisionWsUrl
  )
}

export const asvBridgeUrl = resolveAsvBridgeUrl({
  VITE_ASV_BRIDGE_URL: import.meta.env.VITE_ASV_BRIDGE_URL,
})

export const asvGo2rtcUrls = {
  surface: getGo2rtcUrls(asvBridgeUrl, 'atas'),
  underwater: getGo2rtcUrls(asvBridgeUrl, 'bawah'),
} as const

export const asvStreamUrls = resolveAsvStreamUrls({
  VITE_ASV_SURFACE_STREAM_URL: import.meta.env.VITE_ASV_SURFACE_STREAM_URL,
  VITE_ASV_UNDERWATER_STREAM_URL: import.meta.env
    .VITE_ASV_UNDERWATER_STREAM_URL,
})

export const asvVisionWsUrl = resolveAsvVisionWsUrl({
  VITE_ASV_VISION_WS_URL: import.meta.env.VITE_ASV_VISION_WS_URL,
})
export const asvTelemetryWsUrl = resolveAsvTelemetryWsUrl({
  VITE_ASV_TELEMETRY_WS_URL: import.meta.env.VITE_ASV_TELEMETRY_WS_URL,
  VITE_ASV_VISION_WS_URL: import.meta.env.VITE_ASV_VISION_WS_URL,
})
