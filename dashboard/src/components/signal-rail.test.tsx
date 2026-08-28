import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { SignalRail } from './signal-rail'

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
  it('identifies model monitoring and the current manual control mode', () => {
    const onControlModeChange = vi.fn()
    render(
      <SignalRail
        live={live}
        telemetryConnected={true}
        telemetryStatus="connected"
        controlMode="MANUAL"
        controlModeCanEdit
        controlModeUpdating={false}
        controlModeError={null}
        onControlModeChange={onControlModeChange}
      />,
    )

    expect(screen.getByText('MODEL MONITORING')).toBeInTheDocument()
    expect(screen.getByText('MODEL RUNNING')).toBeInTheDocument()
    expect(screen.getByText('Autonomy target')).toBeInTheDocument()
    expect(screen.getByText('MANUAL', { selector: 'dd' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'MANUAL' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(
      screen.getByRole('button', { name: 'AUTONOMOUS' }),
    ).toHaveAttribute('aria-pressed', 'false')
    expect(screen.queryByText('AUTO / ONBOARD')).not.toBeInTheDocument()
    expect(screen.queryByText(/RC MANUAL|MAVLink/i)).not.toBeInTheDocument()
  })
})
