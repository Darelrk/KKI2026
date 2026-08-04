import { MapPin } from '@phosphor-icons/react'

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
  const telemetryCoursePoints = pathPoints.map((point) =>
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
          {simulationActive ? (
            <polyline
              className="site-map__route"
              points={siteMissionRoute.map(formatOverlayPoint).join(' ')}
              fill="none"
              markerEnd="url(#site-route-direction-arrow)"
            />
          ) : null}

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
              data-testid={simulationActive ? 'simulation-track' : 'gps-track'}
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

      {!currentSitePoint && !simulationActive ? (
        <div className="navigation-map__empty">
          <MapPin aria-hidden="true" size={28} />
          <strong>Waiting for GPS fix.</strong>
          <span>
            Mission route loaded. Live track will appear when telemetry is
            received.
          </span>
        </div>
      ) : null}
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
  // Keep the replay boat at the start dock before the operator starts it.
  const simulationActive = simulation !== undefined
  const simulationRunning =
    simulationActive && (previewMode || simulation?.status !== 'idle')
  const simulationComplete = simulation?.status === 'complete'
  const simulationHeading = simulation
    ? missionRouteHeading(simulation.progress)
    : 0

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
              className="navigation-map__view-switch--active"
              aria-pressed="true"
              disabled
            >
              Map
            </button>
          </div>
        </div>
      </div>

      <div className="navigation-map__layout">
        <SiteMapCanvas
          telemetry={telemetry}
          simulation={simulation}
          simulationActive={simulationActive}
          simulationComplete={simulationComplete}
          simulationHeading={simulationHeading}
        />
        <div className="navigation-map__readout">
          <span>
            {simulationRunning
              ? `Lintasan A · ${Math.round(simulation.progress * 100)}%`
              : telemetry.position
                ? 'GPS position available'
                : 'GPS position unavailable'}
          </span>
          <span>
            {simulationRunning
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
