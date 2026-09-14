import { useEffect, useState } from 'react'

import { asvTelemetryWsUrl } from './stream-urls'

import type { AsvDataMode } from './asv-data-mode'

export type CaptureSocketLike = {
  readonly readyState: number
  onmessage: ((event: MessageEvent) => void) | null
  onclose: ((event: CloseEvent) => void) | null
  onerror: ((event: Event) => void) | null
  close: () => void
}

type CaptureWebSocketFactory = (url: string) => CaptureSocketLike

const reconnectDelayMs = 2000

const defaultWebSocketFactory: CaptureWebSocketFactory = (url) =>
  new WebSocket(url)

export function useCaptureRequests(
  asvId: string,
  mode: AsvDataMode,
  webSocketFactory: CaptureWebSocketFactory = defaultWebSocketFactory,
): number {
  const [requestCount, setRequestCount] = useState(0)

  useEffect(() => {
    if (mode !== 'direct') return

    let cancelled = false
    let socket: CaptureSocketLike | null = null
    let retryTimer: number | null = null

    const scheduleReconnect = () => {
      if (cancelled) return
      if (retryTimer !== null) window.clearTimeout(retryTimer)
      retryTimer = window.setTimeout(connect, reconnectDelayMs)
    }

    const connect = () => {
      if (cancelled) return
      try {
        socket = webSocketFactory(
          `${asvTelemetryWsUrl.replace(/\/+$/, '')}/ws/capture/${asvId}`,
        )
      } catch {
        scheduleReconnect()
        return
      }

      const currentSocket = socket
      currentSocket.onmessage = (event) => {
        if (cancelled) return
        try {
          const payload = JSON.parse(event.data)
          if (payload?.type === 'capture_request') {
            setRequestCount((count) => count + 1)
          }
        } catch {
          // Ignore malformed capture events.
        }
      }
      currentSocket.onclose = () => {
        scheduleReconnect()
      }
      currentSocket.onerror = () => {
        currentSocket.close()
      }
    }

    connect()

    return () => {
      cancelled = true
      if (retryTimer !== null) window.clearTimeout(retryTimer)
      socket?.close()
    }
  }, [asvId, mode, webSocketFactory])

  return requestCount
}
