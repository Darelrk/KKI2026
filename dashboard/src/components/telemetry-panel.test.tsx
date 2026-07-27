import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { emptyNavigationTelemetry } from '../lib/navigation-types'
import { TelemetryPanel } from './telemetry-panel'

afterEach(cleanup)

describe('TelemetryPanel', () => {
  it('shows unavailable values when navigation telemetry is missing', () => {
    render(
      <TelemetryPanel telemetry={emptyNavigationTelemetry} updatedAt={null} />,
    )

    expect(screen.getByText('GPS position')).toBeInTheDocument()
    expect(screen.getByText('Heading')).toBeInTheDocument()
    expect(screen.getByText('SOG')).toBeInTheDocument()
    expect(screen.getByText('Last update')).toBeInTheDocument()
    expect(screen.getAllByText('Unavailable')).toHaveLength(4)
  })

  it('shows SOG in knots and kilometres per hour', () => {
    render(
      <TelemetryPanel
        telemetry={{ ...emptyNavigationTelemetry, speed_mps: 1.2 }}
        updatedAt={null}
      />,
    )

    expect(screen.getByText('SOG')).toBeInTheDocument()
    expect(screen.getByText('2.33 knot')).toBeInTheDocument()
    expect(screen.getByText('4.32 km/h')).toBeInTheDocument()
  })
})
