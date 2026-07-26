import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { emptyNavigationTelemetry } from '../lib/navigation-types'
import { missionRoute, missionRoutePosition } from '../lib/mission-simulation'
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

    expect(
      screen.getByRole('heading', { name: 'Mission route' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Waiting for GPS fix.')).toBeInTheDocument()
    expect(screen.getByText('GPS position unavailable')).toBeInTheDocument()
    expect(screen.getByText('GPS track unavailable')).toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: 'Mission route plan' }),
    ).toBeInTheDocument()
    expect(screen.getAllByTestId('buoy-pair')).toHaveLength(10)
    expect(
      screen.queryByRole('complementary', { name: 'Mission route legend' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByText('Course layout')).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('shows the local replay boat on the simulation route', () => {
    render(
      <NavigationMap
        telemetry={emptyNavigationTelemetry}
        simulation={simulation}
      />,
    )

    expect(
      screen.getByRole('img', { name: 'ASV mission route' }),
    ).toBeInTheDocument()
    expect(screen.getByTestId('simulation-boat')).toHaveAttribute(
      'data-progress',
      '0.5',
    )
    expect(screen.getByTestId('simulation-boat')).toHaveAttribute(
      'data-heading',
    )
    expect(screen.getByTestId('simulation-boat')).toHaveAttribute(
      'transform',
      expect.stringContaining('rotate('),
    )
    const travelledPoints = screen
      .getByTestId('simulation-track')
      .getAttribute('points')
      ?.trim()
      .split(/\s+/)
    expect(travelledPoints?.length).toBeGreaterThan(2)
    expect(travelledPoints?.length).toBeLessThan(missionRoute.length)
    expect(screen.getByText('Lintasan A · 50%')).toBeInTheDocument()
    expect(
      screen.getByText('ASV navigation · mission active'),
    ).toBeInTheDocument()
  })

  it('keeps a fixture reset on the mission route instead of jumping to GPS track', () => {
    const idleSimulation = {
      ...simulation,
      status: 'idle',
      elapsedMs: 0,
      progress: 0,
      position: missionRoutePosition(0),
    } as MissionSimulationController

    render(
      <NavigationMap
        telemetry={{
          ...emptyNavigationTelemetry,
          position: {
            latitude: -2,
            longitude: 101,
            captured_at: '2026-07-20T09:31:00.000Z',
          },
          track: [
            {
              latitude: -1,
              longitude: 100,
              captured_at: '2026-07-20T09:30:00.000Z',
            },
            {
              latitude: -2,
              longitude: 101,
              captured_at: '2026-07-20T09:31:00.000Z',
            },
          ],
        }}
        simulation={idleSimulation}
        previewMode
      />,
    )

    expect(
      screen.getByRole('img', { name: 'ASV mission route' }),
    ).toBeInTheDocument()
    expect(screen.getByTestId('simulation-boat')).toHaveAttribute(
      'data-progress',
      '0',
    )
    expect(screen.queryByText('GPS track · 2 points')).not.toBeInTheDocument()
  })

  it('keeps the real GPS track visible when a replay runs outside preview mode', () => {
    render(
      <NavigationMap
        telemetry={{
          ...emptyNavigationTelemetry,
          position: {
            latitude: -2,
            longitude: 101,
            captured_at: '2026-07-26T09:31:00.000Z',
          },
          heading_deg: 90,
          track: [
            {
              latitude: -1,
              longitude: 100,
              captured_at: '2026-07-26T09:30:00.000Z',
            },
            {
              latitude: -2,
              longitude: 101,
              captured_at: '2026-07-26T09:31:00.000Z',
            },
          ],
        }}
        simulation={simulation}
      />,
    )

    expect(
      screen.getByRole('img', { name: 'GPS track plot' }),
    ).toBeInTheDocument()
    expect(screen.getByTestId('boat-marker')).toBeInTheDocument()
    expect(screen.getByText('GPS track · 2 points')).toBeInTheDocument()
    expect(screen.queryByTestId('simulation-boat')).not.toBeInTheDocument()
  })

  it('shows the Kolam Deli site context for the on-site fixture', () => {
    render(
      <NavigationMap
        telemetry={emptyNavigationTelemetry}
        simulation={{
          ...simulation,
          status: 'idle',
          elapsedMs: 0,
          progress: 0,
          position: missionRoutePosition(0),
        }}
        previewMode
      />,
    )

    expect(screen.queryByTestId('site-context')).not.toBeInTheDocument()
    expect(screen.getByTitle('Kolam Deli satellite base map')).toHaveAttribute(
      'src',
      expect.stringContaining('maps.google.com/maps'),
    )
    expect(screen.getByTitle('Kolam Deli satellite base map')).toHaveAttribute(
      'src',
      expect.stringContaining('t=k'),
    )
    expect(screen.getByTitle('Kolam Deli satellite base map')).toHaveAttribute(
      'src',
      expect.stringContaining('z=21'),
    )
    expect(
      screen.queryByRole('link', {
        name: 'Open Kolam Deli in Google Maps',
      }),
    ).not.toBeInTheDocument()

    const mapButton = screen.getByRole('button', { name: 'Map' })
    const courseButton = screen.getByRole('button', { name: 'Course' })
    expect(mapButton).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(courseButton)

    expect(courseButton).toHaveAttribute('aria-pressed', 'true')
    expect(
      screen.queryByTitle('Kolam Deli satellite base map'),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: 'ASV mission route' }),
    ).toBeInTheDocument()
  })

  it('keeps the boat visible at the dock after mission completion', () => {
    const completeSimulation = {
      ...simulation,
      status: 'complete',
      elapsedMs: 30_000,
      progress: 1,
      position: missionRoutePosition(1),
    } as MissionSimulationController

    render(
      <NavigationMap
        telemetry={emptyNavigationTelemetry}
        simulation={completeSimulation}
      />,
    )

    expect(screen.getByTestId('simulation-boat')).toHaveAttribute(
      'data-status',
      'complete',
    )
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
            {
              latitude: -1,
              longitude: 100,
              captured_at: '2026-07-20T09:30:00.000Z',
            },
            {
              latitude: -2,
              longitude: 101,
              captured_at: '2026-07-20T09:31:00.000Z',
            },
          ],
        }}
      />,
    )

    expect(screen.getByText('GPS track · 2 points')).toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: 'GPS track plot' }),
    ).toBeInTheDocument()
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
            {
              latitude: -1,
              longitude: 100,
              captured_at: '2026-07-20T09:30:00.000Z',
            },
            {
              latitude: -2,
              longitude: 101,
              captured_at: '2026-07-20T09:31:00.000Z',
            },
          ],
        }}
      />,
    )

    const polyline = screen
      .getByRole('img', { name: 'GPS track plot' })
      .querySelector('polyline.navigation-map__track')

    expect(polyline).not.toBeNull()
    expect(polyline?.getAttribute('points')?.trim().split(/\s+/)).toHaveLength(
      3,
    )
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
            {
              latitude: -1,
              longitude: 100,
              captured_at: '2026-07-20T09:30:00.000Z',
            },
          ],
        }}
      />,
    )

    expect(screen.getByTestId('boat-marker')).toBeInTheDocument()
    expect(
      screen.queryByRole('img', { name: 'GPS track plot' }),
    ).not.toBeInTheDocument()
  })
})
