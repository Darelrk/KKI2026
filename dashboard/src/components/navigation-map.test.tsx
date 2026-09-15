import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { emptyNavigationTelemetry } from '../lib/navigation-types'
import { missionRoutePosition } from '../lib/mission-simulation'
import type { MissionSimulationController } from '../lib/use-mission-simulation'
import { NavigationMap } from './navigation-map'

afterEach(() => {
  cleanup()
  window.localStorage.removeItem('kki2026.site-overlay-nudge')
})

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
  it('renders the supplied SVG as the only custom map graphic', () => {
    render(<NavigationMap telemetry={emptyNavigationTelemetry} />)

    const image = screen.getByTestId('course-svg-overlay')
    expect(image).toHaveAttribute('href', '/lintasan-transparan.svg')

    const svg = image.closest('svg')
    expect(svg).not.toBeNull()
    expect(svg?.querySelectorAll('image')).toHaveLength(1)
    expect(svg?.querySelectorAll('polyline,path,circle')).toHaveLength(0)
    expect(screen.queryByTestId('boat-marker')).not.toBeInTheDocument()
    expect(screen.queryByTestId('simulation-boat')).not.toBeInTheDocument()
    expect(screen.queryByTestId('simulation-track')).not.toBeInTheDocument()
    expect(screen.getByText('GPS position unavailable')).toBeInTheDocument()
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

  it('centers the direct map on the latest GPS position', () => {
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
      screen.getByTitle('Kolam Deli satellite base map').getAttribute('src') ??
      ''
    expect(decodeURIComponent(src)).toContain('ll=3.4997,98.7059')
  })

  it('keeps the satellite map stable while GPS data updates', () => {
    const { rerender } = render(
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
        }}
      />,
    )

    expect(screen.getByTitle('Kolam Deli satellite base map')).toHaveAttribute(
      'src',
      initialSrc,
    )
    expect(screen.queryByTestId('boat-marker')).not.toBeInTheDocument()
    expect(screen.queryByTestId('simulation-track')).not.toBeInTheDocument()
  })

  it('keeps fixture telemetry readout without drawing a vessel or route', () => {
    render(
      <NavigationMap
        telemetry={emptyNavigationTelemetry}
        simulation={simulation}
      />,
    )

    expect(screen.getByTestId('course-svg-overlay')).toBeInTheDocument()
    expect(screen.queryByTestId('simulation-boat')).not.toBeInTheDocument()
    expect(screen.queryByTestId('simulation-track')).not.toBeInTheDocument()
    expect(screen.getByText('Lintasan A · 50%')).toBeInTheDocument()
    expect(
      screen.getByText('ASV navigation · mission active'),
    ).toBeInTheDocument()
  })

  it('lets the operator drag the SVG overlay', () => {
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

  it('lets the operator scale the SVG overlay', () => {
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

  it('refreshes the satellite map without changing its live GPS center', () => {
    const firstTelemetry = {
      ...emptyNavigationTelemetry,
      position: {
        latitude: 3.4995,
        longitude: 98.7058,
        captured_at: '2026-07-20T09:30:00.000Z',
      },
    }
    const latestTelemetry = {
      ...firstTelemetry,
      position: {
        latitude: 3.5012,
        longitude: 98.7074,
        captured_at: '2026-07-20T09:31:00.000Z',
      },
    }
    const { rerender } = render(<NavigationMap telemetry={firstTelemetry} />)
    const firstMap = screen.getByTitle('Kolam Deli satellite base map')
    const firstMapSrc = firstMap.getAttribute('src')

    rerender(<NavigationMap telemetry={latestTelemetry} />)
    expect(screen.getByTitle('Kolam Deli satellite base map')).toHaveAttribute(
      'src',
      firstMapSrc,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Refresh map' }))

    const refreshedMap = screen.getByTitle('Kolam Deli satellite base map')
    expect(refreshedMap).not.toBe(firstMap)
    expect(refreshedMap).toHaveAttribute('src', firstMapSrc)
    expect(screen.getByText('GPS position available')).toBeInTheDocument()
  })

  it('reports GPS track data without drawing custom route graphics', () => {
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
      />,
    )

    expect(screen.getByText('GPS track · 2 points')).toBeInTheDocument()
    expect(screen.queryByTestId('gps-track')).not.toBeInTheDocument()
    expect(screen.queryByTestId('boat-marker')).not.toBeInTheDocument()
    expect(screen.queryByTestId('simulation-track')).not.toBeInTheDocument()
  })
})
