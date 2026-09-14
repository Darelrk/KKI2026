import { defineHandler } from 'nitro'

import { asvBridgeUrl } from '../../../../src/lib/stream-urls'
import { readFirstJpeg } from '../../../../src/lib/mjpeg-frame'

const streamSources = {
  surface: 'atas',
  underwater: 'bawah',
} as const

export default defineHandler(async (event) => {
  const source =
    streamSources[event.context.params?.source as keyof typeof streamSources]
  if (!source) return new Response('Unknown camera source', { status: 404 })

  try {
    const upstream = await fetch(`${asvBridgeUrl}/stream/${source}`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(5_000),
    })
    if (!upstream.ok || !upstream.body) {
      throw new Error('Camera stream is unavailable')
    }

    const jpeg = await readFirstJpeg(upstream.body)
    return new Response(new Uint8Array(jpeg).buffer, {
      headers: {
        'Cache-Control': 'no-store',
        'Content-Type': 'image/jpeg',
      },
    })
  } catch {
    return new Response('Camera frame is unavailable', { status: 503 })
  }
})
