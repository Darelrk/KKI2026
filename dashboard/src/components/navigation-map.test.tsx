import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { emptyNavigationTelemetry } from '../lib/navigation-types'
import { NavigationMap } from './navigation-map'

describe('NavigationMap', () => {
  it('shows the formal map placeholder and required mission markers', () => {
    render(<NavigationMap telemetry={emptyNavigationTelemetry} />)

    expect(screen.getByRole('heading', { name: 'Navigation map' })).toBeInTheDocument()
    expect(screen.getByText('MAP MOCKUP')).toBeInTheDocument()
    expect(screen.getByText('Venue coordinates unavailable')).toBeInTheDocument()
    expect(screen.getByText('GPS track unavailable')).toBeInTheDocument()
    expect(screen.getByText('START')).toBeInTheDocument()
    expect(screen.getByText('Finish / docking')).toBeInTheDocument()
    expect(screen.getByText('10 buoy pairs: red + green')).toBeInTheDocument()
    expect(screen.getByText('Surface zone / green')).toBeInTheDocument()
    expect(screen.getByText('Underwater zone / blue')).toBeInTheDocument()
    expect(screen.getByText('3 docking balls / blue')).toBeInTheDocument()
  })

  it('plots only the GPS points provided by telemetry', () => {
    render(
      <NavigationMap
        telemetry={{
          ...emptyNavigationTelemetry,
          track: [
            { latitude: -1, longitude: 100, captured_at: '2026-07-20T09:30:00.000Z' },
            { latitude: -2, longitude: 101, captured_at: '2026-07-20T09:31:00.000Z' },
          ],
        }}
      />,
    )

    expect(screen.getByText('GPS track · 2 points')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'GPS track plot' })).toBeInTheDocument()
  })
})
