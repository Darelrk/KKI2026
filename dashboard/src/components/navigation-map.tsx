import { MapPin } from '@phosphor-icons/react'

import { missionRoute } from '../lib/mission-simulation'

import type { NavigationTelemetry } from '../lib/navigation-types'
import type { MissionSimulationController } from '../lib/use-mission-simulation'

type NavigationMapProps = {
  telemetry: NavigationTelemetry
  simulation?: MissionSimulationController
}


const buoyPairs = [
  { x: 19, y: 75 },
  { x: 15, y: 59 },
  { x: 18, y: 42 },
  { x: 29, y: 25 },
  { x: 42, y: 19 },
  { x: 54, y: 18 },
  { x: 64, y: 21 },
  { x: 69, y: 34 },
  { x: 64, y: 51 },
  { x: 70, y: 69 },
] as const

const simulationTrackPoints = missionRoute.map((point) => `${point.x},${point.y}`).join(' ')


export function NavigationMap({ telemetry, simulation }: NavigationMapProps) {
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
  const projectPoint = (point: (typeof pathPoints)[number]) => ({
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
  const simulationActive = simulation !== undefined && simulation.status !== 'idle'
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
            aria-label={simulationActive ? 'Simulation route replay' : hasTrackPlot ? 'GPS track plot' : 'Mission route plan'}
          >
            <path
              className="navigation-map__route-plan"
              d="M 78 80 C 66 87, 52 89, 33 84 S 12 72, 14 53 S 22 27, 39 20 S 61 16, 66 24 S 70 43, 61 56 S 65 69, 78 80"
              fill="none"
            />
            {!simulationActive && hasTrackPlot ? (
              <polyline
                className="navigation-map__track"
                points={trackPoints}
                fill="none"
              />
            ) : null}
            <rect
              className="navigation-map__zone navigation-map__zone--surface"
              data-testid="surface-zone"
              x="20"
              y="67"
              width="18"
              height="12"
            />
            <rect
              className="navigation-map__zone navigation-map__zone--underwater"
              data-testid="underwater-zone"
              x="61"
              y="61"
              width="17"
              height="13"
            />

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
              <circle cx="78" cy="80" r="2.2" />
              <text x="78" y="87">START</text>
            </g>
            <g className="navigation-map__dock navigation-map__dock--finish">
              <circle cx="78" cy="80" r="2.2" />
              <text x="78" y="74">DOCK</text>
            </g>
            <g className="navigation-map__docking-balls">
              <circle cx="74" cy="80" r="1.25" />
              <circle cx="76" cy="80" r="1.25" />
              <circle cx="78" cy="80" r="1.25" />
            </g>

            {simulationActive ? (
              <>
                <polyline
                  className="navigation-map__simulation-track"
                  data-testid="simulation-track"
                  points={simulationTrackPoints}
                  fill="none"
                />
                <g
                  className="navigation-map__simulation-boat"
                  data-testid="simulation-boat"
                  data-progress={simulation?.progress}
                  aria-hidden="true"
                  transform={`translate(${simulation?.position.x} ${simulation?.position.y})`}
                >
                  <path d="M 0 -5 L 3 4 L 0 2 L -3 4 Z" />
                </g>
              </>
            ) : projectedBoat ? (
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
          {!projectedBoat && !simulationActive ? (
            <div className="navigation-map__empty">
              <MapPin aria-hidden="true" size={28} />
              <strong>Waiting for GPS fix.</strong>
              <span>Mission route loaded. Live track will appear when telemetry is received.</span>
            </div>
          ) : null}
          <div className="navigation-map__readout">
            <span>
              {simulationActive
                ? `Simulation route · ${Math.round((simulation?.progress ?? 0) * 100)}%`
                : telemetry.position
                  ? 'GPS position available'
                  : 'GPS position unavailable'}
            </span>
            <span>
              {simulationActive
                ? 'Local replay · no Pixhawk command'
                : telemetry.track.length > 0
                  ? `GPS track · ${telemetry.track.length} points`
                  : 'GPS track unavailable'}
            </span>
          </div>
        </div>

      </div>
    </section>
  )
}
