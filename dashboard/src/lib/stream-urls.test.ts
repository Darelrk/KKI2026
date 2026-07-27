import { describe, expect, it } from 'vitest'

import {
  defaultAsvBridgeUrl,
  defaultAsvStreamUrls,
  getGo2rtcUrls,
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
    expect(resolveAsvVisionWsUrl({})).toBe(
      'wss://monitor-kapal-pora-pora.web.id',
    )
  })

  it('keeps the telemetry WebSocket URL independent from camera URLs', () => {
    expect(
      resolveAsvTelemetryWsUrl({
        VITE_ASV_TELEMETRY_WS_URL: ' wss://telemetry.example.test ',
      }),
    ).toBe('wss://telemetry.example.test')
    expect(resolveAsvTelemetryWsUrl({})).toBe(
      'wss://monitor-kapal-pora-pora.web.id',
    )
  })
  it('derives all go2rtc endpoints from a custom HTTPS bridge', () => {
    expect(getGo2rtcUrls(' https://bridge.example.test/ ', 'atas')).toEqual({
      webrtcWs: 'wss://bridge.example.test/api/ws?src=atas',
      webrtcHttp: 'https://bridge.example.test/api/webrtc?src=atas',
      mse: 'https://bridge.example.test/api/stream.mp4?src=atas',
      mjpeg: 'https://bridge.example.test/stream/atas',
    })
  })

  it('converts HTTP bridges and supports the underwater source', () => {
    expect(getGo2rtcUrls('http://bridge.example.test/base/', 'bawah')).toEqual({
      webrtcWs: 'ws://bridge.example.test/base/api/ws?src=bawah',
      webrtcHttp: 'http://bridge.example.test/base/api/webrtc?src=bawah',
      mse: 'http://bridge.example.test/base/api/stream.mp4?src=bawah',
      mjpeg: 'http://bridge.example.test/base/stream/bawah',
    })
  })
})
