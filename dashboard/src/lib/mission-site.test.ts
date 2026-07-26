import { describe, expect, it } from 'vitest'

import { asvTelemetrySchema } from './asv-telemetry'
import {
  missionDurationMs,
  missionRoute,
  missionRouteHeading,
  missionRoutePosition,
} from './mission-simulation'
import {
  courseHeadingToGeo,
  coursePointToGeo,
  geoPointToCourse,
  kolamDeliSite,
  missionTelemetryAt,
} from './mission-site'

import type { MissionSite } from './mission-site'

const startedAtMs = Date.parse('2026-07-26T03:00:00.000Z')

describe('Kolam Deli mission site', () => {
  it('defines the requested site center and course calibration', () => {
    expect(kolamDeliSite).toMatchObject({
      id: 'kolam-deli',
      name: 'Kolam Deli',
      center: {
        latitude: 3.602405,
        longitude: 98.681353,
      },
      courseReference: { x: 50, y: 50 },
      metersPerUnit: { x: 0.12, y: 0.1 },
      courseUpBearingDeg: 0,
    })
  })

  it('maps the course reference to the site center and preserves axis direction', () => {
    expect(coursePointToGeo({ x: 50, y: 50 })).toEqual(kolamDeliSite.center)

    const east = coursePointToGeo({ x: 51, y: 50 })
    const south = coursePointToGeo({ x: 50, y: 51 })

    expect(east.longitude).toBeGreaterThan(kolamDeliSite.center.longitude)
    expect(east.latitude).toBeCloseTo(kolamDeliSite.center.latitude, 10)
    expect(south.latitude).toBeLessThan(kolamDeliSite.center.latitude)
    expect(south.longitude).toBeCloseTo(kolamDeliSite.center.longitude, 10)
  })

  it('round-trips every normalized route vertex through geographic coordinates', () => {
    for (const routePoint of missionRoute) {
      const roundTrip = geoPointToCourse(coursePointToGeo(routePoint))

      expect(roundTrip.x).toBeCloseTo(routePoint.x, 7)
      expect(roundTrip.y).toBeCloseTo(routePoint.y, 7)
    }
  })

  it('rotates points and headings using the configured course-up bearing', () => {
    const eastFacingSite = {
      ...kolamDeliSite,
      courseUpBearingDeg: 90,
    } satisfies MissionSite
    const courseUp = coursePointToGeo({ x: 50, y: 49 }, eastFacingSite)

    expect(courseUp.longitude).toBeGreaterThan(eastFacingSite.center.longitude)
    expect(courseUp.latitude).toBeCloseTo(eastFacingSite.center.latitude, 10)
    expect(courseHeadingToGeo(280, eastFacingSite)).toBe(10)
  })
})

describe('Kolam Deli mission telemetry', () => {
  it('derives deterministic position, heading, timestamps, and track from progress', () => {
    const telemetry = missionTelemetryAt({
      progress: 0.5,
      elapsedMs: missionDurationMs / 2,
      status: 'running',
      startedAtMs,
    })
    const expectedPosition = coursePointToGeo(missionRoutePosition(0.5))

    expect(telemetry.position).toMatchObject(expectedPosition)
    expect(telemetry.position).toEqual(telemetry.track.at(-1))
    expect(telemetry.heading_deg).toBeCloseTo(missionRouteHeading(0.5), 10)
    expect(telemetry.captured_at).toBe('2026-07-26T03:00:15.000Z')
    expect(telemetry.heartbeat_at).toBe(telemetry.captured_at)
    expect(telemetry.track).toHaveLength(61)
    expect(telemetry.track[0].captured_at).toBe('2026-07-26T03:00:00.000Z')
    expect(telemetry.speed_mps).toBeGreaterThan(0)
    expect(telemetry.speed_mps).toBeLessThan(2)
    expect(asvTelemetrySchema.safeParse(telemetry).success).toBe(true)
  })

  it.each(['idle', 'paused', 'complete'] as const)(
    'reports zero physical speed while %s',
    (status) => {
      const telemetry = missionTelemetryAt({
        progress: status === 'complete' ? 1 : 0.5,
        elapsedMs:
          status === 'complete' ? missionDurationMs : missionDurationMs / 2,
        status,
        startedAtMs,
      })

      expect(telemetry.speed_mps).toBe(0)
    },
  )

  it('keeps a complete closed route within 121 points and returns to the dock', () => {
    const telemetry = missionTelemetryAt({
      progress: 1,
      elapsedMs: missionDurationMs,
      status: 'complete',
      startedAtMs,
    })
    const first = telemetry.track[0]
    const last = telemetry.track.at(-1)

    expect(telemetry.track).toHaveLength(121)
    expect(last?.latitude).toBeCloseTo(first.latitude, 10)
    expect(last?.longitude).toBeCloseTo(first.longitude, 10)
    expect(telemetry.position).toEqual(last)
    expect(telemetry.captured_at).toBe('2026-07-26T03:00:30.000Z')
  })

  it('clamps out-of-range progress without exceeding the track cap', () => {
    const beforeStart = missionTelemetryAt({
      progress: -1,
      elapsedMs: -1,
      status: 'running',
      startedAtMs,
    })
    const afterFinish = missionTelemetryAt({
      progress: 2,
      elapsedMs: missionDurationMs * 2,
      status: 'running',
      startedAtMs,
    })

    expect(beforeStart.track).toHaveLength(1)
    expect(beforeStart.position).toEqual(beforeStart.track[0])
    expect(afterFinish.track).toHaveLength(121)
    expect(afterFinish.position).toEqual(afterFinish.track.at(-1))
  })

  it('rejects invalid physical calibration', () => {
    const invalidSite = {
      ...kolamDeliSite,
      metersPerUnit: { x: 0, y: 0.1 },
    } satisfies MissionSite

    expect(() => coursePointToGeo({ x: 50, y: 50 }, invalidSite)).toThrow(
      /scale/i,
    )
  })
})
