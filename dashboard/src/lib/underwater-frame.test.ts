import { describe, expect, it } from 'vitest'

import { keepLatestUnderwaterFrame } from './asv-types'

const latestFrame = {
  mime: 'image/jpeg',
  data_base64: '/9j/4AAQSkZJRgABAQAAAQABAAD/2w==',
  captured_at: '2026-07-20T09:30:00.000Z',
  frame_id: 'underwater-001',
} as const

describe('keepLatestUnderwaterFrame', () => {
  it('accepts a bounded JPEG fallback frame', () => {
    expect(keepLatestUnderwaterFrame(null, latestFrame)).toEqual(latestFrame)
  })

  it('keeps the prior frame when the payload exceeds the cap', () => {
    expect(
      keepLatestUnderwaterFrame(latestFrame, {
        ...latestFrame,
        data_base64: 'A'.repeat(180_001),
      }),
    ).toEqual(latestFrame)
  })

  it('keeps the prior frame when MIME type is unsupported', () => {
    expect(
      keepLatestUnderwaterFrame(latestFrame, {
        ...latestFrame,
        mime: 'image/png',
      }),
    ).toEqual(latestFrame)
  })

  it('keeps the prior frame when Base64 is malformed', () => {
    expect(
      keepLatestUnderwaterFrame(latestFrame, {
        ...latestFrame,
        data_base64: 'not-base64!',
      }),
    ).toEqual(latestFrame)
  })
})
