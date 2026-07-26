import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { missionRoutePosition } from '../lib/mission-simulation'
import type { MissionSimulationController } from '../lib/use-mission-simulation'
import { MissionStage } from './mission-stage'

const simulation = {
  status: 'idle',
  elapsedMs: 0,
  progress: 0,
  stageIndex: 0,
  position: missionRoutePosition(0),
  start: vi.fn(),
  pause: vi.fn(),
  stop: vi.fn(),
  reset: vi.fn(),
} as unknown as MissionSimulationController

describe('MissionStage', () => {
  it('renders local simulation controls without claiming real autonomy', () => {
    render(<MissionStage simulation={simulation} />)

    expect(screen.getByRole('heading', { name: 'Mission sequence' })).toBeInTheDocument()
    expect(screen.getByText('SIMULATION / DEMO')).toBeInTheDocument()
    expect(screen.queryByText(/LOCAL UI REPLAY|MAVLink commands/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/RC MANUAL/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/proposal route/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start simulation' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Pause simulation' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Stop simulation' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Reset simulation' })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: 'Start simulation' }))
    expect(simulation.start).toHaveBeenCalledOnce()
  })
})
