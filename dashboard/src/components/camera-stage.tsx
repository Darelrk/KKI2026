import { Camera, VideoCamera } from '@phosphor-icons/react'

type CameraStageProps = {
  streamUrl: string | null
}

export function CameraStage({ streamUrl }: CameraStageProps) {
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
        <img className="camera-stage__stream" src={streamUrl} alt="Live surface camera" />
      ) : (
        <div className="camera-stage__placeholder" role="status">
          <VideoCamera aria-hidden="true" size={40} />
          <p>Surface stream unavailable</p>
          <span>Connect a trusted stream URL from the ASV bridge to enable this feed.</span>
        </div>
      )}
    </section>
  )
}
