import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ControlModeToggle } from './control-mode-toggle'

afterEach(cleanup)

describe('ControlModeToggle', () => {
  it('ignores the active choice and reports the opposite choice', () => {
    const onChange = vi.fn()
    render(
      <ControlModeToggle
        mode="MANUAL"
        canEdit
        isUpdating={false}
        updateError={null}
        onChange={onChange}
      />,
    )

    expect(screen.getByRole('button', { name: 'MANUAL' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(
      screen.getByRole('button', { name: 'AUTONOMOUS' }),
    ).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(screen.getByRole('button', { name: 'MANUAL' }))
    expect(onChange).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'AUTONOMOUS' }))
    expect(onChange).toHaveBeenCalledWith('AUTONOMOUS')
  })

  it('disables both choices and announces an in-flight update', () => {
    const onChange = vi.fn()
    render(
      <ControlModeToggle
        mode="MANUAL"
        canEdit
        isUpdating
        updateError={null}
        onChange={onChange}
      />,
    )

    const group = screen.getByRole('group', { name: 'Runtime control mode' })
    expect(group).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('button', { name: 'MANUAL' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'AUTONOMOUS' })).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent(
      'Updating control mode…',
    )

    fireEvent.click(screen.getByRole('button', { name: 'AUTONOMOUS' }))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('announces an update error', () => {
    render(
      <ControlModeToggle
        mode="MANUAL"
        canEdit
        isUpdating={false}
        updateError={new Error('server rejected mode')}
        onChange={vi.fn()}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('server rejected mode')
  })

  it('marks fixture mode as read-only', () => {
    const onChange = vi.fn()
    render(
      <ControlModeToggle
        mode="AUTONOMOUS"
        canEdit={false}
        isUpdating={false}
        updateError={null}
        onChange={onChange}
      />,
    )

    const group = screen.getByRole('group', { name: 'Runtime control mode' })
    expect(group).toHaveAttribute('aria-disabled', 'true')
    expect(screen.getByRole('button', { name: 'AUTONOMOUS' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('button', { name: 'MANUAL' })).toBeDisabled()
    expect(screen.getByRole('note')).toHaveTextContent(
      'Fixture mode is read-only.',
    )

    fireEvent.click(screen.getByRole('button', { name: 'MANUAL' }))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('does not change an unavailable mode', () => {
    const onChange = vi.fn()
    render(
      <ControlModeToggle
        mode={null}
        canEdit
        isUpdating={false}
        updateError={null}
        onChange={onChange}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'MANUAL' }))
    fireEvent.click(screen.getByRole('button', { name: 'AUTONOMOUS' }))

    expect(onChange).not.toHaveBeenCalled()
  })
})
