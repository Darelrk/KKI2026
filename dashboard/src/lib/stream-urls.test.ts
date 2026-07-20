import { describe, expect, it } from 'vitest'

import { defaultAsvStreamUrls, resolveAsvStreamUrls, resolveAsvVisionWsUrl } from './stream-urls'

describe('resolveAsvStreamUrls', () => {
  it('uses the configured raw camera URLs', () => {
    expect(
      resolveAsvStreamUrls({
        VITE_ASV_SURFACE_STREAM_URL: ' https://example.test/atas ',
        VITE_ASV_UNDERWATER_STREAM_URL: 'https://example.test/bawah',
      }),
    ).toEqual({
      surface: 'https://example.test/atas',
      underwater: 'https://example.test/bawah',
    })
  })

  it('uses the deployed raw camera URLs when env values are empty', () => {
    expect(
      resolveAsvStreamUrls({
        VITE_ASV_SURFACE_STREAM_URL: ' ',
        VITE_ASV_UNDERWATER_STREAM_URL: undefined,
      }),
    ).toEqual(defaultAsvStreamUrls)
  })

  it('keeps the vision WebSocket URL independent from camera URLs', () => {
    expect(
      resolveAsvVisionWsUrl({
        VITE_ASV_VISION_WS_URL: ' wss://bridge.example.test ',
      }),
    ).toBe('wss://bridge.example.test')
    expect(resolveAsvVisionWsUrl({})).toBeNull()
  })
})
