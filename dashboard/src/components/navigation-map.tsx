import { ArrowClockwise, MapPin } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'

import { kolamDeliSite } from '../lib/mission-site'
import {
  buildGoogleMapsSatelliteEmbedUrl,
  lintasanOverlayShiftForMapCenter,
} from '../lib/site-map-projection'
import { useOverlayNudge } from '../lib/use-overlay-nudge'
import type { OverlayNudgeControls } from '../lib/use-overlay-nudge'

import type { NavigationTelemetry } from '../lib/navigation-types'
import type { GeoCoordinate } from '../lib/mission-site'
import type { MissionSimulationController } from '../lib/use-mission-simulation'

type NavigationMapProps = {
  telemetry: NavigationTelemetry
  simulation?: MissionSimulationController
  previewMode?: boolean
}

type SiteMapCanvasProps = {
  mapCenter: GeoCoordinate
  nudge: OverlayNudgeControls['nudge']
  dragging: OverlayNudgeControls['dragging']
  dragHandlers: OverlayNudgeControls['dragHandlers']
  showGpsWaiting: boolean
}

function SiteMapCanvas({
  mapCenter,
  nudge,
  dragging,
  dragHandlers,
  showGpsWaiting,
}: SiteMapCanvasProps) {
  const overlayShift = lintasanOverlayShiftForMapCenter(mapCenter)
  const dragTransform = `translate(${overlayShift.x + nudge.x} ${overlayShift.y + nudge.y}) translate(50 50) scale(${nudge.scale}) translate(-50 -50)`

  return (
    <div
      className="navigation-map__canvas navigation-map__canvas--site"
      aria-label={kolamDeliSite.name}
    >
      <iframe
        className="site-map__base"
        src={buildGoogleMapsSatelliteEmbedUrl(mapCenter, 22)}
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
        aria-label="Lintasan ASV"
      >
        <g
          className={
            'site-map__drag' + (dragging ? ' site-map__drag--active' : '')
          }
          data-testid="overlay-drag-layer"
          transform={dragTransform}
          {...dragHandlers}
        >
          <image
            className="site-map__course-asset"
            data-testid="course-svg-overlay"
            href="/lintasan-transparan.svg"
            x="0"
            y="0"
            width="100"
            height="100"
            preserveAspectRatio="none"
            role="img"
            aria-label="Lintasan ASV"
          />
        </g>
      </svg>
      {showGpsWaiting ? (
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
  const simulationRunning =
    simulation !== undefined && (previewMode || simulation.status !== 'idle')
  const liveCenter = telemetry.position ?? telemetry.track.at(-1) ?? null
  const [mapCenter, setMapCenter] = useState<GeoCoordinate>(() =>
    previewMode ? kolamDeliSite.center : (liveCenter ?? kolamDeliSite.center),
  )
  const [mapRefreshKey, setMapRefreshKey] = useState(0)
  const { nudge, dragging, dragHandlers } = useOverlayNudge()

  useEffect(() => {
    if (
      !previewMode &&
      mapCenter === kolamDeliSite.center &&
      liveCenter !== null
    ) {
      setMapCenter(liveCenter)
    }
  }, [liveCenter, mapCenter, previewMode])

  const refreshMap = () => {
    setMapRefreshKey((current) => current + 1)
  }

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
          <button
            type="button"
            className="navigation-map__refresh"
            onClick={refreshMap}
            title="Refresh map"
          >
            <ArrowClockwise aria-hidden="true" size={14} />
            <span>Refresh map</span>
          </button>
        </div>
      </div>

      <div className="navigation-map__layout">
        <SiteMapCanvas
          key={mapRefreshKey}
          mapCenter={mapCenter}
          nudge={nudge}
          dragging={dragging}
          dragHandlers={dragHandlers}
          showGpsWaiting={
            simulation === undefined &&
            telemetry.position === null &&
            telemetry.track.length === 0
          }
        />
        <div className="navigation-map__readout">
          <span>
            {simulationRunning
              ? 'Lintasan A · ' + Math.round(simulation.progress * 100) + '%'
              : telemetry.position
                ? 'GPS position available'
                : 'GPS position unavailable'}
          </span>
          <span>
            {simulationRunning
              ? 'ASV navigation · mission active'
              : telemetry.track.length > 0
                ? 'GPS track · ' + telemetry.track.length + ' points'
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
