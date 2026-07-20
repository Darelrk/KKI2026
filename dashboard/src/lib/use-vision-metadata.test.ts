import { createElement } from 'react'
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useVisionMetadata } from './use-vision-metadata'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  readonly url: string
  readonly close = vi.fn()
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  open() {
    this.onopen?.()
  }

  message(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }

  closeFromServer() {
    this.onclose?.()
  }
}

const validPayload = {
  schema_version: 1,
  asv_id: 'default',
  frame_id: 42,
  captured_at: '2026-07-20T10:00:00+00:00',
  source_width: 1280,
  source_height: 720,
  detections: [],
}

function Probe({ mode }: { mode: 'fixture' | 'supabase' }) {
  const { cache, realtimeStatus } = useVisionMetadata('default', mode, 'wss://bridge.test')
  return createElement(
    'output',
    { 'data-testid': 'vision-state' },
    `${realtimeStatus}:${cache?.payload.frame_id ?? 'none'}`,
  )
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

describe('useVisionMetadata', () => {
  it('uses fixture metadata without opening a WebSocket', () => {
    render(createElement(Probe, { mode: 'fixture' }))

    expect(screen.getByTestId('vision-state')).toHaveTextContent('fixture:1')
    expect(FakeWebSocket.instances).toHaveLength(0)
  })

  it('keeps the last valid payload when an invalid message arrives', () => {
    render(createElement(Probe, { mode: 'supabase' }))
    const socket = FakeWebSocket.instances[0]
    act(() => socket.open())
    act(() => socket.message(validPayload))

    expect(screen.getByTestId('vision-state')).toHaveTextContent('connected:42')

    act(() => socket.message({ schema_version: 2 }))

    expect(screen.getByTestId('vision-state')).toHaveTextContent('connected:42')
  })

  it('clears stale metadata and retries with one socket timer', () => {
    const { unmount } = render(createElement(Probe, { mode: 'supabase' }))
    const firstSocket = FakeWebSocket.instances[0]
    act(() => firstSocket.open())
    act(() => firstSocket.message(validPayload))

    act(() => vi.advanceTimersByTime(1000))
    expect(screen.getByTestId('vision-state')).toHaveTextContent('connected:none')

    act(() => firstSocket.closeFromServer())
    act(() => vi.advanceTimersByTime(1000))
    expect(FakeWebSocket.instances).toHaveLength(2)
    expect(FakeWebSocket.instances[1].url).toBe('wss://bridge.test/ws/vision/default')

    unmount()
    expect(FakeWebSocket.instances[1].close).toHaveBeenCalledOnce()
  })
})
