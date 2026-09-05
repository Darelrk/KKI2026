import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { SignalRail } from './signal-rail'

afterEach(cleanup)

const live = {
  id: 'default',
  online: true,
  model_status: 'running' as const,
  camera: 'surface' as const,
  stream_url: null,
  run_id: 'run-1',
  updated_at: '2026-07-23T10:00:00.000Z',
}

describe('SignalRail', () => {
  it('identifies model monitoring and the fixed manual control mode', () => {
    render(
      <SignalRail
        live={live}
        telemetryConnected={true}
        telemetryStatus="connected"
      />,
    )

    expect(screen.getByText('MODEL MONITORING')).toBeInTheDocument()
    expect(screen.getByText('MODEL RUNNING')).toBeInTheDocument()
    expect(screen.getByText('Control mode')).toBeInTheDocument()
    expect(screen.getByText('MANUAL', { selector: 'dd' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'MANUAL' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'AUTONOMOUS' })).not.toBeInTheDocument()
    expect(screen.queryByText('AUTO / ONBOARD')).not.toBeInTheDocument()
    expect(screen.queryByText(/RC MANUAL|MAVLink/i)).not.toBeInTheDocument()
  })
})
