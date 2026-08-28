import { useEffect, useMemo, useRef, useState } from 'react'
import { buildGo2RtcUrls, type Go2RtcUrls } from '../lib/video-urls'

export interface SignalingSocketLike {
  readyState: number
  onopen: ((event?: unknown) => void) | null
  onmessage: ((event: { data: string }) => void) | null
  onerror: ((event?: unknown) => void) | null
  onclose: ((event?: unknown) => void) | null
  send(data: string): void
  close(code?: number, reason?: string): void
}

export interface PeerDescription {
  type: 'offer' | 'answer'
  sdp: string
}

export interface PeerConnectionLike {
  connectionState?: string
  onicecandidate: ((event: { candidate: { candidate: string } | null }) => void) | null
  ontrack: ((event: { streams?: MediaStream[] }) => void) | null
  onconnectionstatechange: (() => void) | null
  addTransceiver(kind: string, init: { direction: 'recvonly' }): unknown
  createOffer(): Promise<PeerDescription>
  setLocalDescription(description: PeerDescription): Promise<void>
  setRemoteDescription(description: PeerDescription): Promise<void>
  addIceCandidate(candidate: unknown): Promise<void>
  close(): void
}

export interface RemoteSurfaceCameraProps {
  urls?: Go2RtcUrls
  backendOrigin?: string
  signalingFactory?: (url: string) => SignalingSocketLike
  peerConnectionFactory?: () => PeerConnectionLike
  fallbackDelayMs?: number
  disabled?: boolean
}

const OPEN = 1
const DEFAULT_BACKEND_ORIGIN = 'http://localhost:1984'

function defaultSignalingFactory(url: string): SignalingSocketLike {
  return new WebSocket(url) as unknown as SignalingSocketLike
}

function defaultPeerConnectionFactory(): PeerConnectionLike {
  return new RTCPeerConnection() as unknown as PeerConnectionLike
}

export function RemoteSurfaceCamera({
  urls,
  backendOrigin = DEFAULT_BACKEND_ORIGIN,
  signalingFactory = defaultSignalingFactory,
  peerConnectionFactory = defaultPeerConnectionFactory,
  fallbackDelayMs = 3000,
  disabled = false,
}: RemoteSurfaceCameraProps) {
  const resolvedUrls = useMemo(
    () => urls ?? buildGo2RtcUrls(backendOrigin),
    [backendOrigin, urls?.mjpeg, urls?.signaling, urls?.streamMp4, urls?.webrtc],
  )
  const videoRef = useRef<HTMLVideoElement>(null)
  const fallbackTimerRef = useRef<unknown>(null)
  const fallbackHandlerRef = useRef<() => void>(() => undefined)
  const [fallback, setFallback] = useState(disabled)

  useEffect(() => {
    let disposed = false
    let switchedToFallback = disabled
    let socket: SignalingSocketLike | null = null
    let peer: PeerConnectionLike | null = null
    let offer: PeerDescription | null = null
    let socketOpen = false
    const pendingCandidates: string[] = []

    const clearFallbackTimer = () => {
      if (fallbackTimerRef.current === null) return
      globalThis.clearTimeout(fallbackTimerRef.current as Parameters<typeof globalThis.clearTimeout>[0])
      fallbackTimerRef.current = null
    }

    const closeResources = () => {
      clearFallbackTimer()
      socketOpen = false
      pendingCandidates.length = 0
      if (socket && socket.readyState !== 3) {
        try {
          socket.close(1000, 'surface player stopped')
        } catch {
          // The browser already considers this signaling socket unusable.
        }
      }
      socket = null
      if (peer) {
        try {
          peer.close()
        } catch {
          // A failed peer is already at the safe cleanup boundary.
        }
      }
      peer = null
      const video = videoRef.current
      if (video) video.srcObject = null
    }

    const switchToFallback = () => {
      if (disposed || switchedToFallback) return
      switchedToFallback = true
      closeResources()
      setFallback(true)
    }
    fallbackHandlerRef.current = switchToFallback

    const sendCandidate = (candidate: string) => {
      if (disposed || switchedToFallback) return
      if (!socket || !socketOpen || socket.readyState !== OPEN) {
        pendingCandidates.push(candidate)
        return
      }
      try {
        socket.send(JSON.stringify({ type: 'webrtc/candidate', value: candidate }))
      } catch {
        switchToFallback()
      }
    }

    const flushPendingCandidates = () => {
      if (!socket || !socketOpen || socket.readyState !== OPEN) return
      while (pendingCandidates.length > 0) {
        const candidate = pendingCandidates.shift()!
        try {
          socket.send(JSON.stringify({ type: 'webrtc/candidate', value: candidate }))
        } catch {
          switchToFallback()
          return
        }
      }
    }

    const sendOffer = () => {
      if (!socket || !socketOpen || !offer || socket.readyState !== OPEN) return
      try {
        socket.send(JSON.stringify({ type: 'webrtc/offer', value: offer.sdp }))
      } catch {
        switchToFallback()
      }
    }

    setFallback(disabled)
    if (disabled) {
      return () => {
        disposed = true
        closeResources()
      }
    }

    fallbackTimerRef.current = globalThis.setTimeout(switchToFallback, Math.max(1, fallbackDelayMs))

    try {
      peer = peerConnectionFactory()
      peer.addTransceiver('video', { direction: 'recvonly' })
      peer.addTransceiver('audio', { direction: 'recvonly' })
      peer.onicecandidate = (event) => {
        if (disposed || switchedToFallback || !event.candidate) return
        const candidate = event.candidate.candidate
        if (typeof candidate === 'string' && candidate !== '') sendCandidate(candidate)
      }
      peer.ontrack = (event) => {
        if (disposed || switchedToFallback) return
        const stream = event.streams?.[0]
        if (stream && videoRef.current) {
          videoRef.current.srcObject = stream
          clearFallbackTimer()
        }
      }
      peer.onconnectionstatechange = () => {
        if (disposed || switchedToFallback || !peer) return
        if (peer.connectionState === 'connected') clearFallbackTimer()
        if (['failed', 'disconnected', 'closed'].includes(peer.connectionState ?? '')) {
          switchToFallback()
        }
      }
      socket = signalingFactory(resolvedUrls.signaling)
      socket.onopen = () => {
        socketOpen = true
        flushPendingCandidates()
        sendOffer()
      }
      socket.onmessage = (event) => {
        if (disposed || switchedToFallback || !peer) return
        let message: unknown
        try {
          message = typeof event.data === 'string' ? JSON.parse(event.data) : event.data
        } catch {
          switchToFallback()
          return
        }
        if (!message || typeof message !== 'object') return
        const payload = message as { type?: unknown; value?: unknown }
        if (payload.type === 'webrtc/answer' && typeof payload.value === 'string') {
          void peer.setRemoteDescription({ type: 'answer', sdp: payload.value }).catch(switchToFallback)
          return
        }
        if (payload.type === 'webrtc/candidate' && payload.value !== undefined) {
          if (typeof payload.value === 'string' && payload.value === '') return
          const candidate =
            typeof payload.value === 'string'
              ? { candidate: payload.value, sdpMid: '0', sdpMLineIndex: 0 }
              : payload.value
          void peer.addIceCandidate(candidate).catch(switchToFallback)
        }
      }
      socket.onerror = () => switchToFallback()
      socket.onclose = () => switchToFallback()
      void peer
        .createOffer()
        .then((createdOffer) => peer?.setLocalDescription(createdOffer).then(() => createdOffer))
        .then((createdOffer) => {
          if (disposed || switchedToFallback || !createdOffer) return
          offer = createdOffer
          sendOffer()
        })
        .catch(switchToFallback)
    } catch {
      switchToFallback()
    }

    return () => {
      disposed = true
      switchedToFallback = true
      closeResources()
    }
  }, [backendOrigin, disabled, fallbackDelayMs, peerConnectionFactory, resolvedUrls, signalingFactory])

  if (fallback || disabled) {
    return (
      <div className="remote-surface-camera" aria-label="Surface camera">
        <img src={resolvedUrls.mjpeg} alt="Surface camera" />
      </div>
    )
  }

  return (
    <div className="remote-surface-camera" aria-label="Surface camera">
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        onError={() => fallbackHandlerRef.current()}
      />
    </div>
  )
}
