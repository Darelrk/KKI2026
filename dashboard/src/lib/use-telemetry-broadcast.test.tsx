import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { fetchDirectTelemetry } from './direct-live'
import { getSupabaseBrowser } from './supabase-browser'
import { ensureSupabaseRealtimeAuth } from './supabase-realtime-auth'
import { useTelemetryBroadcast } from './use-telemetry-broadcast'

vi.mock('./direct-live', () => ({ fetchDirectTelemetry: vi.fn() }))
vi.mock('./supabase-browser', () => ({ getSupabaseBrowser: vi.fn() }))
vi.mock('./supabase-realtime-auth', () => ({
  ensureSupabaseRealtimeAuth: vi.fn(),
}))

describe('useTelemetryBroadcast', () => {
  it('returns deterministic fixture telemetry', () => {
    const { result } = renderHook(() =>
      useTelemetryBroadcast('fixture-asv', 'fixture'),
    )

    expect(result.current.telemetry).toMatchObject({
      connected: true,
      heading_deg: 144,
      speed_mps: 0.6,
      position: {
        latitude: -6.1224,
        longitude: 106.8226,
      },
      track: [
        { latitude: -6.1234, longitude: 106.821 },
        { latitude: -6.123, longitude: 106.8218 },
        { latitude: -6.1224, longitude: 106.8226 },
      ],
    })
    expect(result.current.realtimeStatus).toBe('fixture')
  })

  it('subscribes to private telemetry Broadcast and keeps only valid payloads', async () => {
    const telemetry = {
      connected: true,
      position: {
        latitude: -1.7,
        longitude: 102.25,
        captured_at: '2026-07-20T09:30:00.000Z',
      },
      heading_deg: 144,
      speed_mps: 0,
      captured_at: '2026-07-20T09:30:00.000Z',
      heartbeat_at: '2026-07-20T09:29:59.000Z',
      track: [],
    }
    const updatedTelemetry = {
      ...telemetry,
      heading_deg: 145,
      captured_at: '2026-07-20T09:30:01.000Z',
    }
    const channel = {
      on: vi.fn(),
      subscribe: vi.fn(),
    }
    channel.on.mockReturnValue(channel)
    channel.subscribe.mockReturnValue(channel)
    const client = {
      channel: vi.fn(() => channel),
      removeChannel: vi.fn(),
    }

    vi.mocked(getSupabaseBrowser).mockReturnValue(client as never)
    vi.mocked(ensureSupabaseRealtimeAuth).mockResolvedValue()

    const { result, unmount } = renderHook(() =>
      useTelemetryBroadcast('default', 'supabase'),
    )

    await waitFor(() => {
      expect(client.channel).toHaveBeenCalledWith('asv-telemetry:default', {
        config: { private: true },
      })
      expect(channel.on).toHaveBeenCalledWith(
        'broadcast',
        { event: 'telemetry' },
        expect.any(Function),
      )
    })

    const onStatus = channel.subscribe.mock.calls[0]?.[0]
    if (typeof onStatus !== 'function') {
      throw new Error('Expected a telemetry subscription status callback')
    }
    onStatus('SUBSCRIBED')

    const onTelemetry = channel.on.mock.calls[0]?.[2]
    if (typeof onTelemetry !== 'function') {
      throw new Error('Expected a telemetry Broadcast callback')
    }
    onTelemetry({ payload: updatedTelemetry })

    await waitFor(() => {
      expect(result.current.telemetry).toEqual(updatedTelemetry)
      expect(result.current.realtimeStatus).toBe('connected')
    })

    onTelemetry({ payload: { ...updatedTelemetry, heading_deg: 'invalid' } })
    expect(result.current.telemetry).toEqual(updatedTelemetry)

    unmount()

    expect(client.removeChannel).toHaveBeenCalledWith(channel)
  })

  it('polls direct telemetry without creating a Supabase channel', async () => {
    vi.mocked(getSupabaseBrowser).mockClear()
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

    expect(fetchDirectTelemetry).toHaveBeenCalledWith(
      'https://monitor-kapal-pora-pora.web.id',
      expect.any(AbortSignal),
    )
    expect(getSupabaseBrowser).not.toHaveBeenCalled()
    unmount()
  })
})
