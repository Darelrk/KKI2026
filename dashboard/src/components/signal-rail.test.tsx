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
  it('identifies model monitoring and manual RC control', () => {
    render(
      <SignalRail
        live={live}
        telemetryConnected={true}
        telemetryStatus="connected"
      />,
    )

    expect(screen.getByText('MODEL MONITORING')).toBeInTheDocument()
    expect(screen.getByText('MODEL RUNNING')).toBeInTheDocument()
    expect(screen.getByText('Control source')).toBeInTheDocument()
    expect(screen.getByText('RC MANUAL')).toBeInTheDocument()
  })
})
