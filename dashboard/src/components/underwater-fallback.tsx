import { Waves } from '@phosphor-icons/react'

import type { UnderwaterFrame } from '../lib/asv-types'

type UnderwaterFallbackProps = {
  frame: UnderwaterFrame | null
  streamUrl: string | null
}

export function UnderwaterFallback({ frame, streamUrl }: UnderwaterFallbackProps) {
  return (
    <section className="underwater-fallback" aria-labelledby="underwater-camera-title">
      <div className="panel-heading">
        <Waves aria-hidden="true" />
        <div>
          <p className="eyebrow">Raw optical link</p>
          <h2 id="underwater-camera-title">Underwater action camera</h2>
        </div>
      </div>

      {streamUrl ? (
        <img
          className="underwater-fallback__stream"
          src={streamUrl}
          alt="Live underwater action camera"
        />
      ) : frame ? (
        <figure className="underwater-fallback__frame">
          <img
            src={`data:${frame.mime};base64,${frame.data_base64}`}
            alt="Latest underwater frame"
          />
          <figcaption>
            <span>{frame.frame_id}</span>
            <time dateTime={frame.captured_at}>{new Date(frame.captured_at).toLocaleTimeString()}</time>
          </figcaption>
        </figure>
      ) : (
        <div className="underwater-fallback__empty" role="status">
          <Waves aria-hidden="true" size={32} />
          <p>Underwater feed offline</p>
          <span>Waiting for the latest underwater frame from the realtime channel.</span>
        </div>
      )}
    </section>
  )
}
