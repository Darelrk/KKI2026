import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchDirectTelemetry } from './direct-live'
import { kolamDeliSite } from './mission-site'
import { useTelemetryBroadcast } from './use-telemetry-broadcast'

vi.mock('./direct-live', () => ({ fetchDirectTelemetry: vi.fn() }))

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useTelemetryBroadcast', () => {
  it('returns deterministic fixture telemetry', () => {
    const { result } = renderHook(() =>
      useTelemetryBroadcast('fixture-asv', 'fixture'),
    )

    expect(result.current.telemetry).toMatchObject({
      connected: true,
      heading_deg: expect.any(Number),
      speed_mps: 0,
      position: {
        latitude: expect.closeTo(kolamDeliSite.center.latitude, 0.01),
        longitude: expect.closeTo(kolamDeliSite.center.longitude, 0.01),
      },
    })
    expect(result.current.telemetry?.track).toHaveLength(3)
    expect(result.current.realtimeStatus).toBe('fixture')
  })

  it('connects direct telemetry via websocket or falls back to REST polling', async () => {
    vi.stubGlobal(
      'WebSocket',
      vi.fn(() => {
        throw new Error('WebSocket unavailable in this unit test')
      }),
    )
    vi.mocked(fetchDirectTelemetry).mockResolvedValue({
      connected: true,
      position: {
        latitude: -6.2,
        longitude: 106.8,
        captured_at: '2026-07-24T10:00:00.000Z',
      },
      heading_deg: 90,
      speed_mps: 1.2,
      captured_at: '2026-07-24T10:00:00.000Z',
      heartbeat_at: '2026-07-24T10:00:00.000Z',
      track: [],
    })

    const { result, unmount } = renderHook(() =>
      useTelemetryBroadcast('default', 'direct'),
    )

    await waitFor(() => {
      expect(result.current.realtimeStatus).toBe('connected')
    })

    unmount()
  })
})
