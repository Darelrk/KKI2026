export const defaultAsvStreamUrls = {
  surface: 'https://monitor-kapal-pora-pora.web.id/stream/atas',
  underwater: 'https://monitor-kapal-pora-pora.web.id/stream/bawah',
} as const

type AsvStreamEnv = Partial<{
  VITE_ASV_SURFACE_STREAM_URL: string
  VITE_ASV_UNDERWATER_STREAM_URL: string
  VITE_ASV_VISION_WS_URL: string
}>

export function resolveAsvStreamUrls(env: AsvStreamEnv): {
  surface: string
  underwater: string
} {
  return {
    surface: env.VITE_ASV_SURFACE_STREAM_URL?.trim() || defaultAsvStreamUrls.surface,
    underwater: env.VITE_ASV_UNDERWATER_STREAM_URL?.trim() || defaultAsvStreamUrls.underwater,
  }
}

export function resolveAsvVisionWsUrl(env: AsvStreamEnv): string | null {
  return env.VITE_ASV_VISION_WS_URL?.trim() || null
}

export const asvStreamUrls = resolveAsvStreamUrls({
  VITE_ASV_SURFACE_STREAM_URL: import.meta.env.VITE_ASV_SURFACE_STREAM_URL,
  VITE_ASV_UNDERWATER_STREAM_URL: import.meta.env.VITE_ASV_UNDERWATER_STREAM_URL,
})

export const asvVisionWsUrl = resolveAsvVisionWsUrl({
  VITE_ASV_VISION_WS_URL: import.meta.env.VITE_ASV_VISION_WS_URL,
})
