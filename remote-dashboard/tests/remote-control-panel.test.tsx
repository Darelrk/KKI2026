import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ControlChannelLike } from '../src/lib/control-channel'
import { RemoteControlPanel } from '../src/components/remote-control-panel'

type FakePanelChannel = ControlChannelLike

const makeChannel = (): FakePanelChannel => ({
  connect: vi.fn(),
  close: vi.fn(),
  isAvailable: true,
  engage: vi.fn(),
  setPwmPair: vi.fn(() => true),
  release: vi.fn(),
})

describe('RemoteControlPanel', () => {
  it('renders exactly two accessible direct PWM sliders and no command UI', () => {
    const channel = makeChannel()
    const { container } = render(<RemoteControlPanel channel={channel} />)
    expect(container.querySelectorAll('input[type="range"]')).toHaveLength(2)
    expect(screen.getByLabelText('Throttle PWM')).toHaveValue('1500')
    expect(screen.getByLabelText('Steering PWM')).toHaveValue('1500')
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.queryByText(/telemetry|status|latency|ack|autonomous|arm|disarm|underwater|vision|model/i)).toBeNull()
  })

  it('sends the current pair while pointer engaged and releases on pointerup', () => {
    const channel = makeChannel()
    render(<RemoteControlPanel channel={channel} />)
    const throttle = screen.getByLabelText('Throttle PWM')
    const steering = screen.getByLabelText('Steering PWM')

    fireEvent.pointerDown(throttle)
    fireEvent.change(throttle, { target: { value: '1600' } })
    fireEvent.change(steering, { target: { value: '1400' } })
    fireEvent.pointerUp(throttle)

    expect(channel.engage).toHaveBeenCalledWith({ steering_pwm: 1500, throttle_pwm: 1500 })
    expect(channel.setPwmPair).toHaveBeenCalledWith({ steering_pwm: 1500, throttle_pwm: 1600 })
    expect(channel.setPwmPair).toHaveBeenCalledWith({ steering_pwm: 1400, throttle_pwm: 1600 })
    expect(channel.release).toHaveBeenCalled()
  })

  it('engages for keyboard movement and releases when the key is lifted or focus is lost', () => {
    const channel = makeChannel()
    render(<RemoteControlPanel channel={channel} />)
    const steering = screen.getByLabelText('Steering PWM')

    fireEvent.focus(steering)
    fireEvent.keyDown(steering, { key: 'ArrowRight' })
    fireEvent.change(steering, { target: { value: '1501' } })
    fireEvent.keyUp(steering, { key: 'ArrowRight' })
    fireEvent.blur(steering)

    expect(channel.engage).toHaveBeenCalled()
    expect(channel.setPwmPair).toHaveBeenCalledWith({ steering_pwm: 1501, throttle_pwm: 1500 })
    expect(channel.release).toHaveBeenCalledTimes(2)
  })

  it('releases on unmount', () => {
    const channel = makeChannel()
    const { unmount } = render(<RemoteControlPanel channel={channel} />)

    unmount()

    expect(channel.release).toHaveBeenCalledTimes(1)
  })
})
