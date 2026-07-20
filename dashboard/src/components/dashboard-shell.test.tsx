import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { DashboardShell } from './dashboard-shell'

import type { AsvLive, UnderwaterFrame } from '../lib/asv-types'

afterEach(cleanup)

const liveStatus = {
  id: 'default',
  online: true,
  model_status: 'running',
  camera: 'surface',
  stream_url: 'https://monitor-kapal-pora-pora.web.id/stream.mjpg',
  run_id: 'fixture-run-001',
  updated_at: '2026-07-20T09:30:00.000Z',
} satisfies AsvLive

const underwaterFrame = {
  mime: 'image/jpeg',
  data_base64: '/9j/4AAQSkZJRgABAQAAAQABAAD/2w==',
  captured_at: '2026-07-20T09:30:00.000Z',
  frame_id: 'fixture-underwater-001',
} satisfies UnderwaterFrame

describe('DashboardShell', () => {
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

    expect(screen.getByRole('img', { name: 'Live surface camera' })).toHaveAttribute(
      'src',
      'https://monitor-kapal-pora-pora.web.id/stream/atas',
    )
    expect(screen.getByRole('img', { name: 'Live underwater action camera' })).toHaveAttribute(
      'src',
      'https://monitor-kapal-pora-pora.web.id/stream/bawah',
    )
    expect(screen.queryByRole('img', { name: 'Latest underwater frame' })).not.toBeInTheDocument()
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

    expect(screen.getByRole('img', { name: 'Latest underwater frame' })).toHaveAttribute(
      'src',
      `data:image/jpeg;base64,${underwaterFrame.data_base64}`,
    )
  })

  it('renders a clear offline condition', () => {
    render(
      <DashboardShell
        asvId="default"
        live={{ ...liveStatus, online: false, model_status: 'offline' }}
        liveRealtimeStatus="error"
        underwaterFrame={null}
        underwaterRealtimeStatus="error"
        underwaterStreamUrl={null}
      />,
    )

    expect(screen.getByText('ASV offline')).toBeInTheDocument()
    expect(screen.getByText('No underwater frame received')).toBeInTheDocument()
  })
})
