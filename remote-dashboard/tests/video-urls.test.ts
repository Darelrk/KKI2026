import { buildGo2RtcUrls, normalizeVideoOrigin } from '../src/lib/video-urls'

describe('surface video URLs', () => {
  it('normalizes an HTTP origin and derives only raw atas paths', () => {
    expect(buildGo2RtcUrls('https://remote.monitor-kapal-pora-pora.web.id/')).toEqual({
      signaling: 'wss://remote.monitor-kapal-pora-pora.web.id/api/ws?src=atas',
      webrtc: 'https://remote.monitor-kapal-pora-pora.web.id/api/webrtc',
      streamMp4: 'https://remote.monitor-kapal-pora-pora.web.id/api/stream.mp4',
      mjpeg: 'https://remote.monitor-kapal-pora-pora.web.id/api/stream.mjpeg?src=atas',
    })
    const urls = buildGo2RtcUrls('http://localhost:1984')
    expect(urls.signaling).toBe('ws://localhost:1984/api/ws?src=atas')
    expect(normalizeVideoOrigin('wss://example.test///')).toBe('https://example.test')
    expect(JSON.stringify(urls)).not.toMatch(/bawah|vision|telemetry|status/i)
  })
})
