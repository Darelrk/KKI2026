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
  selectStage: vi.fn(),
} as unknown as MissionSimulationController

describe('MissionStage', () => {
  it('renders ASV mission controls without development disclaimers', () => {
    render(<MissionStage simulation={simulation} />)

    expect(
      screen.getByRole('heading', { name: 'Mission sequence' }),
    ).toBeInTheDocument()
    expect(screen.getByText('ASV MISSION CONTROL')).toBeInTheDocument()
    expect(
      screen.queryByText(/SIMULATION|DEMO|RC MANUAL|MAVLink/i),
    ).not.toBeInTheDocument()
    expect(screen.queryByText(/proposal route/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start mission' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Pause mission' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Stop mission' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Reset mission' })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: 'Start mission' }))
    expect(simulation.start).toHaveBeenCalledOnce()

    fireEvent.click(screen.getByRole('button', { name: 'Jump to Navigation' }))
    expect(simulation.selectStage).toHaveBeenCalledWith(2)
  })
})
