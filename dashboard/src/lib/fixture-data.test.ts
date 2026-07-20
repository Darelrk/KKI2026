import { describe, expect, it } from 'vitest'

import { fixtureTelemetry, fixtureUnderwaterFrame, getFixtureAsvLive } from './fixture-data'

describe('ASV fixture data', () => {
  it('returns a running surface status for the requested ASV', () => {
    expect(getFixtureAsvLive('demo-asv')).toMatchObject({
      id: 'demo-asv',
      online: true,
      model_status: 'running',
      camera: 'surface',
      stream_url: null,
    })
  })

  it('provides a bounded JPEG underwater fallback frame', () => {
    expect(fixtureUnderwaterFrame).toMatchObject({
      mime: 'image/jpeg',
      frame_id: 'fixture-underwater-001',
    })
    expect(fixtureUnderwaterFrame.data_base64.length).toBeLessThanOrEqual(180_000)
    const jpeg = Buffer.from(fixtureUnderwaterFrame.data_base64, 'base64')
    expect(jpeg.subarray(0, 2).toString('hex')).toBe('ffd8')
    expect(jpeg.subarray(-2).toString('hex')).toBe('ffd9')
  })
  it('provides a synthetic three-point GPS fixture path', () => {
    expect(fixtureTelemetry.track).toHaveLength(3)
    expect(fixtureTelemetry.position).toEqual(fixtureTelemetry.track.at(-1))
    expect(fixtureTelemetry.heading_deg).toBe(144)
    expect(fixtureTelemetry.speed_mps).toBeGreaterThanOrEqual(0)
  })

})
