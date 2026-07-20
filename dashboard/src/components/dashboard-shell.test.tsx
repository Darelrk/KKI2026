import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { DashboardShell } from './dashboard-shell'

import type { AsvLive, UnderwaterFrame } from '../lib/asv-types'

const liveStatus = {
  id: 'default',
  online: true,
  model_status: 'running',
  camera: 'surface',
  stream_url: null,
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
  it('renders the fixture operational view with a surface placeholder', () => {
    render(
      <DashboardShell
        asvId="default"
        live={liveStatus}
        liveRealtimeStatus="fixture"
        underwaterFrame={underwaterFrame}
        underwaterRealtimeStatus="fixture"
      />,
    )

    expect(screen.getByText('ASV / default')).toBeInTheDocument()
    expect(screen.getByText('MODEL RUNNING')).toBeInTheDocument()
    expect(screen.getByText('Fixture data')).toBeInTheDocument()
    expect(screen.getByText('Surface stream unavailable')).toBeInTheDocument()
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
      />,
    )

    expect(screen.getByText('ASV offline')).toBeInTheDocument()
    expect(screen.getByText('No underwater frame received')).toBeInTheDocument()
  })
})
