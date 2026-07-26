import { kolamDeliSite } from './mission-site'

import type { GeoCoordinate } from './mission-site'

export type SiteOverlayPoint = {
  x: number
  y: number
}

/**
 * Visual calibration for the Kolam Deli satellite composition.
 *
 * The course drawing is authored in the reference SVG coordinate system,
 * where the dock is at the lower-right of the canvas. The supplied site
 * image has the dock/pin at the upper-right of the pool, so the Y scale is
 * intentionally negative. This mirrors the drawing without changing the
 * mission simulation's stage order.
 */
export type SiteMapOverlayCalibration = {
  courseAnchor: SiteOverlayPoint
  mapAnchor: SiteOverlayPoint
  scaleX: number
  scaleY: number
  rotationDeg: number
}

export const kolamDeliOverlayCalibration: SiteMapOverlayCalibration = {
  courseAnchor: { x: 85.1, y: 85.8 },
  mapAnchor: { x: 50, y: 49 },
  scaleX: 0.093,
  scaleY: -0.224,
  rotationDeg: -20,
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

function validateOverlayCalibration(
  calibration: SiteMapOverlayCalibration,
): void {
  validateOverlayPoint(calibration.courseAnchor)
  validateOverlayPoint(calibration.mapAnchor)
  if (
    !Number.isFinite(calibration.scaleX) ||
    calibration.scaleX === 0 ||
    !Number.isFinite(calibration.scaleY) ||
    calibration.scaleY === 0 ||
    !Number.isFinite(calibration.rotationDeg)
  ) {
    throw new RangeError(
      'Overlay calibration scales must be finite and non-zero.',
    )
  }
}

function rotateOverlayPoint(
  point: SiteOverlayPoint,
  rotationDeg: number,
): SiteOverlayPoint {
  const radians = (rotationDeg * Math.PI) / 180
  const cosine = Math.cos(radians)
  const sine = Math.sin(radians)

  return {
    x: point.x * cosine - point.y * sine,
    y: point.x * sine + point.y * cosine,
  }
}

/**
 * Maps one reference-course point into the calibrated site-map SVG space.
 */
export function coursePointToSiteOverlay(
  point: SiteOverlayPoint,
  calibration: SiteMapOverlayCalibration = kolamDeliOverlayCalibration,
): SiteOverlayPoint {
  validateOverlayPoint(point)
  validateOverlayCalibration(calibration)

  const translated = {
    x: (point.x - calibration.courseAnchor.x) * calibration.scaleX,
    y: (point.y - calibration.courseAnchor.y) * calibration.scaleY,
  }
  const rotated = rotateOverlayPoint(translated, calibration.rotationDeg)

  return {
    x: calibration.mapAnchor.x + rotated.x,
    y: calibration.mapAnchor.y + rotated.y,
  }
}

/**
 * Converts a course-frame heading (0° = north, clockwise) to the heading
 * shown after the calibrated, mirrored overlay transform.
 */
export function courseHeadingToSiteOverlay(
  headingDeg: number,
  calibration: SiteMapOverlayCalibration = kolamDeliOverlayCalibration,
): number {
  if (!Number.isFinite(headingDeg)) {
    throw new RangeError('Overlay heading must be finite.')
  }
  validateOverlayCalibration(calibration)

  const radians = (headingDeg * Math.PI) / 180
  // The route heading convention uses a screen vector (sin(h), -cos(h)).
  const scaled = {
    x: Math.sin(radians) * calibration.scaleX,
    y: -Math.cos(radians) * calibration.scaleY,
  }
  const rotated = rotateOverlayPoint(scaled, calibration.rotationDeg)

  return ((Math.atan2(rotated.x, -rotated.y) * 180) / Math.PI + 360) % 360
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
