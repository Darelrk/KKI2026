import { describe, expect, it } from 'vitest'

import { asvLiveSchema } from './asv-types'

describe('asvLiveSchema', () => {
  it('accepts a running surface camera status', () => {
    const status = {
      id: 'default',
      online: true,
      model_status: 'running',
      camera: 'surface',
      stream_url: 'https://camera.example.test/stream/surface.mjpg',
      run_id: 'run-2026-07-20',
      updated_at: '2026-07-20T09:30:00.000Z',
    }

    expect(asvLiveSchema.parse(status)).toEqual(status)
  })

  it('rejects a live status without an ASV identifier', () => {
    expect(
      asvLiveSchema.safeParse({
        online: true,
        model_status: 'running',
        camera: 'surface',
        stream_url: null,
        run_id: null,
        updated_at: '2026-07-20T09:30:00.000Z',
      }).success,
    ).toBe(false)
  })

  it('rejects an unknown model status', () => {
    expect(
      asvLiveSchema.safeParse({
        id: 'default',
        online: true,
        model_status: 'calibrating',
        camera: 'surface',
        stream_url: null,
        run_id: null,
        updated_at: '2026-07-20T09:30:00.000Z',
      }).success,
    ).toBe(false)
  })
})
