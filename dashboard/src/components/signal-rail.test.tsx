import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

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
  it('identifies model monitoring and autonomous onboard control', () => {
    render(
      <SignalRail
        live={live}
        telemetryConnected={true}
        telemetryStatus="connected"
      />,
    )

    expect(screen.getByText('MODEL MONITORING')).toBeInTheDocument()
    expect(screen.getByText('MODEL RUNNING')).toBeInTheDocument()
    expect(screen.getByText('Autonomy target')).toBeInTheDocument()
    expect(screen.getByText('AUTO / ONBOARD')).toBeInTheDocument()
    expect(screen.queryByText('Control source')).not.toBeInTheDocument()
    expect(screen.queryByText(/RC MANUAL/i)).not.toBeInTheDocument()
  })
})
