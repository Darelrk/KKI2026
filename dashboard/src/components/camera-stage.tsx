
import { useEffect, useRef } from 'react'
import { Camera, VideoCamera } from '@phosphor-icons/react'

import {
  isVisionMetadataFresh,
  projectVisionBox,
} from '../lib/vision-metadata'

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
  const imageRef = useRef<HTMLImageElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const cacheRef = useRef(metadataCache)

  useEffect(() => {
    cacheRef.current = metadataCache
  }, [metadataCache])

  useEffect(() => {
    let animationFrame = 0

    const draw = (nowMs: number) => {
      const image = imageRef.current
      const canvas = canvasRef.current
      if (image && canvas) {
        const display = image.getBoundingClientRect()
        const dpr = window.devicePixelRatio || 1
        canvas.width = Math.max(1, Math.round(display.width * dpr))
        canvas.height = Math.max(1, Math.round(display.height * dpr))
        const context = canvas.getContext('2d')
        if (context) {
          context.clearRect(0, 0, canvas.width, canvas.height)
          const cache = cacheRef.current
          if (cache && isVisionMetadataFresh(cache, nowMs)) {
            const sourceWidth = image.naturalWidth || cache.payload.source_width
            const sourceHeight = image.naturalHeight || cache.payload.source_height
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
      }
      animationFrame = requestAnimationFrame(draw)
    }

    animationFrame = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(animationFrame)
  }, [])

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
          <img
            ref={imageRef}
            className="camera-stage__stream"
            src={streamUrl}
            alt="Live surface camera"
          />
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
          <span>Camera feed is not available. Verify the stream URL configuration.</span>
        </div>
      )}
      {streamUrl ? (
        <p className="camera-stage__metadata-status" aria-live="polite">
          Metadata channel {metadataStatus}
        </p>
      ) : null}
    </section>
  )
}
