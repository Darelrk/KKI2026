import {
  missionDurationMs,
  missionRouteHeading,
  missionRoutePosition,
} from './mission-simulation'

import type {
  MissionRoutePoint,
  MissionSimulationStatus,
} from './mission-simulation'
import type { AsvTelemetry } from './asv-telemetry'

const earthRadiusMeters = 6_371_008.8
const maximumTrackPoints = 121

export type GeoCoordinate = {
  latitude: number
  longitude: number
}

export type MissionSite = {
  id: string
  name: string
  locality: string
  mapsUrl: string
  center: GeoCoordinate
  courseReference: MissionRoutePoint
  metersPerUnit: {
    x: number
    y: number
  }
  /**
   * Compass bearing of the course's upward SVG direction, measured clockwise
   * from true north.
   */
  courseUpBearingDeg: number
}

export const kolamDeliSite = {
  id: 'kolam-deli',
  name: 'Kolam Deli',
  locality: 'Medan, Sumatera Utara',
  mapsUrl: 'https://maps.app.goo.gl/apdH17mPbHuK6Rxd9',
  center: {
    latitude: 3.602405,
    longitude: 98.681353,
  },
  courseReference: {
    x: 50,
    y: 50,
  },
  metersPerUnit: {
    x: 0.12,
    y: 0.1,
  },
  courseUpBearingDeg: 0,
} satisfies MissionSite

export type MissionTelemetryInput = {
  progress: number
  elapsedMs: number
  status: MissionSimulationStatus
  startedAtMs: number
  site?: MissionSite
}

function degreesToRadians(value: number): number {
  return (value * Math.PI) / 180
}

function radiansToDegrees(value: number): number {
  return (value * 180) / Math.PI
}

function normalizeDegrees(value: number): number {
  return ((value % 360) + 360) % 360
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value))
}

function validateSite(site: MissionSite): void {
  if (
    !Number.isFinite(site.metersPerUnit.x) ||
    !Number.isFinite(site.metersPerUnit.y) ||
    site.metersPerUnit.x <= 0 ||
    site.metersPerUnit.y <= 0
  ) {
    throw new RangeError('Mission-site scale must be finite and positive.')
  }

  if (
    !Number.isFinite(site.center.latitude) ||
    !Number.isFinite(site.center.longitude) ||
    Math.abs(site.center.latitude) >= 90 ||
    Math.abs(site.center.longitude) > 180
  ) {
    throw new RangeError('Mission-site center must be a valid GPS coordinate.')
  }
}

export function coursePointToGeo(
  point: MissionRoutePoint,
  site: MissionSite = kolamDeliSite,
): GeoCoordinate {
  validateSite(site)

  const localEastMeters =
    (point.x - site.courseReference.x) * site.metersPerUnit.x
  const localNorthMeters =
    (site.courseReference.y - point.y) * site.metersPerUnit.y
  const bearingRadians = degreesToRadians(site.courseUpBearingDeg)
  const eastMeters =
    localEastMeters * Math.cos(bearingRadians) +
    localNorthMeters * Math.sin(bearingRadians)
  const northMeters =
    -localEastMeters * Math.sin(bearingRadians) +
    localNorthMeters * Math.cos(bearingRadians)
  const centerLatitudeRadians = degreesToRadians(site.center.latitude)

  return {
    latitude:
      site.center.latitude + radiansToDegrees(northMeters / earthRadiusMeters),
    longitude:
      site.center.longitude +
      radiansToDegrees(
        eastMeters / (earthRadiusMeters * Math.cos(centerLatitudeRadians)),
      ),
  }
}

export function geoPointToCourse(
  point: GeoCoordinate,
  site: MissionSite = kolamDeliSite,
): MissionRoutePoint {
  validateSite(site)

  const centerLatitudeRadians = degreesToRadians(site.center.latitude)
  const eastMeters =
    degreesToRadians(point.longitude - site.center.longitude) *
    earthRadiusMeters *
    Math.cos(centerLatitudeRadians)
  const northMeters =
    degreesToRadians(point.latitude - site.center.latitude) * earthRadiusMeters
  const bearingRadians = degreesToRadians(site.courseUpBearingDeg)
  const localEastMeters =
    eastMeters * Math.cos(bearingRadians) -
    northMeters * Math.sin(bearingRadians)
  const localNorthMeters =
    eastMeters * Math.sin(bearingRadians) +
    northMeters * Math.cos(bearingRadians)

  return {
    x: site.courseReference.x + localEastMeters / site.metersPerUnit.x,
    y: site.courseReference.y - localNorthMeters / site.metersPerUnit.y,
  }
}

export function courseHeadingToGeo(
  courseHeadingDeg: number,
  site: MissionSite = kolamDeliSite,
): number {
  return normalizeDegrees(courseHeadingDeg + site.courseUpBearingDeg)
}

function physicalDistanceMeters(
  start: MissionRoutePoint,
  end: MissionRoutePoint,
  site: MissionSite,
): number {
  return Math.hypot(
    (end.x - start.x) * site.metersPerUnit.x,
    (end.y - start.y) * site.metersPerUnit.y,
  )
}

function missionSpeedMetersPerSecond(
  progress: number,
  site: MissionSite,
): number {
  const sampleProgress = 1 / (maximumTrackPoints - 1)
  const startProgress =
    progress >= 1
      ? Math.max(0, progress - sampleProgress)
      : Math.max(0, progress)
  const endProgress =
    progress >= 1 ? progress : Math.min(1, progress + sampleProgress)
  const elapsedSeconds =
    ((endProgress - startProgress) * missionDurationMs) / 1000

  if (elapsedSeconds <= 0) {
    return 0
  }

  return (
    physicalDistanceMeters(
      missionRoutePosition(startProgress),
      missionRoutePosition(endProgress),
      site,
    ) / elapsedSeconds
  )
}

export function missionTelemetryAt({
  progress,
  elapsedMs,
  status,
  startedAtMs,
  site = kolamDeliSite,
}: MissionTelemetryInput): AsvTelemetry {
  validateSite(site)

  const clampedProgress = clamp(Number.isFinite(progress) ? progress : 0, 0, 1)
  const clampedElapsedMs = clamp(
    Number.isFinite(elapsedMs) ? elapsedMs : 0,
    0,
    missionDurationMs,
  )
  const trackPointCount =
    clampedProgress === 0
      ? 1
      : Math.min(
          maximumTrackPoints,
          Math.max(
            2,
            Math.floor(clampedProgress * (maximumTrackPoints - 1)) + 1,
          ),
        )
  const capturedAtMs = startedAtMs + clampedElapsedMs
  const track = Array.from({ length: trackPointCount }, (_, index) => {
    const fraction = trackPointCount === 1 ? 0 : index / (trackPointCount - 1)
    const sampleProgress = clampedProgress * fraction
    const sampleElapsedMs = clampedElapsedMs * fraction

    return {
      ...coursePointToGeo(missionRoutePosition(sampleProgress), site),
      captured_at: new Date(startedAtMs + sampleElapsedMs).toISOString(),
    }
  })
  const position = track.at(-1) ?? {
    ...coursePointToGeo(missionRoutePosition(clampedProgress), site),
    captured_at: new Date(capturedAtMs).toISOString(),
  }
  const capturedAt = new Date(capturedAtMs).toISOString()

  return {
    connected: true,
    position,
    heading_deg: courseHeadingToGeo(missionRouteHeading(clampedProgress), site),
    speed_mps:
      status === 'running'
        ? missionSpeedMetersPerSecond(clampedProgress, site)
        : 0,
    captured_at: capturedAt,
    heartbeat_at: capturedAt,
    track,
  }
}
