import { useCallback, useEffect, useRef, useState } from 'react'

import type { RefObject } from 'react'
import type { Go2rtcUrls } from './stream-urls'

export type Go2rtcPlaybackMode = 'connecting' | 'webrtc' | 'mjpeg'

type UseGo2rtcVideoOptions = {
  urls: Go2rtcUrls
  enabled: boolean
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
const ICE_GATHERING_TIMEOUT_MS = 1000

function isSignalingMessage(value: unknown): value is SignalingMessage {
  return typeof value === 'object' && value !== null
}

function waitForIceGathering(peer: RTCPeerConnection): Promise<void> {
  if (peer.iceGatheringState === 'complete') {
    return Promise.resolve()
  }

  const { promise, resolve } = (
    Promise as PromiseConstructor & {
      withResolvers<T>(): {
        promise: Promise<T>
        resolve: (value?: T | PromiseLike<T>) => void
      }
    }
  ).withResolvers<void>()
  let settled = false
  const finish = () => {
    if (settled) return
    settled = true
    window.clearTimeout(timeoutId)
    peer.onicegatheringstatechange = null
    resolve()
  }
  const timeoutId = window.setTimeout(finish, ICE_GATHERING_TIMEOUT_MS)
  peer.onicegatheringstatechange = () => {
    if (peer.iceGatheringState === 'complete') finish()
  }
  return promise
}

export function useGo2rtcVideo({
  urls,
  enabled,
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
          await peer.addIceCandidate({ candidate: message.value })
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
        peer = new RTCPeerConnection()
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

          video.srcObject = stream
          void video.play().catch(() => undefined)
          clearTimeoutIfNeeded()
          setMode('webrtc')
        }
        peer.onconnectionstatechange = () => {
          if (
            peer &&
            (peer.connectionState === 'failed' ||
              peer.connectionState === 'closed')
          ) {
            fallback()
          }
        }

        socket = new WebSocket(urls.webrtcWs)
        socket.onopen = async () => {
          if (stopped || !peer) return
          try {
            const offer = await peer.createOffer()
            if (stopped || !peer) return
            await peer.setLocalDescription(offer)
            await waitForIceGathering(peer)
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
  }, [enabled, urls.mjpeg, urls.mse, urls.webrtcHttp, urls.webrtcWs])

  const onMjpegError = useCallback(() => {
    setMjpegFailed(true)
  }, [])

  return { videoRef, mode, mjpegFailed, onMjpegError }
}
