import { geoPointToCourse, kolamDeliSite } from './mission-site'

import type { GeoCoordinate } from './mission-site'

export type SiteOverlayPoint = {
  x: number
  y: number
}

function validateCoordinate(point: GeoCoordinate): void {
  if (
    !Number.isFinite(point.latitude) ||
    !Number.isFinite(point.longitude) ||
    point.latitude < -90 ||
    point.latitude > 90 ||
    point.longitude < -180 ||
    point.longitude > 180
  ) {
    throw new RangeError('Map point must be a valid GPS coordinate.')
  }
}

function validateOverlayPoint(point: SiteOverlayPoint): void {
  if (!Number.isFinite(point.x) || !Number.isFinite(point.y)) {
    throw new RangeError('Overlay point must contain finite x/y values.')
  }
}

// SVG source coordinates use course * 5.5 - (30, 104).
// This is asset geometry, not a hardcoded map location.
const lintasanSvgFrame = {
  width: 464,
  height: 425,
  offsetX: 30,
  offsetY: 104,
  pixelsPerCourseUnit: 5.5,
} as const

/** Maps a reference-course point into the supplied SVG overlay frame. */
export function coursePointToLintasanOverlay(
  point: SiteOverlayPoint,
): SiteOverlayPoint {
  validateOverlayPoint(point)

  return {
    x:
      ((point.x * lintasanSvgFrame.pixelsPerCourseUnit -
        lintasanSvgFrame.offsetX) /
        lintasanSvgFrame.width) *
      100,
    y:
      ((point.y * lintasanSvgFrame.pixelsPerCourseUnit -
        lintasanSvgFrame.offsetY) /
        lintasanSvgFrame.height) *
      100,
  }
}

/**
 * Keeps the SVG overlay aligned when the live map center changes.
 * The center is supplied by runtime telemetry; the site only defines the
 * course coordinate frame used to calculate the geographic translation.
 */
export function lintasanOverlayShiftForMapCenter(
  mapCenter: GeoCoordinate,
): SiteOverlayPoint {
  validateCoordinate(mapCenter)

  const siteCenter = coursePointToLintasanOverlay(kolamDeliSite.courseReference)
  const liveMapCenter = coursePointToLintasanOverlay(
    geoPointToCourse(mapCenter),
  )

  return {
    x: siteCenter.x - liveMapCenter.x,
    y: siteCenter.y - liveMapCenter.y,
  }
}

/**
 * Builds the lightweight Google Maps satellite embed used by the on-site
 * preview. `ll` centers the view without dropping a marker pin; `q` is
 * deliberately omitted because it forces a red marker over the course.
 */
export function buildGoogleMapsSatelliteEmbedUrl(
  center: GeoCoordinate = kolamDeliSite.center,
  zoom = 21,
): string {
  validateCoordinate(center)
  if (!Number.isInteger(zoom) || zoom < 1 || zoom > 22) {
    throw new RangeError('Google Maps zoom must be an integer from 1 to 22.')
  }

  const url = new URL('https://maps.google.com/maps')
  url.searchParams.set('ll', `${center.latitude},${center.longitude}`)
  url.searchParams.set('z', String(zoom))
  url.searchParams.set('t', 'k')
  url.searchParams.set('output', 'embed')

  return url.toString()
}
