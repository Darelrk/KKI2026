import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  RemoteSurfaceCamera,
  type PeerConnectionLike,
  type SignalingSocketLike,
} from '../src/components/remote-surface-camera'
import { buildGo2RtcUrls, type Go2RtcUrls } from '../src/lib/video-urls'

class FakeSignalingSocket implements SignalingSocketLike {
  static instances: FakeSignalingSocket[] = []
  readonly url: string
  readonly sent: string[] = []
  readyState = 0
  onopen: ((event?: unknown) => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: ((event?: unknown) => void) | null = null
  onclose: ((event?: unknown) => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeSignalingSocket.instances.push(this)
  }

  send(payload: string) {
    this.sent.push(payload)
  }

  close() {
    this.readyState = 3
    this.onclose?.()
  }

  open() {
    this.readyState = 1
    this.onopen?.()
  }

  message(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }
}

class FakePeerConnection implements PeerConnectionLike {
  static instances: FakePeerConnection[] = []
  readonly transceivers: string[] = []
  readonly remoteDescriptions: RTCSessionDescriptionInit[] = []
  readonly candidates: unknown[] = []
  onicecandidate: PeerConnectionLike['onicecandidate'] = null
  ontrack: ((event: { streams?: MediaStream[] }) => void) | null = null
  onconnectionstatechange: (() => void) | null = null
  connectionState: RTCPeerConnectionState = 'new'
  localDescription: RTCSessionDescriptionInit | null = null
  closed = false

  constructor() {
    FakePeerConnection.instances.push(this)
  }

  addTransceiver(kind: string, init: { direction: RTCRtpTransceiverDirection }) {
    this.transceivers.push(`${kind}:${init.direction}`)
  }

  async createOffer() {
    return { type: 'offer' as const, sdp: 'offer-sdp' }
  }

  async setLocalDescription(description: RTCSessionDescriptionInit) {
    this.localDescription = description
  }

  async setRemoteDescription(description: RTCSessionDescriptionInit) {
    this.remoteDescriptions.push(description)
  }

  async addIceCandidate(candidate: unknown) {
    this.candidates.push(candidate)
  }

  close() {
    this.closed = true
    this.connectionState = 'closed'
  }
}

const urls: Go2RtcUrls = buildGo2RtcUrls('https://remote.example.test')

beforeEach(() => {
  vi.useFakeTimers()
  FakeSignalingSocket.instances = []
  FakePeerConnection.instances = []
})

afterEach(() => vi.useRealTimers())

describe('RemoteSurfaceCamera', () => {
  it('uses one receive-only atas signaling socket and falls back to raw MJPEG', async () => {
    const { container } = render(
      <RemoteSurfaceCamera
        urls={urls}
        signalingFactory={(url) => new FakeSignalingSocket(url)}
        peerConnectionFactory={() => new FakePeerConnection()}
      />,
    )
    const socket = FakeSignalingSocket.instances[0]!
    expect(socket.url).toBe(urls.signaling)
    expect(container.querySelectorAll('video, img')).toHaveLength(1)
    socket.open()
    await act(async () => {})
    const peer = FakePeerConnection.instances[0]!
    expect(peer.transceivers).toEqual(['video:recvonly', 'audio:recvonly'])
    expect(JSON.parse(socket.sent[0] ?? '{}')).toEqual({ type: 'webrtc/offer', value: 'offer-sdp' })

    socket.message({ type: 'webrtc/answer', value: 'answer-sdp' })
    socket.message({ type: 'webrtc/candidate', value: { candidate: 'candidate' } })
    await act(async () => {})
    expect(peer.remoteDescriptions).toContainEqual({ type: 'answer', sdp: 'answer-sdp' })
    expect(peer.candidates).toContainEqual({ candidate: 'candidate' })

    await act(async () => {
      vi.advanceTimersByTime(3000)
    })
    expect(peer.closed).toBe(true)
    expect(container.querySelector('video')).toBeNull()
    expect(container.querySelector('img')).toHaveAttribute('src', urls.mjpeg)
    expect(JSON.stringify(container.innerHTML)).not.toMatch(/bawah|vision|model|overlay|canvas/i)
  })

  it('normalizes incoming Go2RTC ICE candidate strings for browser compatibility', async () => {
    render(
      <RemoteSurfaceCamera
        urls={urls}
        signalingFactory={(url) => new FakeSignalingSocket(url)}
        peerConnectionFactory={() => new FakePeerConnection()}
      />,
    )
    const socket = FakeSignalingSocket.instances[0]!
    const peer = FakePeerConnection.instances[0]!

    socket.message({ type: 'webrtc/candidate', value: 'candidate:remote' })
    await act(async () => {})

    expect(peer.candidates).toEqual([
      {
        candidate: 'candidate:remote',
        sdpMid: '0',
        sdpMLineIndex: 0,
      },
    ])
  })

  it('ignores empty incoming Go2RTC ICE candidate strings', async () => {
    render(
      <RemoteSurfaceCamera
        urls={urls}
        signalingFactory={(url) => new FakeSignalingSocket(url)}
        peerConnectionFactory={() => new FakePeerConnection()}
      />,
    )
    const socket = FakeSignalingSocket.instances[0]!
    const peer = FakePeerConnection.instances[0]!

    socket.message({ type: 'webrtc/candidate', value: '' })
    await act(async () => {})

    expect(peer.candidates).toEqual([])
  })

  it('sends ICE candidate strings after socket open, including queued candidates', async () => {
    render(
      <RemoteSurfaceCamera
        urls={urls}
        signalingFactory={(url) => new FakeSignalingSocket(url)}
        peerConnectionFactory={() => new FakePeerConnection()}
      />,
    )
    const socket = FakeSignalingSocket.instances[0]!
    const peer = FakePeerConnection.instances[0]!

    peer.onicecandidate?.({ candidate: { candidate: '' } })
    expect(socket.sent).toHaveLength(0)

    peer.onicecandidate?.({ candidate: { candidate: 'pre-open-candidate' } })
    expect(socket.sent).toHaveLength(0)

    socket.open()
    await act(async () => {})
    const candidateMessages = socket.sent.map((payload) => JSON.parse(payload)).filter(
      (message) => message.type === 'webrtc/candidate',
    )
    expect(candidateMessages).toEqual([
      { type: 'webrtc/candidate', value: 'pre-open-candidate' },
    ])

    peer.onicecandidate?.({ candidate: { candidate: 'open-candidate' } })
    expect(socket.sent.map((payload) => JSON.parse(payload))).toContainEqual({
      type: 'webrtc/candidate',
      value: 'open-candidate',
    })
  })


  it('switches to raw fallback immediately on signaling close and cleans resources', async () => {
    const { container } = render(
      <RemoteSurfaceCamera
        urls={urls}
        signalingFactory={(url) => new FakeSignalingSocket(url)}
        peerConnectionFactory={() => new FakePeerConnection()}
      />,
    )
    const socket = FakeSignalingSocket.instances[0]!
    socket.open()
    await act(async () => {})
    const peer = FakePeerConnection.instances[0]!
    await act(async () => {
      socket.close()
    })
    expect(peer.closed).toBe(true)
    expect(container.querySelector('img')).toHaveAttribute('src', urls.mjpeg)
    expect(FakeSignalingSocket.instances).toHaveLength(1)
  })
})
