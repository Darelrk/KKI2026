import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MissionStage } from './mission-stage'

describe('MissionStage', () => {
  it('renders the production mission sequence and targets without control actions', () => {
    render(<MissionStage />)

    expect(screen.queryByText('MISSION MOCKUP')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Mission sequence' })).toBeInTheDocument()
    expect(screen.getAllByText('Ready / Preparation')).toHaveLength(2)
    expect(screen.getByText('10 buoy pairs')).toBeInTheDocument()
    expect(screen.getByText('3 blue docking balls')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Standby')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
