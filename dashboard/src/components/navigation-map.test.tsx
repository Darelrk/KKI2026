import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { emptyNavigationTelemetry } from '../lib/navigation-types'
import { missionRoutePosition } from '../lib/mission-simulation'
import type { MissionSimulationController } from '../lib/use-mission-simulation'
import { NavigationMap } from './navigation-map'

afterEach(cleanup)

const simulation = {
  status: 'running',
  elapsedMs: 15_000,
  progress: 0.5,
  stageIndex: 3,
  position: missionRoutePosition(0.5),
  start: () => undefined,
  pause: () => undefined,
  stop: () => undefined,
  reset: () => undefined,
  selectStage: () => undefined,
} as MissionSimulationController

describe('NavigationMap', () => {
  it('keeps the official mission route visible while GPS is unavailable', () => {
    render(<NavigationMap telemetry={emptyNavigationTelemetry} />)

    expect(screen.getByRole('heading', { name: 'Mission route' })).toBeInTheDocument()
    expect(screen.getByText('Waiting for GPS fix.')).toBeInTheDocument()
    expect(screen.getByText('GPS position unavailable')).toBeInTheDocument()
    expect(screen.getByText('GPS track unavailable')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Mission route plan' })).toBeInTheDocument()
    expect(screen.getAllByTestId('buoy-pair')).toHaveLength(10)
    expect(screen.queryByRole('complementary', { name: 'Mission route legend' })).not.toBeInTheDocument()
    expect(screen.queryByText('Course layout')).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('shows the local replay boat on the simulation route', () => {
    render(<NavigationMap telemetry={emptyNavigationTelemetry} simulation={simulation} />)

    expect(screen.getByRole('img', { name: 'Simulation route replay' })).toBeInTheDocument()
    expect(screen.getByTestId('simulation-boat')).toHaveAttribute('data-progress', '0.5')
    expect(screen.getByText('Simulation route · 50%')).toBeInTheDocument()
  })

  it('keeps mission graphics visible without course layout options', () => {
    render(<NavigationMap telemetry={emptyNavigationTelemetry} />)

    expect(screen.getByTestId('surface-zone')).toBeInTheDocument()
    expect(screen.getByTestId('underwater-zone')).toBeInTheDocument()
    expect(screen.getAllByTestId('buoy-pair')).toHaveLength(10)
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
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
