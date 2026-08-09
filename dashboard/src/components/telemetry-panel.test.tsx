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

    expect(screen.queryByText('GPS position')).not.toBeInTheDocument()
    expect(screen.getByText('COG')).toBeInTheDocument()
    expect(screen.getByText('SOG')).toBeInTheDocument()
    expect(screen.getByText('Last update')).toBeInTheDocument()
    expect(screen.getAllByText('Unavailable')).toHaveLength(3)
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

  it('marks COG and SOG as priority telemetry', () => {
    render(
      <TelemetryPanel
        telemetry={{
          ...emptyNavigationTelemetry,
          heading_deg: 144,
          speed_mps: 1.2,
        }}
        updatedAt={null}
      />,
    )

    const cogCard = screen.getByText('COG').closest('.telemetry-card')
    const sogCard = screen.getByText('SOG').closest('.telemetry-card')
    expect(cogCard).toHaveClass(
      'telemetry-card--priority',
      'telemetry-card--wide',
    )
    expect(sogCard).toHaveClass(
      'telemetry-card--priority',
      'telemetry-card--wide',
    )
    expect(cogCard?.compareDocumentPosition(sogCard as Node)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
  })
})
