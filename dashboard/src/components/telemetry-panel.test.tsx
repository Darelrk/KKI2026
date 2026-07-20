import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { emptyNavigationTelemetry } from '../lib/navigation-types'
import { TelemetryPanel } from './telemetry-panel'

describe('TelemetryPanel', () => {
  it('shows unavailable values when navigation telemetry is missing', () => {
    render(<TelemetryPanel telemetry={emptyNavigationTelemetry} updatedAt={null} />)

    expect(screen.getByText('GPS position')).toBeInTheDocument()
    expect(screen.getByText('Heading')).toBeInTheDocument()
    expect(screen.getByText('Speed')).toBeInTheDocument()
    expect(screen.getByText('Last update')).toBeInTheDocument()
    expect(screen.getAllByText('Unavailable')).toHaveLength(4)
  })
})
