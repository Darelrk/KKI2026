import { describe, expect, it, vi } from 'vitest'

import { fetchDirectAsvLive, fetchDirectTelemetry } from './direct-live'

const liveStatus = {
  id: 'default',
  online: true,
  model_status: 'running',
  camera: 'surface',
  stream_url: 'https://camera.example.test/stream.mjpg',
  run_id: 'run-001',
  updated_at: '2026-07-24T10:00:00.000Z',
}

const telemetry = {
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
}

describe('direct live API', () => {
  it('fetches and validates status from the bridge', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(liveStatus), { status: 200 }),
      ),
    )

    await expect(
      fetchDirectAsvLive('https://bridge.example.test', 'default'),
    ).resolves.toEqual(liveStatus)
    expect(fetch).toHaveBeenCalledWith(
      'https://bridge.example.test/api/status',
      expect.objectContaining({ cache: 'no-store' }),
    )
  })

  it('fetches and validates telemetry from the bridge', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(telemetry), { status: 200 }),
      ),
    )

    await expect(
      fetchDirectTelemetry('https://bridge.example.test'),
    ).resolves.toEqual(telemetry)
  })

  it('rejects a failed bridge response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('offline', { status: 503 })))

    await expect(fetchDirectTelemetry('https://bridge.example.test')).rejects.toThrow(
      'Direct bridge request failed: 503',
    )
  })
})
