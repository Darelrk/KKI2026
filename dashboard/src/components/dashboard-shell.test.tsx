import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { DashboardShell } from './dashboard-shell'

import type { AsvLive, UnderwaterFrame } from '../lib/asv-types'
import type { AsvTelemetry } from '../lib/asv-telemetry'

afterEach(cleanup)

const liveStatus = {
  id: 'default',
  online: true,
  model_status: 'running',
  camera: 'surface',
  stream_url: 'https://camera.example.test/raw-surface',
  run_id: 'fixture-run-001',
  updated_at: '2026-07-20T09:30:00.000Z',
} satisfies AsvLive

const underwaterFrame = {
  mime: 'image/jpeg',
  data_base64: '/9j/4AAQSkZJRgABAQAAAQABAAD/2w==',
  captured_at: '2026-07-20T09:30:00.000Z',
  frame_id: 'fixture-underwater-001',
} satisfies UnderwaterFrame

const telemetry = {
  connected: true,
  position: {
    latitude: -1.7,
    longitude: 102.25,
    captured_at: '2026-07-20T09:30:00.000Z',
  },
  heading_deg: 144,
  speed_mps: 0,
  captured_at: '2026-07-20T09:30:00.000Z',
  heartbeat_at: '2026-07-20T09:29:59.000Z',
  track: [
    {
      latitude: -1.7,
      longitude: 102.25,
      captured_at: '2026-07-20T09:30:00.000Z',
    },
  ],
} satisfies AsvTelemetry

describe('DashboardShell', () => {
  it('binds the on-site fixture to the Kolam Deli coordinate stream', () => {
    render(
      <DashboardShell
        asvId="default"
        mode="fixture"
        live={liveStatus}
        liveRealtimeStatus="fixture"
        telemetry={telemetry}
        telemetryRealtimeStatus="fixture"
        underwaterFrame={underwaterFrame}
        underwaterRealtimeStatus="fixture"
      />,
    )

    expect(
      screen.queryByRole('link', {
        name: 'Open Kolam Deli test location in Google Maps',
      }),
    ).not.toBeInTheDocument()
    expect(
      within(
        screen.getByRole('region', { name: 'Attitude telemetry' }),
      ).getByText(/^3\.\d{6}, 98\.\d{6}$/),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Test site: Kolam Deli · Lintasan A'),
    ).toBeInTheDocument()
  })

  it('runs the mission route preview while telemetry is still missing', () => {
    render(
      <DashboardShell
        asvId="default"
        live={liveStatus}
        liveRealtimeStatus="connecting"
        telemetry={null}
        telemetryRealtimeStatus="connecting"
        underwaterFrame={null}
        underwaterRealtimeStatus="connecting"
      />,
    )

    expect(screen.queryByText('Waiting for GPS fix.')).not.toBeInTheDocument()
    expect(screen.getByTestId('simulation-boat')).toBeInTheDocument()
  })

  it('shows the initial replay marker before mission start in direct mode', () => {
    render(
      <DashboardShell
        asvId="default"
        live={liveStatus}
        liveRealtimeStatus="connected"
        telemetry={telemetry}
        telemetryRealtimeStatus="connected"
        underwaterFrame={underwaterFrame}
        underwaterRealtimeStatus="connected"
      />,
    )

    expect(screen.getByTestId('simulation-boat')).toBeInTheDocument()
    expect(screen.queryByTestId('boat-marker')).not.toBeInTheDocument()
  })

  it('renders raw main and underwater camera streams instead of model output', () => {
    render(
      <DashboardShell
        asvId="default"
        live={liveStatus}
        liveRealtimeStatus="fixture"
        underwaterFrame={underwaterFrame}
        underwaterRealtimeStatus="fixture"
      />,
    )

    expect(
      screen.getByRole('img', { name: 'Live surface camera' }),
    ).toHaveAttribute(
      'src',
      'https://monitor-kapal-pora-pora.web.id/stream/atas',
    )
    expect(
      screen.getByRole('img', { name: 'Live underwater action camera' }),
    ).toHaveAttribute(
      'src',
      'https://monitor-kapal-pora-pora.web.id/stream/bawah',
    )
    expect(
      screen.queryByRole('img', { name: 'Latest underwater frame' }),
    ).not.toBeInTheDocument()
  })

  it('uses the Realtime underwater frame when no raw stream is configured', () => {
    render(
      <DashboardShell
        asvId="default"
        live={liveStatus}
        liveRealtimeStatus="fixture"
        underwaterFrame={underwaterFrame}
        underwaterRealtimeStatus="fixture"
        underwaterStreamUrl={null}
      />,
    )

    expect(
      screen.getByRole('img', { name: 'Latest underwater frame' }),
    ).toHaveAttribute(
      'src',
      `data:image/jpeg;base64,${underwaterFrame.data_base64}`,
    )
  })

  it('renders live Pixhawk telemetry and channel status', () => {
    render(
      <DashboardShell
        asvId="default"
        live={{ ...liveStatus, online: false, model_status: 'offline' }}
        liveRealtimeStatus="error"
        telemetry={telemetry}
        telemetryRealtimeStatus="connected"
        underwaterFrame={null}
        underwaterRealtimeStatus="connected"
      />,
    )

    expect(screen.getByText('GPS position')).toBeInTheDocument()
    expect(screen.getByText('-1.700000, 102.250000')).toBeInTheDocument()
    expect(screen.getByText('144.0°')).toBeInTheDocument()
    expect(screen.getByText('0.00 knot')).toBeInTheDocument()
    expect(screen.getByText('0.00 km/h')).toBeInTheDocument()
    expect(screen.getByText('TRIFUSION / ASV / default')).toBeInTheDocument()
    expect(screen.getByText('GPS track · 1 points')).toBeInTheDocument()
    expect(screen.getByText('Pixhawk connected')).toBeInTheDocument()
    expect(screen.getByText('Telemetry channel: connected')).toBeInTheDocument()
    expect(screen.queryByText('Telemetry unavailable')).not.toBeInTheDocument()
    expect(screen.getByText('ASV online')).toBeInTheDocument()
  })

  it('uses fallback heading and speed while Pixhawk telemetry is missing', () => {
    render(
      <DashboardShell
        asvId="default"
        live={null}
        liveRealtimeStatus="error"
        telemetry={null}
        telemetryRealtimeStatus="error"
        underwaterFrame={null}
        underwaterRealtimeStatus="error"
      />,
    )

    const telemetryRegion = screen.getByRole('region', {
      name: 'Attitude telemetry',
    })
    expect(telemetryRegion).not.toHaveTextContent('Unavailable')
    expect(telemetryRegion).toHaveTextContent(/\d+\.\d+°/)
    expect(telemetryRegion).toHaveTextContent(/\d+\.\d{2} knot/)
    expect(screen.getByText('ASV online')).toBeInTheDocument()
    expect(screen.queryByText('ASV offline')).not.toBeInTheDocument()
    expect(screen.queryByText('Realtime delayed')).not.toBeInTheDocument()
  })

  it('uses live Pixhawk telemetry when it becomes available', () => {
    render(
      <DashboardShell
        asvId="default"
        live={null}
        liveRealtimeStatus="error"
        telemetry={{ ...telemetry, heading_deg: 144, speed_mps: 1.2 }}
        telemetryRealtimeStatus="connected"
        underwaterFrame={null}
        underwaterRealtimeStatus="connected"
      />,
    )

    const telemetryRegion = screen.getByRole('region', {
      name: 'Attitude telemetry',
    })
    expect(telemetryRegion).toHaveTextContent('144.0°')
    expect(telemetryRegion).toHaveTextContent('2.33 knot')
    expect(screen.getByText('Pixhawk connected')).toBeInTheDocument()
    expect(screen.getByText('Telemetry channel: connected')).toBeInTheDocument()
  })

  it('hides disconnected Pixhawk status while telemetry is unavailable', () => {
    render(
      <DashboardShell
        asvId="default"
        live={liveStatus}
        liveRealtimeStatus="connected"
        telemetry={null}
        telemetryRealtimeStatus="error"
        underwaterFrame={null}
        underwaterRealtimeStatus="error"
      />,
    )

    expect(screen.queryByText('Telemetry unavailable')).not.toBeInTheDocument()
    expect(screen.queryByText('Pixhawk offline')).not.toBeInTheDocument()
    expect(screen.queryByText('Telemetry channel')).not.toBeInTheDocument()
  })

  it('uses fallback heading and speed while Pixhawk telemetry is missing', () => {
    render(
      <DashboardShell
        asvId="default"
        live={{ ...liveStatus, online: false, model_status: 'offline' }}
        liveRealtimeStatus="error"
        telemetry={null}
        telemetryRealtimeStatus="error"
        underwaterFrame={null}
        underwaterRealtimeStatus="error"
        underwaterStreamUrl={null}
      />,
    )

    expect(screen.getByText('ASV online')).toBeInTheDocument()
    expect(screen.queryByText('On-site test')).not.toBeInTheDocument()
    expect(screen.queryByText('Realtime delayed')).not.toBeInTheDocument()
    expect(screen.getByText('Underwater feed offline')).toBeInTheDocument()
  })
})
