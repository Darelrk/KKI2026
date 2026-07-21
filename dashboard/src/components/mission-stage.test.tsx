import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MissionStage } from './mission-stage'

describe('MissionStage', () => {
  it('changes the active mission stage locally without exposing scoring controls', () => {
    render(<MissionStage />)

    expect(screen.queryByText('MISSION MOCKUP')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ready / Preparation' })).toBeInTheDocument()
    expect(screen.queryByText(/penal|total score|NM|IMH|IMB|DC/i)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Start' }))

    expect(screen.getByRole('status')).toHaveTextContent('Start')
    expect(screen.getByRole('button', { name: 'Start' })).toHaveAttribute('aria-pressed', 'true')
  })
})
