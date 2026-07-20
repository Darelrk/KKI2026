import { describe, expect, it } from 'vitest'

import {
  isVisionMetadataFresh,
  projectVisionBox,
  visionMetadataSchema,
} from './vision-metadata'

const validPayload = {
  schema_version: 1,
  asv_id: 'default',
  frame_id: 42,
  captured_at: '2026-07-20T10:00:00+00:00',
  source_width: 1280,
  source_height: 720,
  detections: [
    {
      track_id: null,
      label: 'buoy',
      confidence: 0.9,
      x: 0.4,
      y: 0.4,
      width: 0.2,
      height: 0.2,
    },
  ],
}

describe('visionMetadataSchema', () => {
  it('accepts a valid normalized detection payload', () => {
    expect(visionMetadataSchema.safeParse(validPayload).success).toBe(true)
  })

  it.each([
    ['unknown schema version', { schema_version: 2 }],
    ['invalid confidence', { detections: [{ ...validPayload.detections[0], confidence: 2 }] }],
    ['zero dimensions', { detections: [{ ...validPayload.detections[0], width: 0 }] }],
    ['out of bounds box', { detections: [{ ...validPayload.detections[0], x: 0.9 }] }],
    ['extra field', { extra: true }],
  ])('rejects %s', (_name, patch) => {
    const payload = {
      ...validPayload,
      ...patch,
      detections: 'detections' in patch ? patch.detections : validPayload.detections,
    }

    expect(visionMetadataSchema.safeParse(payload).success).toBe(false)
  })
})

describe('vision metadata projection', () => {
  it('projects normalized boxes into a contained source rectangle', () => {
    expect(
      projectVisionBox(
        validPayload.detections[0],
        { x: 100, y: 0, width: 800, height: 600 },
      ),
    ).toEqual({ x: 420, y: 240, width: 160, height: 120 })
  })

  it('tracks freshness separately from source capture time', () => {
    const cache = { payload: visionMetadataSchema.parse(validPayload), receivedAtMs: 5000 }

    expect(isVisionMetadataFresh(cache, 5999)).toBe(true)
    expect(isVisionMetadataFresh(cache, 6000)).toBe(false)
  })
})
