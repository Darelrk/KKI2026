import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchDirectAsvLive, fetchDirectTelemetry } from './direct-live'

afterEach(() => {
  vi.unstubAllGlobals()
})

const liveStatus = {
  id: 'default',
  online: true,
  model_status: 'running',
  camera: 'surface',
  stream_url: null,
  run_id: 'run-1',
  updated_at: '2026-07-23T10:00:00.000Z',
}

const telemetry = {
  connected: false,
  position: null,
  heading_deg: 0,
  speed_mps: 0,
  captured_at: '2026-07-23T10:00:00.000Z',
  heartbeat_at: '2026-07-23T10:00:00.000Z',
  track: [],
}

describe('direct bridge client', () => {
  it('fetches ASV live status and telemetry from the direct bridge', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(liveStatus), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(telemetry), { status: 200 }),
      )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      fetchDirectAsvLive('https://bridge.example.test', 'default'),
    ).resolves.toEqual(liveStatus)
    await expect(
      fetchDirectTelemetry('https://bridge.example.test'),
    ).resolves.toEqual(telemetry)

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      'https://bridge.example.test/api/status',
      expect.objectContaining({ cache: 'no-store' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'https://bridge.example.test/api/telemetry',
      expect.objectContaining({ cache: 'no-store' }),
    )
  })

  it('throws when the bridge status does not match the expected ASV', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(liveStatus), { status: 200 }),
      ),
    )

    await expect(
      fetchDirectAsvLive('https://bridge.example.test', 'other'),
    ).rejects.toThrow('Direct bridge returned ASV default, expected other')
  })

  it('throws when the bridge request fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('nope', { status: 403 })),
    )

    await expect(
      fetchDirectTelemetry('https://bridge.example.test'),
    ).rejects.toThrow('Direct bridge request failed: 403')
  })
})
