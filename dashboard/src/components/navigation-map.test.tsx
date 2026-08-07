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
  it('hides the synthetic mission route while keeping course markers', () => {
    render(<NavigationMap telemetry={emptyNavigationTelemetry} />)

    expect(
      screen.getByRole('img', { name: 'ASV mission route' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: 'ASV mission route' }).querySelector(
        '.site-map__route',
      ),
    ).not.toBeInTheDocument()
    expect(screen.getByTestId('overlay-drag-layer')).toBeInTheDocument()
    expect(screen.getByTestId('surface-zone')).toBeInTheDocument()
    expect(screen.getByTestId('underwater-zone')).toBeInTheDocument()
    expect(screen.getAllByTestId('buoy-pair')).toHaveLength(10)
    expect(screen.getByText('Waiting for GPS fix.')).toBeInTheDocument()
    expect(screen.getByText('GPS position unavailable')).toBeInTheDocument()
    expect(screen.getByText('GPS track unavailable')).toBeInTheDocument()
  })

  it('shows the satellite map as the only map view', () => {
    render(<NavigationMap telemetry={emptyNavigationTelemetry} />)

    expect(screen.getByTitle('Kolam Deli satellite base map')).toHaveAttribute(
      'src',
      expect.stringContaining('maps.google.com/maps'),
    )
    expect(screen.getByRole('button', { name: 'Map' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(
      screen.queryByRole('button', { name: 'Course' }),
    ).not.toBeInTheDocument()
  })
  it('centers direct map on the latest GPS position', () => {
    render(
      <NavigationMap
        telemetry={{
          ...emptyNavigationTelemetry,
          position: {
            latitude: 3.4997,
            longitude: 98.7059,
            captured_at: '2026-08-07T09:55:31.000Z',
          },
        }}
      />,
    )

    const src =
      screen.getByTitle('Kolam Deli satellite base map').getAttribute('src') ?? ''
    expect(decodeURIComponent(src)).toContain('ll=3.4997,98.7059')
  })

  it('keeps the satellite map stable while the GPS cursor updates', () => {
    const { rerender } = render(
      <NavigationMap
        telemetry={{
          ...emptyNavigationTelemetry,
          position: {
            latitude: 3.4997,
            longitude: 98.7059,
            captured_at: '2026-08-07T09:55:31.000Z',
          },
          heading_deg: 90,
        }}
      />,
    )

    const iframe = screen.getByTitle('Kolam Deli satellite base map')
    const initialSrc = iframe.getAttribute('src')

    rerender(
      <NavigationMap
        telemetry={{
          ...emptyNavigationTelemetry,
          position: {
            latitude: 3.4998,
            longitude: 98.706,
            captured_at: '2026-08-07T09:55:32.000Z',
          },
          heading_deg: 180,
        }}
      />,
    )

    expect(
      screen.getByTitle('Kolam Deli satellite base map'),
    ).toHaveAttribute('src', initialSrc)
    expect(screen.getByTestId('boat-marker')).toHaveAttribute(
      'data-course-heading',
      '180',
    )
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
    expect(screen.queryByText('COURSE OVERLAY')).not.toBeInTheDocument()
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

  it('shows the moving replay overlay with live telemetry in direct mode', () => {
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

    expect(screen.getByTestId('simulation-track')).toBeInTheDocument()
    expect(screen.getByTestId('simulation-boat')).toHaveAttribute(
      'data-progress',
      '0.5',
    )
    expect(screen.getByText('Lintasan A · 50%')).toBeInTheDocument()
    expect(screen.queryByTestId('boat-marker')).not.toBeInTheDocument()
    expect(screen.queryByText('GPS track · 2 points')).not.toBeInTheDocument()
  })

  it('lets the operator drag the mission overlay onto the pool', () => {
    window.localStorage.clear()
    render(
      <NavigationMap
        telemetry={emptyNavigationTelemetry}
        simulation={simulation}
        previewMode
      />,
    )

    const layer = screen.getByTestId(
      'overlay-drag-layer',
    ) as unknown as SVGGElement
    Object.defineProperty(layer.ownerSVGElement!, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ width: 500, height: 500 }),
    })

    fireEvent.pointerDown(layer, { clientX: 200, clientY: 200 })
    fireEvent.pointerMove(layer, { clientX: 250, clientY: 180 })
    fireEvent.pointerUp(layer, { clientX: 250, clientY: 180 })

    expect(layer.getAttribute('transform')).toContain('translate(10 -4)')
  })

  it('lets the operator scale the mission overlay with the wheel', () => {
    window.localStorage.clear()
    render(
      <NavigationMap
        telemetry={emptyNavigationTelemetry}
        simulation={simulation}
        previewMode
      />,
    )

    const layer = screen.getByTestId('overlay-drag-layer')

    fireEvent.wheel(layer, { deltaY: -100 })
    expect(layer.getAttribute('transform')).toContain('scale(1.08)')

    fireEvent.wheel(layer, { deltaY: 100 })
    expect(layer.getAttribute('transform')).toContain('scale(1)')
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
      expect.stringContaining('z=22'),
    )
    expect(
      screen.queryByRole('link', {
        name: 'Open Kolam Deli in Google Maps',
      }),
    ).not.toBeInTheDocument()

    const mapButton = screen.getByRole('button', { name: 'Map' })
    expect(mapButton).toHaveAttribute('aria-pressed', 'true')
    expect(
      screen.queryByRole('button', { name: 'Course' }),
    ).not.toBeInTheDocument()
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

  it('keeps mission graphics visible with the map view', () => {
    render(<NavigationMap telemetry={emptyNavigationTelemetry} />)

    expect(screen.getByTestId('surface-zone')).toBeInTheDocument()
    expect(screen.getByTestId('underwater-zone')).toBeInTheDocument()
    expect(screen.getAllByTestId('buoy-pair')).toHaveLength(10)
    expect(screen.getByRole('button', { name: 'Map' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(
      screen.queryByRole('button', { name: 'Course' }),
    ).not.toBeInTheDocument()
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
    expect(screen.getByTestId('gps-track')).toBeInTheDocument()
    expect(screen.getByTestId('boat-marker')).toHaveAttribute(
      'data-course-heading',
      '90',
    )
    expect(screen.getByTestId('boat-marker')).toHaveAttribute(
      'transform',
      expect.stringContaining('rotate('),
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

    const polyline = screen.getByTestId('gps-track')

    expect(polyline.getAttribute('points')?.trim().split(/\s+/)).toHaveLength(3)
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
    expect(screen.queryByTestId('gps-track')).not.toBeInTheDocument()
  })
})
