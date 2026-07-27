import { MapPin } from '@phosphor-icons/react'
import { useState } from 'react'

import {
  missionRoute,
  missionRouteHeading,
  missionRoutePosition,
  missionRouteTravelledPoints,
  missionStages,
} from '../lib/mission-simulation'
import { geoPointToCourse, kolamDeliSite } from '../lib/mission-site'
import {
  buildGoogleMapsSatelliteEmbedUrl,
  courseHeadingToSiteOverlay,
  coursePointToSiteOverlay,
} from '../lib/site-map-projection'
import { useOverlayNudge } from '../lib/use-overlay-nudge'

import type { NavigationTelemetry } from '../lib/navigation-types'
import type { MissionSimulationController } from '../lib/use-mission-simulation'
import type { SiteOverlayPoint } from '../lib/site-map-projection'

type NavigationMapProps = {
  telemetry: NavigationTelemetry
  simulation?: MissionSimulationController
  previewMode?: boolean
}

const buoyPairs = [
  { red: { x: 81.34, y: 67.51 }, green: { x: 87.33, y: 67.63 } },
  { red: { x: 77.9, y: 56.75 }, green: { x: 83.94, y: 56.75 } },
  { red: { x: 82.11, y: 46.45 }, green: { x: 88.13, y: 47.77 } },
  { red: { x: 60.43, y: 26.2 }, green: { x: 60.61, y: 20.23 } },
  { red: { x: 54.48, y: 26.34 }, green: { x: 54.49, y: 20.44 } },
  { red: { x: 48.11, y: 26.2 }, green: { x: 48.29, y: 20.34 } },
  { red: { x: 42.19, y: 26.2 }, green: { x: 42.19, y: 20.51 } },
  { red: { x: 18.59, y: 39.71 }, green: { x: 12.69, y: 38.77 } },
  { red: { x: 13.7, y: 50.05 }, green: { x: 7.78, y: 49.86 } },
  { red: { x: 13.19, y: 59.75 }, green: { x: 7.26, y: 60.62 } },
] as const

const siteMapEmbedUrl = buildGoogleMapsSatelliteEmbedUrl(
  kolamDeliSite.center,
  22,
)

function formatOverlayPoint(point: SiteOverlayPoint): string {
  return `${point.x},${point.y}`
}

function projectCourseRectangle(
  x: number,
  y: number,
  width: number,
  height: number,
): string {
  return [
    coursePointToSiteOverlay({ x, y }),
    coursePointToSiteOverlay({ x: x + width, y }),
    coursePointToSiteOverlay({ x: x + width, y: y + height }),
    coursePointToSiteOverlay({ x, y: y + height }),
  ]
    .map(formatOverlayPoint)
    .join(' ')
}

const siteMissionRoute = missionRoute.map((point) =>
  coursePointToSiteOverlay(point),
)
const courseRoutePoints = missionRoute
  .map((point) => `${point.x},${point.y}`)
  .join(' ')
const siteBuoyPairs = buoyPairs.map((pair) => ({
  red: coursePointToSiteOverlay(pair.red),
  green: coursePointToSiteOverlay(pair.green),
}))
const surfaceStageProgress =
  missionStages.find((stage) => stage.id === 'surface')?.routeProgress ?? 0.24
const underwaterStageProgress =
  missionStages.find((stage) => stage.id === 'underwater')?.routeProgress ?? 0.3
const surfaceStagePoint = missionRoutePosition(surfaceStageProgress)
const underwaterStagePoint = missionRoutePosition(underwaterStageProgress)
const siteSurfaceZonePoints = projectCourseRectangle(
  surfaceStagePoint.x - 2.5,
  surfaceStagePoint.y - 2.5,
  5,
  5,
)
const siteUnderwaterZonePoints = projectCourseRectangle(
  underwaterStagePoint.x - 2.5,
  underwaterStagePoint.y - 2.5,
  5,
  5,
)
const siteDock = coursePointToSiteOverlay({ x: 85.1, y: 85.8 })
const siteDockHeading = courseHeadingToSiteOverlay(missionRouteHeading(0))
const siteBuoyRadius = 0.72
const siteDockRadius = 1.7
const siteDockingBallRadius = 0.72
const siteDockingBalls = [
  coursePointToSiteOverlay({ x: 82.2, y: 89.47 }),
  coursePointToSiteOverlay({ x: 82.2, y: 92.14 }),
  coursePointToSiteOverlay({ x: 82.2, y: 95.27 }),
]

type SiteMapCanvasProps = {
  telemetry: NavigationTelemetry
  simulation?: MissionSimulationController
  simulationActive: boolean
  simulationComplete: boolean
  simulationHeading: number
}

function SiteMapCanvas({
  telemetry,
  simulation,
  simulationActive,
  simulationComplete,
  simulationHeading,
}: SiteMapCanvasProps) {
  const telemetryCoursePoints = telemetry.track.map((point) =>
    geoPointToCourse(point),
  )
  const telemetryCourseTrack = telemetryCoursePoints.map((point) =>
    coursePointToSiteOverlay(point),
  )
  const travelledPoints = simulation
    ? missionRouteTravelledPoints(simulation.progress).map((point) =>
        coursePointToSiteOverlay(point),
      )
    : telemetryCourseTrack
  const currentCoursePoint =
    simulationActive && simulation
      ? simulation.position
      : telemetry.position
        ? geoPointToCourse(telemetry.position)
        : telemetryCoursePoints.at(-1)
  const currentSitePoint = currentCoursePoint
    ? coursePointToSiteOverlay(currentCoursePoint)
    : undefined
  const heading =
    simulationActive && simulation
      ? simulationHeading
      : (telemetry.heading_deg ?? 0)
  const siteHeading = courseHeadingToSiteOverlay(heading)
  const { nudge, dragging, dragHandlers } = useOverlayNudge()

  return (
    <div
      className="navigation-map__canvas navigation-map__canvas--site"
      aria-label={`Geographic mission map at ${kolamDeliSite.name}`}
    >
      <iframe
        className="site-map__base"
        src={siteMapEmbedUrl}
        title="Kolam Deli satellite base map"
        loading="eager"
        tabIndex={-1}
      />
      <div className="site-map__wash" aria-hidden="true" />
      <div className="navigation-map__north" aria-label="North up">
        <span>N</span>
        <b>↑</b>
      </div>

      <svg
        className="site-map__overlay"
        viewBox="0 0 100 100"
        role="img"
        aria-label="ASV mission route"
      >
        <defs>
          <marker
            id="site-route-direction-arrow"
            markerWidth="5"
            markerHeight="5"
            refX="4.2"
            refY="2.5"
            orient="auto"
          >
            <path
              className="site-map__route-direction-arrow"
              d="M 0 0 L 5 2.5 L 0 5 Z"
            />
          </marker>
        </defs>
        <g
          className={`site-map__drag${dragging ? ' site-map__drag--active' : ''}`}
          data-testid="overlay-drag-layer"
          transform={`translate(${nudge.x} ${nudge.y}) translate(50 50) scale(${nudge.scale}) translate(-50 -50)`}
          {...dragHandlers}
        >
          <polyline
            className="site-map__route"
            points={siteMissionRoute.map(formatOverlayPoint).join(' ')}
            fill="none"
            markerEnd="url(#site-route-direction-arrow)"
          />

          <polygon
            className="site-map__zone site-map__zone--surface"
            data-testid="surface-zone"
            points={siteSurfaceZonePoints}
          />
          <polygon
            className="site-map__zone site-map__zone--underwater"
            data-testid="underwater-zone"
            points={siteUnderwaterZonePoints}
          />

          {siteBuoyPairs.map((pair, index) => (
            <g
              key={`site-buoy-pair-${index + 1}`}
              className="site-map__buoy-pair"
              data-testid="buoy-pair"
              aria-label={`Buoy pair ${index + 1}`}
            >
              <circle
                className="site-map__buoy site-map__buoy--red"
                cx={pair.red.x}
                cy={pair.red.y}
                r={siteBuoyRadius}
              />
              <circle
                className="site-map__buoy site-map__buoy--green"
                cx={pair.green.x}
                cy={pair.green.y}
                r={siteBuoyRadius}
              />
            </g>
          ))}

          <g className="site-map__dock">
            <circle cx={siteDock.x} cy={siteDock.y} r={siteDockRadius} />
            <path
              transform={`translate(${siteDock.x} ${siteDock.y}) rotate(${siteDockHeading})`}
              d="M 0 -3.4 L 1.5 -1.2 L 0 -1.8 L -1.5 -1.2 Z"
            />
          </g>
          <g className="site-map__docking-balls">
            {siteDockingBalls.map((point, index) => (
              <circle
                key={`site-docking-ball-${index + 1}`}
                cx={point.x}
                cy={point.y}
                r={siteDockingBallRadius}
              />
            ))}
          </g>

          {travelledPoints.length > 1 ? (
            <polyline
              className="site-map__travelled"
              data-testid={simulationActive ? 'simulation-track' : undefined}
              points={travelledPoints.map(formatOverlayPoint).join(' ')}
              fill="none"
            />
          ) : null}

          {currentSitePoint ? (
            <g
              className={`site-map__boat${
                simulationComplete ? ' site-map__boat--complete' : ''
              }`}
              data-testid={simulationActive ? 'simulation-boat' : 'boat-marker'}
              data-progress={simulation?.progress}
              data-heading={siteHeading}
              data-course-heading={heading}
              data-status={simulation?.status}
              aria-hidden="true"
              transform={`translate(${currentSitePoint.x} ${currentSitePoint.y}) rotate(${siteHeading})${
                simulationComplete ? ' scale(0.65)' : ''
              }`}
            >
              <circle r="3.7" />
              <path d="M 0 -4.5 L 2.7 3.5 L 0 2 L -2.7 3.5 Z" />
            </g>
          ) : null}
        </g>
      </svg>

      <div className="site-map__course-label">
        <span>COURSE OVERLAY</span>
        <strong>LINTASAN A</strong>
      </div>
      <div className="navigation-map__gnss">
        <span className="navigation-map__gnss-dot" />
        <span>GNSS LOCK · 12 SAT · ±0.8M</span>
      </div>
      <a
        className="site-map__attribution"
        href={kolamDeliSite.mapsUrl}
        target="_blank"
        rel="noreferrer"
      >
        Satellite imagery · Google Maps
      </a>
    </div>
  )
}

export function NavigationMap({
  telemetry,
  simulation,
  previewMode = false,
}: NavigationMapProps) {
  const [viewMode, setViewMode] = useState<'map' | 'course'>('map')
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
  const hasRealTelemetry =
    telemetry.position !== null || telemetry.track.length > 0
  // Outside the on-site preview the replay must never paint over a real fix.
  const simulationActive =
    simulation !== undefined &&
    (previewMode || (simulation.status !== 'idle' && !hasRealTelemetry))
  const simulationComplete = simulation?.status === 'complete'
  const simulationTravelledPoints = simulation
    ? missionRouteTravelledPoints(simulation.progress)
        .map((point) => `${point.x},${point.y}`)
        .join(' ')
    : ''
  const simulationHeading = simulation
    ? missionRouteHeading(simulation.progress)
    : 0
  const hasTrackPlot = pathPoints.length >= 2
  const showSiteMap = viewMode === 'map'

  return (
    <section className="navigation-map" aria-labelledby="navigation-map-title">
      <div className="panel-heading">
        <MapPin aria-hidden="true" />
        <div>
          <p className="eyebrow">Route telemetry</p>
          <h2 id="navigation-map-title">Mission route</h2>
        </div>
        <div className="navigation-map__heading-tools">
          <div
            className="navigation-map__view-switch"
            role="group"
            aria-label="Mission map view"
          >
            <button
              type="button"
              className={
                showSiteMap ? 'navigation-map__view-switch--active' : ''
              }
              aria-pressed={showSiteMap}
              onClick={() => setViewMode('map')}
            >
              Map
            </button>
            <button
              type="button"
              className={
                !showSiteMap ? 'navigation-map__view-switch--active' : ''
              }
              aria-pressed={!showSiteMap}
              onClick={() => setViewMode('course')}
            >
              Course
            </button>
          </div>
        </div>
      </div>

      <div className="navigation-map__layout">
        {showSiteMap ? (
          <SiteMapCanvas
            telemetry={telemetry}
            simulation={simulation}
            simulationActive={simulationActive}
            simulationComplete={simulationComplete}
            simulationHeading={simulationHeading}
          />
        ) : (
          <div
            className="navigation-map__canvas"
            aria-label={`Mission route and live boat track${previewMode ? ` at ${kolamDeliSite.name}` : ''}`}
          >
            {previewMode ? (
              <>
                <div
                  className="navigation-map__site-hud"
                  data-testid="site-context"
                >
                  <div className="navigation-map__site-hud-copy">
                    <strong>{kolamDeliSite.name.toUpperCase()}</strong>
                    <small>{kolamDeliSite.locality.toUpperCase()}</small>
                  </div>
                  <a
                    href={kolamDeliSite.mapsUrl}
                    target="_blank"
                    rel="noreferrer"
                    aria-label="Open Kolam Deli in Google Maps"
                  >
                    MAP
                  </a>
                </div>
                <div className="navigation-map__north" aria-label="North up">
                  <span>N</span>
                  <b>↑</b>
                </div>
                <div className="navigation-map__gnss">
                  <span className="navigation-map__gnss-dot" />
                  <span>GNSS LOCK · 12 SAT · ±0.8M</span>
                </div>
              </>
            ) : null}
            <svg
              className="navigation-map__plot"
              viewBox="0 0 100 110"
              role="img"
              aria-label={
                simulationActive
                  ? 'ASV mission route'
                  : hasTrackPlot
                    ? 'GPS track plot'
                    : 'Mission route plan'
              }
            >
              <defs>
                <pattern
                  id="mission-grid-pattern"
                  width="5"
                  height="5"
                  patternUnits="userSpaceOnUse"
                >
                  <path
                    className="navigation-map__grid-line"
                    d="M 5 0 L 0 0 L 0 5"
                    fill="none"
                  />
                </pattern>
                <marker
                  id="route-direction-arrow"
                  markerWidth="5"
                  markerHeight="5"
                  refX="4"
                  refY="2.5"
                  orient="auto"
                >
                  <path
                    className="navigation-map__route-direction-arrow"
                    d="M 0 0 L 5 2.5 L 0 5 Z"
                  />
                </marker>
              </defs>
              <rect
                className="navigation-map__grid-surface"
                x="0"
                y="0"
                width="100"
                height="100"
              />
              <g className="navigation-map__axes" aria-hidden="true">
                {['A', 'B', 'C', 'D', 'E'].map((label, index) => (
                  <text key={label} x={1 + index * 20.25} y="4">
                    {label}
                  </text>
                ))}
                {['5', '4', '3', '2', '1'].map((label, index) => (
                  <text key={label} x="2" y={17 + index * 20}>
                    {label}
                  </text>
                ))}
              </g>
              <polyline
                className="navigation-map__route-plan"
                points={courseRoutePoints}
                fill="none"
              />
              <g
                className="navigation-map__route-directions"
                aria-hidden="true"
              >
                <path d="M 64 94 L 79 93" />
              </g>
              {!simulationActive && hasTrackPlot ? (
                <polyline
                  className="navigation-map__track"
                  points={trackPoints}
                  fill="none"
                />
              ) : null}
              <g className="navigation-map__mission-zone">
                <rect
                  className="navigation-map__zone navigation-map__zone--surface"
                  data-testid="surface-zone"
                  x="25"
                  y="88"
                  width="5"
                  height="3"
                />
              </g>
              <g className="navigation-map__mission-zone">
                <rect
                  className="navigation-map__zone navigation-map__zone--underwater"
                  data-testid="underwater-zone"
                  x="15"
                  y="78"
                  width="5"
                  height="4"
                />
              </g>

              {buoyPairs.map((pair, index) => (
                <g
                  key={`buoy-pair-${index + 1}`}
                  className="navigation-map__buoy-pair"
                  data-testid="buoy-pair"
                  aria-label={`Buoy pair ${index + 1}`}
                >
                  <circle
                    className="navigation-map__buoy navigation-map__buoy--red"
                    cx={pair.red.x}
                    cy={pair.red.y}
                    r="1.1"
                  />
                  <circle
                    className="navigation-map__buoy navigation-map__buoy--green"
                    cx={pair.green.x}
                    cy={pair.green.y}
                    r="1.1"
                  />
                </g>
              ))}

              <g className="navigation-map__dock navigation-map__dock--start">
                <path d="M 85.1 84.3 L 86.6 85.8 L 85.1 87.3 L 83.6 85.8 Z" />
              </g>
              <g className="navigation-map__course-tag" aria-hidden="true">
                <rect x="42" y="99.5" width="20" height="7" rx="1.2" />
                <text x="52" y="104.1">
                  LINTASAN A
                </text>
              </g>
              <g className="navigation-map__start-finish" aria-hidden="true">
                <ellipse cx="85" cy="105.2" rx="11" ry="4.1" />
                <text x="85" y="104.5">
                  Start /
                </text>
                <text x="85" y="107">
                  Finish
                </text>
              </g>
              <g className="navigation-map__docking-balls">
                <rect x="82.3" y="88.2" width="4.9" height="8" rx="0.5" />
                <circle cx="82.2" cy="89.47" r="1.3" />
                <circle cx="82.2" cy="92.14" r="1.3" />
                <circle cx="82.2" cy="95.27" r="1.3" />
              </g>

              {simulationActive ? (
                <>
                  <polyline
                    className="navigation-map__simulation-track"
                    data-testid="simulation-track"
                    points={simulationTravelledPoints}
                    fill="none"
                  />
                  <g
                    className={`navigation-map__simulation-boat${
                      simulationComplete
                        ? ' navigation-map__simulation-boat--complete'
                        : ''
                    }`}
                    data-testid="simulation-boat"
                    data-progress={simulation.progress}
                    data-heading={simulationHeading}
                    data-status={simulation.status}
                    aria-hidden="true"
                    transform={`translate(${simulation.position.x} ${simulation.position.y}) rotate(${simulationHeading})${
                      simulationComplete ? ' scale(0.58)' : ''
                    }`}
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
                    telemetry.heading_deg === null
                      ? ''
                      : ` rotate(${telemetry.heading_deg})`
                  }`}
                >
                  {telemetry.heading_deg === null ? (
                    <circle className="navigation-map__boat-dot" r="2.8" />
                  ) : (
                    <path
                      className="navigation-map__boat-arrow"
                      d="M 0 -5 L 3 4 L 0 2 L -3 4 Z"
                    />
                  )}
                </g>
              ) : null}
            </svg>
            {!projectedBoat && !simulationActive ? (
              <div className="navigation-map__empty">
                <MapPin aria-hidden="true" size={28} />
                <strong>Waiting for GPS fix.</strong>
                <span>
                  Mission route loaded. Live track will appear when telemetry is
                  received.
                </span>
              </div>
            ) : null}
          </div>
        )}
        <div className="navigation-map__readout">
          <span>
            {simulationActive
              ? `Lintasan A · ${Math.round(simulation.progress * 100)}%`
              : telemetry.position
                ? 'GPS position available'
                : 'GPS position unavailable'}
          </span>
          <span>
            {simulationActive
              ? 'ASV navigation · mission active'
              : telemetry.track.length > 0
                ? `GPS track · ${telemetry.track.length} points`
                : 'GPS track unavailable'}
          </span>
          {previewMode && telemetry.position ? (
            <span className="navigation-map__coordinate">
              {telemetry.position.latitude.toFixed(6)}°{' '}
              {telemetry.position.latitude >= 0 ? 'N' : 'S'} ·{' '}
              {telemetry.position.longitude.toFixed(6)}°{' '}
              {telemetry.position.longitude >= 0 ? 'E' : 'W'}
            </span>
          ) : null}
        </div>
      </div>
    </section>
  )
}
