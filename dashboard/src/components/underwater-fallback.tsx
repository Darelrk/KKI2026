import { forwardRef, useImperativeHandle, useRef } from 'react'
import { Waves } from '@phosphor-icons/react'

import { asvGo2rtcUrls } from '../lib/stream-urls'
import { useGo2rtcVideo } from '../lib/use-go2rtc-video'
import { captureMediaFrame } from '../lib/camera-capture'

import type { UnderwaterFrame } from '../lib/asv-types'
import type { CameraCaptureHandle } from '../lib/camera-capture'

type UnderwaterFallbackProps = {
  frame: UnderwaterFrame | null
  streamUrl: string | null
}

export const UnderwaterFallback = forwardRef<
  CameraCaptureHandle,
  UnderwaterFallbackProps
>(function UnderwaterFallback({ frame, streamUrl }, ref) {
  const imageRef = useRef<HTMLImageElement>(null)
  const player = useGo2rtcVideo({
    urls: asvGo2rtcUrls.underwater,
    enabled: Boolean(streamUrl),
    fallbackUrl: streamUrl,
  })
  useImperativeHandle(
    ref,
    () => ({
      captureFrame() {
        const media = player.videoRef.current ?? imageRef.current
        if (!media) throw new Error('Underwater camera frame is not ready')
        return captureMediaFrame(media, { rotate180: true })
      },
    }),
    [player.videoRef],
  )
  const activeStreamUrl =
    streamUrl && player.mode === 'mjpeg' && !player.mjpegFailed
      ? streamUrl
      : null

  return (
    <section
      className="underwater-fallback"
      aria-labelledby="underwater-camera-title"
    >
      <div className="panel-heading">
        <Waves aria-hidden="true" />
        <div>
          <p className="eyebrow">Raw optical link</p>
          <h2 id="underwater-camera-title">Underwater action camera</h2>
        </div>
      </div>

      {streamUrl && player.mode !== 'mjpeg' ? (
        <video
          ref={player.videoRef}
          className="underwater-fallback__stream"
          autoPlay
          playsInline
          muted
          aria-label="Live underwater action camera"
        />
      ) : activeStreamUrl ? (
        <img
          ref={imageRef}
          className="underwater-fallback__stream"
          src={activeStreamUrl}
          alt="Live underwater action camera"
          onError={player.onMjpegError}
        />
      ) : frame ? (
        <figure className="underwater-fallback__frame">
          <img
            ref={imageRef}
            src={`data:${frame.mime};base64,${frame.data_base64}`}
            alt="Latest underwater frame"
          />
          <figcaption>
            <span>{frame.frame_id}</span>
            <time dateTime={frame.captured_at}>
              {new Date(frame.captured_at).toLocaleTimeString()}
            </time>
          </figcaption>
        </figure>
      ) : (
        <div className="underwater-fallback__empty" role="status">
          <Waves aria-hidden="true" size={32} />
          <p>Underwater feed offline</p>
          <span>
            Waiting for the latest underwater frame from the realtime channel.
          </span>
        </div>
      )}
    </section>
  )
})
