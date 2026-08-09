import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { Camera, VideoCamera } from '@phosphor-icons/react'

import { isVisionMetadataFresh, projectVisionBox } from '../lib/vision-metadata'
import { asvGo2rtcUrls } from '../lib/stream-urls'
import { useGo2rtcVideo } from '../lib/use-go2rtc-video'
import { captureMediaFrame } from '../lib/camera-capture'

import type { VisionMetadataCache } from '../lib/vision-metadata'
import type { VisionRealtimeStatus } from '../lib/use-vision-metadata'
import type { CameraCaptureHandle } from '../lib/camera-capture'

type CameraStageProps = {
  streamUrl: string | null
  metadataCache?: VisionMetadataCache | null
  metadataStatus?: VisionRealtimeStatus
}

type VisionRect = {
  x: number
  y: number
  width: number
  height: number
}

function drawVisionDetections(
  context: CanvasRenderingContext2D,
  cache: VisionMetadataCache | null,
  nowMs: number,
  sourceRect: VisionRect,
  scale: number,
) {
  if (!cache || !isVisionMetadataFresh(cache, nowMs)) return
  context.strokeStyle = '#ff9762'
  context.lineWidth = 2 * scale
  context.fillStyle = '#ff9762'
  context.font = `${12 * scale}px sans-serif`
  for (const detection of cache.payload.detections) {
    const box = projectVisionBox(detection, sourceRect)
    context.strokeRect(
      box.x * scale,
      box.y * scale,
      box.width * scale,
      box.height * scale,
    )
    context.fillText(
      `${detection.label} ${(detection.confidence * 100).toFixed(0)}%`,
      box.x * scale,
      Math.max(14 * scale, box.y * scale - 4 * scale),
    )
  }
}

export const CameraStage = forwardRef<CameraCaptureHandle, CameraStageProps>(
  function CameraStage(
    {
      streamUrl,
      metadataCache = null,
      metadataStatus = 'error',
    },
    ref,
  ) {
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

  useImperativeHandle(
    ref,
    () => ({
      captureFrame() {
        const media = player.videoRef.current ?? imageRef.current
        if (!media) throw new Error('Surface camera frame is not ready')
        const canvas = captureMediaFrame(media)
        const context = canvas.getContext('2d')
        if (!context) throw new Error('Canvas capture is unavailable')
        drawVisionDetections(
          context,
          cacheRef.current,
          performance.now(),
          { x: 0, y: 0, width: canvas.width, height: canvas.height },
          1,
        )
        return canvas
      },
    }),
    [player.videoRef],
  )

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


          drawVisionDetections(
            context,
            cache,
            nowMs,
            sourceRect,
            dpr,
          )
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
  },
)
