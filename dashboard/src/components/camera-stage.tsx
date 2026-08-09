import { useEffect, useRef } from 'react'
import { Camera, VideoCamera } from '@phosphor-icons/react'

import { isVisionMetadataFresh, projectVisionBox } from '../lib/vision-metadata'
import { asvGo2rtcUrls } from '../lib/stream-urls'
import { useGo2rtcVideo } from '../lib/use-go2rtc-video'

import type { VisionMetadataCache } from '../lib/vision-metadata'
import type { VisionRealtimeStatus } from '../lib/use-vision-metadata'

type CameraStageProps = {
  streamUrl: string | null
  metadataCache?: VisionMetadataCache | null
  metadataStatus?: VisionRealtimeStatus
}

export function CameraStage({
  streamUrl,
  metadataCache = null,
  metadataStatus = 'error',
}: CameraStageProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imageRef = useRef<HTMLImageElement>(null)
  const cacheRef = useRef(metadataCache)
  const player = useGo2rtcVideo({
    urls: asvGo2rtcUrls.surface,
    enabled: Boolean(streamUrl),
    fallbackUrl: streamUrl,
  })

  useEffect(() => {
    cacheRef.current = metadataCache
  }, [metadataCache])

  useEffect(() => {
    let animationFrame = 0

    const draw = (nowMs: number) => {
      const video = player.videoRef.current
      const image = imageRef.current
      const media = video ?? image
      const canvas = canvasRef.current
      if (media && canvas) {
        const display = media.getBoundingClientRect()
        const dpr = window.devicePixelRatio || 1
        canvas.width = Math.max(1, Math.round(display.width * dpr))
        canvas.height = Math.max(1, Math.round(display.height * dpr))
        const context = canvas.getContext('2d')
        if (context) {
          context.clearRect(0, 0, canvas.width, canvas.height)
          const cache = cacheRef.current
          const sourceWidth =
            video?.videoWidth ||
            image?.naturalWidth ||
            cache?.payload.source_width ||
            display.width
          const sourceHeight =
            video?.videoHeight ||
            image?.naturalHeight ||
            cache?.payload.source_height ||
            display.height
          const scale = Math.min(
            display.width / sourceWidth,
            display.height / sourceHeight,
          )
          const sourceRect = {
            x: (display.width - sourceWidth * scale) / 2,
            y: (display.height - sourceHeight * scale) / 2,
            width: sourceWidth * scale,
            height: sourceHeight * scale,
          }

          // Keep the operator's visual center fixed independently of
          // detection refreshes and stale metadata.
          const centerX = (sourceRect.x + sourceRect.width / 2) * dpr
          context.strokeStyle = '#2f80ed'
          context.lineWidth = 2 * dpr
          context.beginPath()
          context.moveTo(centerX, sourceRect.y * dpr)
          context.lineTo(
            centerX,
            (sourceRect.y + sourceRect.height) * dpr,
          )
          context.stroke()

          if (cache && isVisionMetadataFresh(cache, nowMs)) {
            context.strokeStyle = '#ff9762'
            context.lineWidth = 2 * dpr
            for (const detection of cache.payload.detections) {
              const box = projectVisionBox(detection, sourceRect)
              context.strokeRect(
                box.x * dpr,
                box.y * dpr,
                box.width * dpr,
                box.height * dpr,
              )
              context.fillStyle = '#ff9762'
              context.font = `${12 * dpr}px sans-serif`
              context.fillText(
                `${detection.label} ${(detection.confidence * 100).toFixed(0)}%`,
                box.x * dpr,
                Math.max(14 * dpr, box.y * dpr - 4 * dpr),
              )
            }
          }
        }
      } else if (canvas) {
        canvas.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height)
      }
      animationFrame = requestAnimationFrame(draw)
    }

    animationFrame = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(animationFrame)
  }, [player.videoRef])

  return (
    <section className="camera-stage" aria-labelledby="surface-camera-title">
      <div className="panel-heading">
        <Camera aria-hidden="true" />
        <div>
          <p className="eyebrow">Primary optical link</p>
          <h2 id="surface-camera-title">Surface camera</h2>
        </div>
      </div>

      {streamUrl ? (
        <div className="camera-stage__media">
          {player.mode === 'mjpeg' ? (
            player.mjpegFailed ? (
              <div className="camera-stage__placeholder" role="status">
                <VideoCamera aria-hidden="true" size={40} />
                <p>Surface stream offline</p>
                <span>
                  Camera feed is not available. Verify the stream URL
                  configuration.
                </span>
              </div>
            ) : (
              <img
                className="camera-stage__stream"
                ref={imageRef}
                src={streamUrl || asvGo2rtcUrls.surface.mjpeg}
                alt="Live surface camera"
                onError={player.onMjpegError}
              />
            )
          ) : (
            <video
              ref={player.videoRef}
              className="camera-stage__stream"
              autoPlay
              playsInline
              muted
              aria-label="Live surface camera"
            />
          )}
          <canvas
            ref={canvasRef}
            className="camera-stage__overlay"
            aria-hidden="true"
            style={{ pointerEvents: 'none' }}
          />
        </div>
      ) : (
        <div className="camera-stage__placeholder" role="status">
          <VideoCamera aria-hidden="true" size={40} />
          <p>Surface stream offline</p>
          <span>
            Camera feed is not available. Verify the stream URL configuration.
          </span>
        </div>
      )}
      {streamUrl ? (
        <div className="camera-stage__metadata-bar">
          <span
            className={`status-chip status-chip--${metadataStatus === 'connected' ? 'connected' : metadataStatus === 'fixture' ? 'fixture' : metadataStatus === 'connecting' ? 'connecting' : 'error'}`}
          >
            Vision {metadataStatus === 'fixture' ? 'active' : metadataStatus}
          </span>
        </div>
      ) : null}
    </section>
  )
}
