import { MapPin } from '@phosphor-icons/react'

import type { NavigationTelemetry } from '../lib/navigation-types'

type NavigationMapProps = {
  telemetry: NavigationTelemetry
}

export function NavigationMap({ telemetry }: NavigationMapProps) {
  const lastTrackPoint = telemetry.track.at(-1)
  const boatPosition = telemetry.position ?? lastTrackPoint
  const projectionPoints = boatPosition
    ? [...telemetry.track, boatPosition]
    : telemetry.track
  const longitudes = projectionPoints.map((point) => point.longitude)
  const latitudes = projectionPoints.map((point) => point.latitude)
  const minLongitude = longitudes.length > 0 ? Math.min(...longitudes) : 0
  const maxLongitude = longitudes.length > 0 ? Math.max(...longitudes) : 1
  const minLatitude = latitudes.length > 0 ? Math.min(...latitudes) : 0
  const maxLatitude = latitudes.length > 0 ? Math.max(...latitudes) : 1
  const longitudeRange = maxLongitude - minLongitude || 1
  const latitudeRange = maxLatitude - minLatitude || 1
  const projectPoint = (point: typeof projectionPoints[number]) => ({
    x: 10 + ((point.longitude - minLongitude) / longitudeRange) * 80,
    y: 90 - ((point.latitude - minLatitude) / latitudeRange) * 80,
  })
  const trackPoints = telemetry.track.length >= 2
    ? telemetry.track.map((point) => {
        const projected = projectPoint(point)
        return `${projected.x},${projected.y}`
      }).join(' ')
    : ''
  const projectedBoat = boatPosition ? projectPoint(boatPosition) : null
  const hasTrackPlot = telemetry.track.length >= 2
  const plotLabel = hasTrackPlot ? 'GPS track plot' : 'Current boat position'

  return (
    <section className="navigation-map" aria-labelledby="navigation-map-title">
      <div className="panel-heading">
        <MapPin aria-hidden="true" />
        <div>
          <p className="eyebrow">Route telemetry</p>
          <h2 id="navigation-map-title">Live boat track</h2>
        </div>
      </div>

      <div className="navigation-map__canvas" aria-label="Live boat track">
        <div className="navigation-map__grid" aria-hidden="true" />
        {projectedBoat ? (
          <svg
            className="navigation-map__plot"
            viewBox="0 0 100 100"
            role="img"
            aria-label={plotLabel}
          >
            {hasTrackPlot ? (
              <polyline
                className="navigation-map__track"
                points={trackPoints}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
              />
            ) : null}
            <g
              className="navigation-map__boat"
              data-testid="boat-marker"
              aria-hidden="true"
              transform={`translate(${projectedBoat.x} ${projectedBoat.y})${
                telemetry.heading_deg === null ? '' : ` rotate(${telemetry.heading_deg})`
              }`}
            >
              {telemetry.heading_deg === null ? (
                <circle className="navigation-map__boat-dot" r="2.8" />
              ) : (
                <path className="navigation-map__boat-arrow" d="M 0 -5 L 3 4 L 0 2 L -3 4 Z" />
              )}
            </g>
          </svg>
        ) : (
          <div className="navigation-map__empty">
            <MapPin aria-hidden="true" size={28} />
            <strong>Waiting for GPS fix.</strong>
            <span>The live boat path will appear when GPS points are received.</span>
          </div>
        )}
        <div className="navigation-map__readout">
          <span>{telemetry.position ? 'GPS position available' : 'GPS position unavailable'}</span>
          <span>{telemetry.track.length > 0 ? `GPS track · ${telemetry.track.length} points` : 'GPS track unavailable'}</span>
        </div>
      </div>
    </section>
  )
}
