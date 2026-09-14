import { useEffect, useRef, useState } from 'react'
import type { ControlChannelLike } from '../lib/control-channel'
import { PWM_MAX, PWM_MIN, type PwmPair } from '../lib/control-protocol'

export interface RemoteControlPanelProps {
  channel: ControlChannelLike
  disabled?: boolean
}

const INITIAL_PAIR: PwmPair = { steering_pwm: 1500, throttle_pwm: 1500 }
const KEYBOARD_KEYS = new Set([
  'ArrowUp',
  'ArrowDown',
  'ArrowLeft',
  'ArrowRight',
  'Home',
  'End',
  'PageUp',
  'PageDown',
])

function readPwm(value: string): number | null {
  if (!/^\d+$/.test(value)) return null
  const pwm = Number(value)
  return Number.isSafeInteger(pwm) && pwm >= PWM_MIN && pwm <= PWM_MAX ? pwm : null
}

export function RemoteControlPanel({ channel, disabled = channel.isAvailable === false }: RemoteControlPanelProps) {
  const [pair, setPair] = useState<PwmPair>(INITIAL_PAIR)
  const engaged = useRef(false)

  const engage = () => {
    if (disabled || engaged.current) return
    engaged.current = true
    channel.engage(pair)
  }

  const release = () => {
    engaged.current = false
    channel.release()
  }

  const change = (axis: keyof PwmPair, value: string) => {
    const pwm = readPwm(value)
    if (pwm === null) return
    const nextPair = { ...pair, [axis]: pwm }
    setPair(nextPair)
    if (engaged.current) channel.setPwmPair(nextPair)
  }

  useEffect(() => {
    if (!disabled) return
    engaged.current = false
    channel.release()
  }, [channel, disabled])

  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'hidden') release()
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
      release()
    }
  }, [channel])

  return (
    <section className="remote-control-panel" aria-label="Direct PWM controls">
      <label className="remote-slider">
        <span>Throttle PWM</span>
        <input
          type="range"
          min={PWM_MIN}
          max={PWM_MAX}
          step={1}
          value={pair.throttle_pwm}
          disabled={disabled}
          onChange={(event) => change('throttle_pwm', event.currentTarget.value)}
          onPointerDown={engage}
          onPointerUp={release}
          onPointerCancel={release}
          onBlur={release}
          onFocus={engage}
          onKeyDown={(event) => {
            if (KEYBOARD_KEYS.has(event.key)) engage()
          }}
          onKeyUp={release}
        />
      </label>
      <label className="remote-slider">
        <span>Steering PWM</span>
        <input
          type="range"
          min={PWM_MIN}
          max={PWM_MAX}
          step={1}
          value={pair.steering_pwm}
          disabled={disabled}
          onChange={(event) => change('steering_pwm', event.currentTarget.value)}
          onPointerDown={engage}
          onPointerUp={release}
          onPointerCancel={release}
          onBlur={release}
          onFocus={engage}
          onKeyDown={(event) => {
            if (KEYBOARD_KEYS.has(event.key)) engage()
          }}
          onKeyUp={release}
        />
      </label>
    </section>
  )
}
