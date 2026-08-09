import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from '@testing-library/react'
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
        mode="fixture"
        live={liveStatus}
        telemetry={telemetry}
        telemetryRealtimeStatus="fixture"
        underwaterFrame={underwaterFrame}
      />,
    )

    expect(
      screen.queryByRole('link', {
        name: 'Open Kolam Deli test location in Google Maps',
      }),
    ).not.toBeInTheDocument()
    expect(screen.getByTestId('simulation-boat')).toBeInTheDocument()
    expect(
      document.querySelector('.dashboard-shell__footer'),
    ).not.toBeInTheDocument()
  })

  it('shows the GPS waiting state while telemetry is missing in direct mode', () => {
    render(
      <DashboardShell
        live={liveStatus}
        telemetry={null}
        telemetryRealtimeStatus="connecting"
        underwaterFrame={null}
      />,
    )

    expect(screen.getByText('Waiting for GPS fix.')).toBeInTheDocument()
    expect(screen.queryByTestId('simulation-boat')).not.toBeInTheDocument()
  })

  it('shows the live GPS boat marker in direct mode', () => {
    render(
      <DashboardShell
        live={liveStatus}
        telemetry={telemetry}
        telemetryRealtimeStatus="connected"
        underwaterFrame={underwaterFrame}
      />,
    )

    expect(screen.getByTestId('boat-marker')).toBeInTheDocument()
    expect(screen.queryByTestId('simulation-boat')).not.toBeInTheDocument()
  })

  it('keeps mission controls in direct mode without replacing live GPS', () => {
    render(
      <DashboardShell
        live={liveStatus}
        telemetry={telemetry}
        telemetryRealtimeStatus="connected"
        underwaterFrame={underwaterFrame}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Start mission' }))

    expect(screen.getAllByText('Mission route active')).toHaveLength(2)
    expect(screen.getByTestId('boat-marker')).toBeInTheDocument()
    expect(screen.queryByTestId('simulation-boat')).not.toBeInTheDocument()
  })

  it('renders raw main and underwater camera streams instead of model output', () => {
    render(
      <DashboardShell
        live={liveStatus}
        underwaterFrame={underwaterFrame}
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
        live={liveStatus}
        underwaterFrame={underwaterFrame}
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
        live={{ ...liveStatus, online: false, model_status: 'offline' }}
        telemetry={telemetry}
        telemetryRealtimeStatus="connected"
        underwaterFrame={null}
      />,
    )

    expect(screen.queryByText('GPS position')).not.toBeInTheDocument()
    expect(screen.getByTestId('boat-marker')).toBeInTheDocument()
    expect(screen.getByText('COG')).toBeInTheDocument()
    expect(screen.queryByText('Heading')).not.toBeInTheDocument()
    expect(screen.getByText('144.0°')).toBeInTheDocument()
    expect(screen.getByText('0.00 knot')).toBeInTheDocument()
    expect(screen.getByText('0.00 km/h')).toBeInTheDocument()
    const teamLogo = screen.getByRole('img', { name: 'TRIFUSION' })
    expect(teamLogo).toHaveAttribute('src', '/trifusion.svg')
    const teamIdentity = teamLogo.closest('.connection-bar__identity')
    expect(teamIdentity).not.toHaveTextContent('TRIFUSION')
    expect(teamIdentity?.querySelector('svg')).not.toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: 'Diktisaintek Berdampak' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: 'Direktorat Jenderal Pendidikan Tinggi' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('img', {
        name: 'Universitas Muhammadiyah Sumatera Utara',
      }),
    ).toBeInTheDocument()
    expect(
      within(screen.getByLabelText('Institution partners'))
        .getAllByRole('img')
        .map((logo) => logo.getAttribute('alt')),
    ).toEqual([
      'Direktorat Jenderal Pendidikan Tinggi',
      'Diktisaintek Berdampak',
      'Universitas Muhammadiyah Sumatera Utara',
    ])
    expect(screen.getByText('GPS track · 1 points')).toBeInTheDocument()
    expect(screen.getByText('Pixhawk connected')).toBeInTheDocument()
    expect(screen.queryByText('Telemetry unavailable')).not.toBeInTheDocument()
    expect(screen.getByText('ASV online')).toBeInTheDocument()
  })

  it('shows unavailable telemetry and offline status while Pixhawk is missing', () => {
    render(
      <DashboardShell
        live={null}
        telemetry={null}
        telemetryRealtimeStatus="error"
        underwaterFrame={null}
      />,
    )

    const telemetryRegion = screen.getByRole('region', {
      name: 'Attitude telemetry',
    })
    expect(telemetryRegion).toHaveTextContent('Unavailable')
    expect(screen.getByText('ASV offline')).toBeInTheDocument()
    expect(screen.queryByText('ASV online')).not.toBeInTheDocument()
    expect(screen.getByText('Realtime delayed')).toBeInTheDocument()
  })

  it('uses live Pixhawk telemetry when it becomes available', () => {
    render(
      <DashboardShell
        live={null}
        telemetry={{ ...telemetry, heading_deg: 144, speed_mps: 1.2 }}
        telemetryRealtimeStatus="connected"
        underwaterFrame={null}
      />,
    )

    const telemetryRegion = screen.getByRole('region', {
      name: 'Attitude telemetry',
    })
    expect(telemetryRegion).toHaveTextContent('144.0°')
    expect(telemetryRegion).toHaveTextContent('2.33 knot')
    expect(screen.getByText('Pixhawk connected')).toBeInTheDocument()
  })

  it('hides disconnected Pixhawk status while telemetry is unavailable', () => {
    render(
      <DashboardShell
        live={liveStatus}
        telemetry={null}
        telemetryRealtimeStatus="error"
        underwaterFrame={null}
      />,
    )

    expect(screen.queryByText('Telemetry unavailable')).not.toBeInTheDocument()
    expect(screen.queryByText('Pixhawk offline')).not.toBeInTheDocument()
    expect(screen.queryByText('Telemetry channel')).not.toBeInTheDocument()
  })

  it('reports offline status and underwater feed state without telemetry', () => {
    render(
      <DashboardShell
        live={{ ...liveStatus, online: false, model_status: 'offline' }}
        telemetry={null}
        telemetryRealtimeStatus="error"
        underwaterFrame={null}
        underwaterStreamUrl={null}
      />,
    )

    expect(screen.getByText('ASV offline')).toBeInTheDocument()
    expect(screen.queryByText('On-site test')).not.toBeInTheDocument()
    expect(screen.getByText('Realtime delayed')).toBeInTheDocument()
    expect(screen.getByText('Underwater feed offline')).toBeInTheDocument()
  })
})
