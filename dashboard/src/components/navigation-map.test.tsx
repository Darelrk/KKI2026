import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { emptyNavigationTelemetry } from '../lib/navigation-types'
import { NavigationMap } from './navigation-map'

afterEach(cleanup)

describe('NavigationMap', () => {
  it('shows the GPS empty state without mission mockup markers', () => {
    render(<NavigationMap telemetry={emptyNavigationTelemetry} />)

    expect(screen.getByRole('heading', { name: 'Live boat track' })).toBeInTheDocument()
    expect(screen.getByText('Waiting for GPS fix.')).toBeInTheDocument()
    expect(screen.getByText('GPS position unavailable')).toBeInTheDocument()
    expect(screen.getByText('GPS track unavailable')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: 'GPS track plot' })).not.toBeInTheDocument()
    expect(screen.queryByText('MAP MOCKUP')).not.toBeInTheDocument()
    expect(screen.queryByText('Venue coordinates unavailable')).not.toBeInTheDocument()
    expect(screen.queryByText('START')).not.toBeInTheDocument()
    expect(screen.queryByText('Finish / docking')).not.toBeInTheDocument()
    expect(screen.queryByText('10 buoy pairs: red + green')).not.toBeInTheDocument()
    expect(screen.queryByText('Surface zone / green')).not.toBeInTheDocument()
    expect(screen.queryByText('Underwater zone / blue')).not.toBeInTheDocument()
    expect(screen.queryByText('3 docking balls / blue')).not.toBeInTheDocument()
  })

  it('plots GPS points and rotates the current boat marker by heading', () => {
    render(
      <NavigationMap
        telemetry={{
          ...emptyNavigationTelemetry,
          position: {
            latitude: -2,
            longitude: 101,
            captured_at: '2026-07-20T09:31:00.000Z',
          },
          heading_deg: 90,
          track: [
            { latitude: -1, longitude: 100, captured_at: '2026-07-20T09:30:00.000Z' },
            { latitude: -2, longitude: 101, captured_at: '2026-07-20T09:31:00.000Z' },
          ],
        }}
      />,
    )

    expect(screen.getByText('GPS track · 2 points')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'GPS track plot' })).toBeInTheDocument()
    expect(screen.getByTestId('boat-marker')).toHaveAttribute(
      'transform',
      expect.stringContaining('rotate(90'),
    )
  })

  it('connects the current position to the end of the GPS path', () => {
    render(
      <NavigationMap
        telemetry={{
          ...emptyNavigationTelemetry,
          position: {
            latitude: -2,
            longitude: 102,
            captured_at: '2026-07-20T09:32:00.000Z',
          },
          track: [
            { latitude: -1, longitude: 100, captured_at: '2026-07-20T09:30:00.000Z' },
            { latitude: -2, longitude: 101, captured_at: '2026-07-20T09:31:00.000Z' },
          ],
        }}
      />,
    )

    const polyline = screen
      .getByRole('img', { name: 'GPS track plot' })
      .querySelector('polyline')

    expect(polyline).not.toBeNull()
    expect(polyline?.getAttribute('points')?.trim().split(/\s+/)).toHaveLength(3)
  })

  it('renders one current position without inventing a path', () => {
    render(
      <NavigationMap
        telemetry={{
          ...emptyNavigationTelemetry,
          position: {
            latitude: -1,
            longitude: 100,
            captured_at: '2026-07-20T09:30:00.000Z',
          },
          track: [
            { latitude: -1, longitude: 100, captured_at: '2026-07-20T09:30:00.000Z' },
          ],
        }}
      />,
    )

    expect(screen.getByTestId('boat-marker')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: 'GPS track plot' })).not.toBeInTheDocument()
  })
})
