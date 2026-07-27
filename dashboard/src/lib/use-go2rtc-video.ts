import { useCallback, useEffect, useRef, useState } from 'react'

import type { RefObject } from 'react'
import type { Go2rtcUrls } from './stream-urls'

export type Go2rtcPlaybackMode = 'connecting' | 'webrtc' | 'mjpeg'

type UseGo2rtcVideoOptions = {
  urls: Go2rtcUrls
  enabled: boolean
  fallbackUrl?: string | null
}

export type UseGo2rtcVideoResult = {
  videoRef: RefObject<HTMLVideoElement | null>
  mode: Go2rtcPlaybackMode
  mjpegFailed: boolean
  onMjpegError: () => void
}

type SignalingMessage = {
  type?: unknown
  value?: unknown
}

const WEBRTC_TIMEOUT_MS = 3000

function isSignalingMessage(value: unknown): value is SignalingMessage {
  return typeof value === 'object' && value !== null
}

export function useGo2rtcVideo({
  urls,
  enabled,
  fallbackUrl,
}: UseGo2rtcVideoOptions): UseGo2rtcVideoResult {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [mode, setMode] = useState<Go2rtcPlaybackMode>(
    enabled ? 'connecting' : 'mjpeg',
  )
  const [mjpegFailed, setMjpegFailed] = useState(false)

  useEffect(() => {
    setMode(enabled ? 'connecting' : 'mjpeg')
    setMjpegFailed(false)

    if (!enabled) return

    let stopped = false
    let peer: RTCPeerConnection | null = null
    let socket: WebSocket | null = null
    let timeoutId: number | undefined
    let remoteStream: MediaStream | null = null
    const activateIfConnected = () => {
      if (
        stopped ||
        !peer ||
        !remoteStream ||
        peer.connectionState !== 'connected'
      ) {
        return
      }
      clearTimeoutIfNeeded()
      setMode('webrtc')
    }

    const clearTimeoutIfNeeded = () => {
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId)
        timeoutId = undefined
      }
    }

    const closeResources = () => {
      clearTimeoutIfNeeded()

      if (socket) {
        socket.onopen = null
        socket.onmessage = null
        socket.onerror = null
        socket.onclose = null
        socket.close()
        socket = null
      }

      if (peer) {
        peer.onicecandidate = null
        peer.onicegatheringstatechange = null
        peer.ontrack = null
        peer.onconnectionstatechange = null
        peer.close()
        peer = null
      }

      if (videoRef.current) {
        videoRef.current.srcObject = null
      }
    }

    const fallback = () => {
      if (stopped) return
      stopped = true
      closeResources()
      setMode('mjpeg')
    }

    const send = (message: Record<string, string>) => {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(message))
      }
    }

    const handleMessage = async (rawMessage: unknown) => {
      if (stopped || !peer) return

      let message: unknown
      try {
        message = JSON.parse(String(rawMessage))
      } catch {
        return
      }
      if (!isSignalingMessage(message)) return

      if (
        message.type === 'webrtc/answer' &&
        typeof message.value === 'string'
      ) {
        try {
          await peer.setRemoteDescription({
            type: 'answer',
            sdp: message.value,
          })
        } catch {
          fallback()
        }
        return
      }

      if (
        message.type === 'webrtc/candidate' &&
        typeof message.value === 'string' &&
        message.value
      ) {
        try {
          await peer.addIceCandidate({
            candidate: message.value,
            sdpMid: '0',
          })
        } catch {
          fallback()
        }
      }
    }

    const connect = async () => {
      if (
        typeof RTCPeerConnection === 'undefined' ||
        typeof WebSocket === 'undefined'
      ) {
        fallback()
        return
      }

      try {
        peer = new RTCPeerConnection({
          iceServers: [
            {
              urls: [
                'stun:stun.cloudflare.com:3478',
                'stun:stun.l.google.com:19302',
              ],
            },
          ],
        })
        peer.addTransceiver('video', { direction: 'recvonly' })
        peer.ontrack = (event) => {
          if (stopped) return
          const stream =
            event.streams[0] ??
            (typeof MediaStream === 'undefined'
              ? null
              : new MediaStream([event.track]))
          const video = videoRef.current
          if (!stream || !video) return

          remoteStream = stream
          video.srcObject = stream
          void video.play().catch(() => undefined)
          activateIfConnected()
        }
        peer.onconnectionstatechange = () => {
          if (
            peer &&
            (peer.connectionState === 'failed' ||
              peer.connectionState === 'closed')
          ) {
            fallback()
            return
          }
          activateIfConnected()
        }

        socket = new WebSocket(urls.webrtcWs)
        socket.onopen = async () => {
          if (stopped || !peer) return
          try {
            const offer = await peer.createOffer()
            if (stopped || !peer) return
            await peer.setLocalDescription(offer)
            if (stopped || !peer?.localDescription?.sdp) return
            send({ type: 'webrtc/offer', value: peer.localDescription.sdp })
          } catch {
            fallback()
          }
        }
        peer.onicecandidate = (event) => {
          if (event.candidate) {
            send({ type: 'webrtc/candidate', value: event.candidate.candidate })
          }
        }
        socket.onmessage = (event) => {
          void handleMessage(event.data)
        }
        socket.onerror = fallback
        socket.onclose = fallback
        timeoutId = window.setTimeout(fallback, WEBRTC_TIMEOUT_MS)
      } catch {
        fallback()
      }
    }

    void connect()

    return () => {
      stopped = true
      closeResources()
    }
  }, [
    enabled,
    fallbackUrl,
    urls.mjpeg,
    urls.mse,
    urls.webrtcHttp,
    urls.webrtcWs,
  ])

  const onMjpegError = useCallback(() => {
    setMjpegFailed(true)
  }, [])

  return { videoRef, mode, mjpegFailed, onMjpegError }
}
