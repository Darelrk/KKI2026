import { MapPin } from '@phosphor-icons/react'

import type { NavigationTelemetry } from '../lib/navigation-types'

type NavigationMapProps = {
  telemetry: NavigationTelemetry
}

const buoyPairs = [
  { x: 15, y: 77 },
  { x: 21, y: 68 },
  { x: 28, y: 59 },
  { x: 35, y: 51 },
  { x: 43, y: 43 },
  { x: 51, y: 36 },
  { x: 59, y: 30 },
  { x: 67, y: 25 },
  { x: 75, y: 21 },
  { x: 83, y: 17 },
] as const

export function NavigationMap({ telemetry }: NavigationMapProps) {
  const lastTrackPoint = telemetry.track.at(-1)
  const boatPosition = telemetry.position ?? lastTrackPoint
  const currentIsAlreadyLastPoint =
    boatPosition !== undefined &&
    lastTrackPoint !== undefined &&
    boatPosition.latitude === lastTrackPoint.latitude &&
    boatPosition.longitude === lastTrackPoint.longitude
  const pathPoints =
    boatPosition && !currentIsAlreadyLastPoint
      ? [...telemetry.track, boatPosition]
      : telemetry.track
  const longitudes = pathPoints.map((point) => point.longitude)
  const latitudes = pathPoints.map((point) => point.latitude)
  const minLongitude = longitudes.length > 0 ? Math.min(...longitudes) : 0
  const maxLongitude = longitudes.length > 0 ? Math.max(...longitudes) : 1
  const minLatitude = latitudes.length > 0 ? Math.min(...latitudes) : 0
  const maxLatitude = latitudes.length > 0 ? Math.max(...latitudes) : 1
  const longitudeRange = maxLongitude - minLongitude || 1
  const latitudeRange = maxLatitude - minLatitude || 1
  const projectPoint = (point: typeof pathPoints[number]) => ({
    x: 10 + ((point.longitude - minLongitude) / longitudeRange) * 80,
    y: 90 - ((point.latitude - minLatitude) / latitudeRange) * 80,
  })
  const trackPoints =
    pathPoints.length >= 2
      ? pathPoints
          .map((point) => {
            const projected = projectPoint(point)
            return `${projected.x},${projected.y}`
          })
          .join(' ')
      : ''
  const projectedBoat = boatPosition ? projectPoint(boatPosition) : null
  const hasTrackPlot = pathPoints.length >= 2

  return (
    <section className="navigation-map" aria-labelledby="navigation-map-title">
      <div className="panel-heading">
        <MapPin aria-hidden="true" />
        <div>
          <p className="eyebrow">Route telemetry</p>
          <h2 id="navigation-map-title">Mission route</h2>
        </div>
      </div>

      <div className="navigation-map__layout">
        <div className="navigation-map__canvas" aria-label="Mission route and live boat track">
          <div className="navigation-map__grid" aria-hidden="true" />
          <svg
            className="navigation-map__plot"
            viewBox="0 0 100 100"
            role="img"
            aria-label={hasTrackPlot ? 'GPS track plot' : 'Mission route plan'}
          >
            <path
              className="navigation-map__route-plan"
              d="M 8 82 C 19 72, 25 64, 35 53 S 56 31, 86 14"
              fill="none"
            />
            <rect className="navigation-map__zone navigation-map__zone--surface" x="43" y="47" width="15" height="12" />
            <rect className="navigation-map__zone navigation-map__zone--underwater" x="62" y="24" width="15" height="12" />

            {buoyPairs.map((pair, index) => (
              <g
                key={`buoy-pair-${index + 1}`}
                className="navigation-map__buoy-pair"
                data-testid="buoy-pair"
                aria-label={`Buoy pair ${index + 1}`}
              >
                <circle className="navigation-map__buoy navigation-map__buoy--red" cx={pair.x - 1.2} cy={pair.y} r="1.35" />
                <circle className="navigation-map__buoy navigation-map__buoy--green" cx={pair.x + 1.2} cy={pair.y} r="1.35" />
              </g>
            ))}

            <g className="navigation-map__dock navigation-map__dock--start">
              <circle cx="8" cy="82" r="2.2" />
              <text x="8" y="88">START</text>
            </g>
            <g className="navigation-map__dock navigation-map__dock--finish">
              <circle cx="86" cy="14" r="2.2" />
              <text x="86" y="10">FINISH</text>
            </g>
            <g className="navigation-map__docking-balls">
              <circle cx="82" cy="14" r="1.25" />
              <circle cx="84" cy="14" r="1.25" />
              <circle cx="86" cy="14" r="1.25" />
            </g>

            {hasTrackPlot ? (
              <polyline
                className="navigation-map__track"
                points={trackPoints}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
              />
            ) : null}
            {projectedBoat ? (
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
            ) : null}
          </svg>
          {!projectedBoat ? (
            <div className="navigation-map__empty">
              <MapPin aria-hidden="true" size={28} />
              <strong>Waiting for GPS fix.</strong>
              <span>Mission route loaded. Live track will appear when telemetry is received.</span>
            </div>
          ) : null}
          <div className="navigation-map__readout">
            <span>{telemetry.position ? 'GPS position available' : 'GPS position unavailable'}</span>
            <span>{telemetry.track.length > 0 ? `GPS track · ${telemetry.track.length} points` : 'GPS track unavailable'}</span>
          </div>
        </div>

        <aside className="route-legend" aria-label="Mission route legend">
          <div className="route-legend__heading">
            <span>Course layout</span>
            <strong>ASV KKI 2026</strong>
          </div>
          <div className="route-legend__item">
            <span className="route-legend__swatch route-legend__swatch--buoys" aria-hidden="true" />
            <div><strong>Navigation</strong><span>10 red + green buoy pairs</span></div>
          </div>
          <div className="route-legend__item">
            <span className="route-legend__swatch route-legend__swatch--surface" aria-hidden="true" />
            <div><strong>Surface imaging</strong><span>Green mission zone</span></div>
          </div>
          <div className="route-legend__item">
            <span className="route-legend__swatch route-legend__swatch--underwater" aria-hidden="true" />
            <div><strong>Underwater imaging</strong><span>Blue mission zone</span></div>
          </div>
          <div className="route-legend__item">
            <span className="route-legend__swatch route-legend__swatch--dock" aria-hidden="true" />
            <div><strong>Finish dock</strong><span>3 blue docking balls</span></div>
          </div>
        </aside>
      </div>
    </section>
  )
}
