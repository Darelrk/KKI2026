import { describe, expect, it } from 'vitest'

import { missionRoute } from './mission-simulation'
import { kolamDeliSite } from './mission-site'
import {
  buildGoogleMapsSatelliteEmbedUrl,
  courseHeadingToSiteOverlay,
  coursePointToSiteOverlay,
  kolamDeliOverlayCalibration,
} from './site-map-projection'


describe('Kolam Deli course overlay calibration', () => {
  it('anchors both mission endpoints at the supplied site pin', () => {
    const anchor = kolamDeliOverlayCalibration.mapAnchor

    expect(coursePointToSiteOverlay(missionRoute[0])).toEqual(anchor)
    expect(coursePointToSiteOverlay(missionRoute.at(-1)!)).toEqual(anchor)
  })

  it('mirrors the course vertically into the pool', () => {
    const anchor = kolamDeliOverlayCalibration.mapAnchor
    const pointBelowDockInCourse = {
      x: kolamDeliOverlayCalibration.courseAnchor.x,
      y: kolamDeliOverlayCalibration.courseAnchor.y + 10,
    }
    const projected = coursePointToSiteOverlay(pointBelowDockInCourse)

    expect(projected.y).toBeLessThan(anchor.y)
  })

  it('keeps the calibrated route inside the supplied pool crop', () => {
    const projected = missionRoute.map((point) =>
      coursePointToSiteOverlay(point),
    )
    const xValues = projected.map((point) => point.x)
    const yValues = projected.map((point) => point.y)

    expect(Math.min(...xValues)).toBeGreaterThan(39)
    expect(Math.max(...xValues)).toBeLessThan(57)
    expect(Math.min(...yValues)).toBeGreaterThan(46)
    expect(Math.max(...yValues)).toBeLessThan(74)
  })

  it('transforms headings from the mirrored geometry instead of reusing raw degrees', () => {
    const transformedNorth = courseHeadingToSiteOverlay(0)
    const transformedSouth = courseHeadingToSiteOverlay(180)

    expect(transformedNorth).not.toBeCloseTo(0, 3)
    expect(Math.abs(transformedNorth - transformedSouth)).toBeCloseTo(180, 5)
  })
})

describe('Google Maps satellite embed URL', () => {
  it('centers on Kolam Deli without dropping a marker pin', () => {
    const url = new URL(buildGoogleMapsSatelliteEmbedUrl())

    expect(url.origin).toBe('https://maps.google.com')
    expect(url.pathname).toBe('/maps')
    expect(url.searchParams.get('ll')).toBe(
      `${kolamDeliSite.center.latitude},${kolamDeliSite.center.longitude}`,
    )
    expect(url.searchParams.get('q')).toBeNull()
    expect(url.searchParams.get('z')).toBe('21')
    expect(url.searchParams.get('t')).toBe('k')
    expect(url.searchParams.get('output')).toBe('embed')
  })
})
