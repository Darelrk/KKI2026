import { describe, expect, it } from 'vitest'

import { kolamDeliSite } from './mission-site'
import {
  buildGoogleMapsSatelliteEmbedUrl,
  coursePointToLintasanOverlay,
  lintasanOverlayShiftForMapCenter,
} from './site-map-projection'

describe('Lintasan SVG overlay frame', () => {
  it('maps course coordinates to the supplied SVG frame', () => {
    const projected = coursePointToLintasanOverlay({
      x: (421 + 30) / 5.5,
      y: (390 + 104) / 5.5,
    })

    expect(projected.x).toBeCloseTo((421 / 464) * 100, 5)
    expect(projected.y).toBeCloseTo((390 / 425) * 100, 5)
  })

  it('keeps the overlay aligned when the live map center recenters', () => {
    expect(lintasanOverlayShiftForMapCenter(kolamDeliSite.center)).toEqual({
      x: 0,
      y: 0,
    })

    const eastOfSite = {
      ...kolamDeliSite.center,
      longitude: kolamDeliSite.center.longitude + 0.00001,
    }
    const shift = lintasanOverlayShiftForMapCenter(eastOfSite)

    expect(shift.x).toBeLessThan(0)
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
