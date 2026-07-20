import { describe, expect, it, vi } from 'vitest'

import { fetchAsvLive } from './asv-live-query'

describe('fetchAsvLive', () => {
  it('selects and validates the requested ASV row', async () => {
    const maybeSingle = vi.fn().mockResolvedValue({
      data: {
        id: 'default',
        online: true,
        model_status: 'running',
        camera: 'surface',
        stream_url: 'https://camera.example.test/stream/surface.mjpg',
        run_id: 'run-2026-07-20',
        updated_at: '2026-07-20T09:30:00.000Z',
      },
      error: null,
    })
    const eq = vi.fn(() => ({ maybeSingle }))
    const select = vi.fn(() => ({ eq }))
    const from = vi.fn(() => ({ select }))

    const result = await fetchAsvLive({ from } as never, 'default')

    expect(result).toMatchObject({ id: 'default', model_status: 'running' })
    expect(from).toHaveBeenCalledWith('asv_live')
    expect(select).toHaveBeenCalledWith(
      'id, online, model_status, camera, stream_url, run_id, updated_at',
    )
    expect(eq).toHaveBeenCalledWith('id', 'default')
  })

  it('returns null when the requested ASV has no live row', async () => {
    const maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null })
    const eq = vi.fn(() => ({ maybeSingle }))
    const select = vi.fn(() => ({ eq }))
    const from = vi.fn(() => ({ select }))

    await expect(fetchAsvLive({ from } as never, 'missing-asv')).resolves.toBeNull()
  })

  it('propagates a database read failure', async () => {
    const maybeSingle = vi
      .fn()
      .mockResolvedValue({ data: null, error: new Error('database unavailable') })
    const eq = vi.fn(() => ({ maybeSingle }))
    const select = vi.fn(() => ({ eq }))
    const from = vi.fn(() => ({ select }))

    await expect(fetchAsvLive({ from } as never, 'default')).rejects.toThrow(
      'database unavailable',
    )
  })
})
