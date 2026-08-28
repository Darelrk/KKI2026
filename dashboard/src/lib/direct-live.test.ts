import { describe, expect, it, vi } from 'vitest'

import {
  fetchControlMode,
  fetchDirectAsvLive,
  fetchDirectTelemetry,
  putControlMode,
} from './direct-live'

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

  it('fetches and updates control mode as JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ mode: 'MANUAL' }), { status: 200 }),
        )
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ mode: 'AUTONOMOUS' }), { status: 200 }),
        ),
    )

    await expect(
      fetchControlMode('https://bridge.example.test///'),
    ).resolves.toBe('MANUAL')
    await expect(
      putControlMode('https://bridge.example.test///', 'AUTONOMOUS'),
    ).resolves.toBe('AUTONOMOUS')

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      'https://bridge.example.test/api/control/mode',
      expect.objectContaining({
        cache: 'no-store',
        headers: { accept: 'application/json' },
      }),
    )
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      'https://bridge.example.test/api/control/mode',
      expect.objectContaining({
        body: JSON.stringify({ mode: 'AUTONOMOUS' }),
        cache: 'no-store',
        headers: {
          accept: 'application/json',
          'content-type': 'application/json',
        },
        method: 'PUT',
      }),
    )
  })

  it('reports a forbidden control mode update with its status', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('forbidden', { status: 403 })),
    )

    await expect(
      putControlMode('https://bridge.example.test', 'AUTONOMOUS'),
    ).rejects.toThrow('Direct bridge mode request failed: 403')
  })

  it('rejects a failed bridge response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('offline', { status: 503 })))

    await expect(fetchDirectTelemetry('https://bridge.example.test')).rejects.toThrow(
      'Direct bridge request failed: 503',
    )
  })
})
