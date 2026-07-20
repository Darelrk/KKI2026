import { Compass, Crosshair, Gauge, Timer } from '@phosphor-icons/react'

import type { NavigationTelemetry } from '../lib/navigation-types'

type TelemetryPanelProps = {
  telemetry: NavigationTelemetry
  updatedAt: string | null
}

export function TelemetryPanel({ telemetry, updatedAt }: TelemetryPanelProps) {
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
        <div className="telemetry-card telemetry-card--wide">
          <dt>
            <Crosshair aria-hidden="true" size={14} />
            GPS position
          </dt>
          <dd>
            {telemetry.position
              ? `${telemetry.position.latitude.toFixed(6)}, ${telemetry.position.longitude.toFixed(6)}`
              : 'Unavailable'}
          </dd>
        </div>
        <div className="telemetry-card">
          <dt>
            <Compass aria-hidden="true" size={14} />
            Heading
          </dt>
          <dd>{telemetry.heading_deg === null ? 'Unavailable' : `${telemetry.heading_deg.toFixed(1)}°`}</dd>
        </div>
        <div className="telemetry-card">
          <dt>
            <Gauge aria-hidden="true" size={14} />
            Speed
          </dt>
          <dd>{telemetry.speed_mps === null ? 'Unavailable' : `${telemetry.speed_mps.toFixed(2)} m/s`}</dd>
        </div>
        <div className="telemetry-card telemetry-card--wide">
          <dt>
            <Timer aria-hidden="true" size={14} />
            Last update
          </dt>
          <dd>{updatedAt ? updatedAt.replace('T', ' ').replace(/\.\d+Z$/, ' UTC') : 'Unavailable'}</dd>
        </div>
      </dl>
    </section>
  )
}
