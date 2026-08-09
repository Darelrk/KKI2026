import { Camera, Compass, Crosshair, Gauge, Timer } from '@phosphor-icons/react'

import { formatSiteTime } from '../lib/format-site-time'

import type { NavigationTelemetry } from '../lib/navigation-types'

type TelemetryPanelProps = {
  telemetry: NavigationTelemetry
  updatedAt: string | null
  captureState?: 'idle' | 'capturing' | 'saved' | 'error'
  captureFilename?: string
  onCapture?: () => void
}

const metersPerSecondToKnots = 1.943844492
const metersPerSecondToKilometersPerHour = 3.6

export function TelemetryPanel({
  telemetry,
  updatedAt,
  captureState = 'idle',
  captureFilename = '',
  onCapture,
}: TelemetryPanelProps) {
  return (
    <section className="telemetry-panel" aria-labelledby="telemetry-title">
      <div className="panel-heading">
        <Crosshair aria-hidden="true" />
        <div>
          <p className="eyebrow">Realtime monitoring</p>
          <h2 id="telemetry-title">Attitude telemetry</h2>
        </div>
      </div>

      <dl className="telemetry-grid">
        <div className="telemetry-card telemetry-card--priority telemetry-card--wide">
          <dt>
            <Compass aria-hidden="true" size={14} />
            COG
          </dt>
          <dd>
            {telemetry.heading_deg === null
              ? 'Unavailable'
              : `${telemetry.heading_deg.toFixed(1)}°`}
          </dd>
        </div>
        <div className="telemetry-card telemetry-card--priority telemetry-card--wide">
          <dt>
            <Gauge aria-hidden="true" size={14} />
            SOG
          </dt>
          <dd>
            {telemetry.speed_mps === null ? (
              'Unavailable'
            ) : (
              <>
                <span>
                  {(telemetry.speed_mps * metersPerSecondToKnots).toFixed(2)}{' '}
                  knot
                </span>
                <br />
                <span>
                  {(
                    telemetry.speed_mps * metersPerSecondToKilometersPerHour
                  ).toFixed(2)}{' '}
                  km/h
                </span>
              </>
            )}
          </dd>
        </div>
        <div className="telemetry-card telemetry-card--wide">
          <dt>
            <Timer aria-hidden="true" size={14} />
            Last update
          </dt>
          <dd>{updatedAt ? formatSiteTime(updatedAt) : 'Unavailable'}</dd>
        </div>
      </dl>
      {onCapture ? (
        <div className="telemetry-panel__capture">
          <button
            type="button"
            className={`telemetry-panel__capture-button telemetry-panel__capture-button--${captureState}`}
            aria-label="Capture both cameras"
            title="Capture both cameras"
            onClick={onCapture}
            disabled={captureState === 'capturing'}
          >
            <Camera aria-hidden="true" size={15} weight="bold" />
            <span>Capture cameras</span>
          </button>
          {captureState === 'capturing' ? (
            <span className="telemetry-panel__capture-status" role="status">
              Capturing both camera feeds.
            </span>
          ) : captureState === 'saved' ? (
            <span className="telemetry-panel__capture-status" role="status">
              Capture saved: {captureFilename}
            </span>
          ) : captureState === 'error' ? (
            <span
              className="telemetry-panel__capture-status telemetry-panel__capture-status--error"
              role="alert"
            >
              Capture failed. Verify both camera feeds.
            </span>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
