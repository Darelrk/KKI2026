import { describe, expect, it } from 'vitest'

import {
  defaultAsvBridgeUrl,
  defaultAsvStreamUrls,
  resolveAsvBridgeUrl,
  resolveAsvStreamUrls,
  resolveAsvTelemetryWsUrl,
  resolveAsvVisionWsUrl,
} from './stream-urls'

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
    ).toEqual({
      surface: defaultAsvStreamUrls.surface,
      underwater: defaultAsvStreamUrls.underwater,
    })
  })

  it('resolves the direct bridge URL independently from camera URLs', () => {
    expect(
      resolveAsvBridgeUrl({
        VITE_ASV_BRIDGE_URL: ' https://bridge.example.test/ ',
      }),
    ).toBe('https://bridge.example.test')
    expect(resolveAsvBridgeUrl({})).toBe(defaultAsvBridgeUrl)
  })

  it('keeps the vision WebSocket URL independent from camera URLs', () => {
    expect(
      resolveAsvVisionWsUrl({
        VITE_ASV_VISION_WS_URL: ' wss://bridge.example.test ',
      }),
    ).toBe('wss://bridge.example.test')
    expect(resolveAsvVisionWsUrl({})).toBe('wss://monitor-kapal-pora-pora.web.id')
  })

  it('keeps the telemetry WebSocket URL independent from camera URLs', () => {
    expect(
      resolveAsvTelemetryWsUrl({
        VITE_ASV_TELEMETRY_WS_URL: ' wss://telemetry.example.test ',
      }),
    ).toBe('wss://telemetry.example.test')
    expect(resolveAsvTelemetryWsUrl({})).toBe('wss://monitor-kapal-pora-pora.web.id')
  })
