import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { asvTelemetryWsUrl } from './stream-urls'
import { useCaptureRequests } from './use-capture-requests'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  readonly url: string
  readonly readyState = 1
  readonly close = vi.fn()
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  message(data: string) {
    this.onmessage?.({ data } as MessageEvent)
  }

  closeFromServer() {
    this.onclose?.({} as CloseEvent)
  }

  fail() {
    this.onerror?.({} as Event)
  }
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeWebSocket.instances = []
  vi.stubGlobal('WebSocket', FakeWebSocket)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('useCaptureRequests', () => {
  it('opens the capture socket and counts capture requests only', () => {
    const { result } = renderHook(() => useCaptureRequests('default', 'direct'))

    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(FakeWebSocket.instances[0].url).toBe(
      `${asvTelemetryWsUrl.replace(/\/+$/, '')}/ws/capture/default`,
    )

    act(() => {
      FakeWebSocket.instances[0].message('{"type":"capture_request"}')
      FakeWebSocket.instances[0].message('{"type":"telemetry"}')
      FakeWebSocket.instances[0].message('{malformed')
    })

    expect(result.current).toBe(1)
  })

  it('does not open a socket in fixture mode', () => {
    renderHook(() => useCaptureRequests('fixture-asv', 'fixture'))

    expect(FakeWebSocket.instances).toHaveLength(0)
  })

  it('reconnects two seconds after the server closes the socket', () => {
    renderHook(() => useCaptureRequests('default', 'direct'))
    const firstSocket = FakeWebSocket.instances[0]

    act(() => firstSocket.closeFromServer())
    act(() => vi.advanceTimersByTime(1999))
    expect(FakeWebSocket.instances).toHaveLength(1)

    act(() => vi.advanceTimersByTime(1))
    expect(FakeWebSocket.instances).toHaveLength(2)
    expect(FakeWebSocket.instances[1].url).toBe(firstSocket.url)
  })

  it('closes the socket and cancels a pending reconnect on unmount', () => {
    const { unmount } = renderHook(() =>
      useCaptureRequests('default', 'direct'),
    )
    const firstSocket = FakeWebSocket.instances[0]

    act(() => firstSocket.closeFromServer())
    unmount()
    act(() => vi.advanceTimersByTime(2000))

    expect(firstSocket.close).toHaveBeenCalledOnce()
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it('closes a socket after an error', () => {
    renderHook(() => useCaptureRequests('default', 'direct'))
    const socket = FakeWebSocket.instances[0]

    act(() => socket.fail())

    expect(socket.close).toHaveBeenCalledOnce()
  })
})
