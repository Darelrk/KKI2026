import { useEffect, useState } from 'react'

import { getAsvDataMode } from './asv-data-mode'
import { fixtureVisionMetadata } from './fixture-data'
import { asvVisionWsUrl } from './stream-urls'
import { visionMetadataSchema } from './vision-metadata'

import type { AsvDataMode } from './asv-data-mode'
import type { VisionMetadataCache } from './vision-metadata'

export type VisionRealtimeStatus = 'fixture' | 'connecting' | 'connected' | 'error'

const staleAfterMs = 1000

export function useVisionMetadata(
  asvId: string,
  mode: AsvDataMode = getAsvDataMode(import.meta.env.VITE_ASV_DATA_MODE),
  wsBaseUrl = asvVisionWsUrl || '',
) {
  const [cache, setCache] = useState<VisionMetadataCache | null>(() =>
    mode === 'fixture'
      ? { payload: fixtureVisionMetadata, receivedAtMs: performance.now() }
      : null,
  )
  const [realtimeStatus, setRealtimeStatus] = useState<VisionRealtimeStatus>(
    mode === 'fixture' ? 'fixture' : 'connecting',
  )

  useEffect(() => {
    if (!cache) {
      return
    }
    const remaining = Math.max(
      0,
      staleAfterMs - (performance.now() - cache.receivedAtMs),
    )
    const timer = window.setTimeout(() => {
      setCache((current) => (current === cache ? null : current))
    }, remaining)
    return () => window.clearTimeout(timer)
  }, [cache])

  useEffect(() => {
    if (mode === 'fixture') {
      setCache({ payload: fixtureVisionMetadata, receivedAtMs: performance.now() })
      setRealtimeStatus('fixture')
      return
    }

    setCache(null)
    if (!wsBaseUrl) {
      setRealtimeStatus('error')
      return
    }

    let cancelled = false
    let socket: WebSocket | null = null
    let retryTimer: number | undefined
    let retryAttempt = 0

    const connect = () => {
      if (cancelled) {
        return
      }
      setRealtimeStatus('connecting')
      socket = new WebSocket(
        `${wsBaseUrl.replace(/\/$/, '')}/ws/vision/${encodeURIComponent(asvId)}`,
      )
      socket.onopen = () => {
        if (!cancelled) {
          retryAttempt = 0
          setRealtimeStatus('connected')
        }
      }
      socket.onmessage = (event) => {
        if (cancelled || typeof event.data !== 'string') {
          return
        }
        try {
          const parsed = visionMetadataSchema.safeParse(JSON.parse(event.data))
          if (parsed.success) {
            setCache({ payload: parsed.data, receivedAtMs: performance.now() })
          }
        } catch {
          // Invalid wire data never replaces the last valid cache.
        }
      }
      socket.onerror = () => {
        if (!cancelled) {
          setRealtimeStatus('error')
          socket?.close()
        }
      }
      socket.onclose = () => {
        if (cancelled) {
          return
        }
        setRealtimeStatus('connecting')
        const delay = Math.min(1000 * 2 ** retryAttempt, 8000)
        retryAttempt += 1
        retryTimer = window.setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      cancelled = true
      if (retryTimer !== undefined) {
        window.clearTimeout(retryTimer)
      }
      socket?.close()
    }
  }, [asvId, mode, wsBaseUrl])

  return { cache, realtimeStatus }
}
