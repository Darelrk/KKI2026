import { MapPin, Waves } from '@phosphor-icons/react'

import type { NavigationTelemetry } from '../lib/navigation-types'

type NavigationMapProps = {
  telemetry: NavigationTelemetry
}

export function NavigationMap({ telemetry }: NavigationMapProps) {
  const longitudes = telemetry.track.map((point) => point.longitude)
  const latitudes = telemetry.track.map((point) => point.latitude)
  const minLongitude = Math.min(...longitudes)
  const maxLongitude = Math.max(...longitudes)
  const minLatitude = Math.min(...latitudes)
  const maxLatitude = Math.max(...latitudes)
  const longitudeRange = maxLongitude - minLongitude || 1
  const latitudeRange = maxLatitude - minLatitude || 1
  const trackPoints = telemetry.track
    .map((point) => {
      const x = 10 + ((point.longitude - minLongitude) / longitudeRange) * 80
      const y = 90 - ((point.latitude - minLatitude) / latitudeRange) * 80
      return `${x},${y}`
    })
    .join(' ')
  const lastTrackPoint = telemetry.track.at(-1)
  const lastTrackX = lastTrackPoint
    ? 10 + ((lastTrackPoint.longitude - minLongitude) / longitudeRange) * 80
    : null
  const lastTrackY = lastTrackPoint
    ? 90 - ((lastTrackPoint.latitude - minLatitude) / latitudeRange) * 80
    : null

  return (
    <section className="navigation-map" aria-labelledby="navigation-map-title">
      <div className="panel-heading">
        <MapPin aria-hidden="true" />
        <div>
          <p className="eyebrow">Route telemetry</p>
          <h2 id="navigation-map-title">Navigation map</h2>
        </div>
        <span className="mockup-badge">MAP MOCKUP</span>
      </div>

      <div className="navigation-map__canvas" aria-label="Venue map placeholder">
        <div className="navigation-map__grid" aria-hidden="true" />
        {telemetry.track.length > 0 ? (
          <svg className="navigation-map__plot" viewBox="0 0 100 100" role="img" aria-label="GPS track plot">
            <polyline points={trackPoints} fill="none" stroke="currentColor" strokeWidth="1.4" />
            {lastTrackX !== null && lastTrackY !== null ? (
              <circle cx={lastTrackX} cy={lastTrackY} r="2.8" fill="currentColor" />
            ) : null}
          </svg>
        ) : null}
        <div className="navigation-map__empty">
          <MapPin aria-hidden="true" size={28} />
          <strong>Venue coordinates unavailable</strong>
          <span>Petunjuk Teknis ASV belum tersedia. Posisi marker tidak direka.</span>
        </div>
        <div className="navigation-map__readout">
          <span>{telemetry.position ? 'GPS position available' : 'GPS position unavailable'}</span>
          <span>{telemetry.track.length > 0 ? `GPS track · ${telemetry.track.length} points` : 'GPS track unavailable'}</span>
        </div>
      </div>

      <div className="navigation-map__legend" aria-label="Mission map markers">
        <span><i className="map-key map-key--start" />START</span>
        <span><i className="map-key map-key--finish" />Finish / docking</span>
        <span><i className="map-key map-key--route" />10 buoy pairs: red + green</span>
        <span><i className="map-key map-key--surface" />Surface zone / green</span>
        <span><i className="map-key map-key--underwater" />Underwater zone / blue</span>
        <span><i className="map-key map-key--dock" />3 docking balls / blue</span>
      </div>

      <p className="navigation-map__note">
        <Waves aria-hidden="true" size={14} />
        Track hanya menggambar titik GPS yang diterima; venue map menunggu Petunjuk Teknis final.
      </p>
    </section>
  )
}
