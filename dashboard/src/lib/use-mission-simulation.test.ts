import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { missionDurationMs, missionStages } from './mission-simulation'
import { useMissionSimulation } from './use-mission-simulation'

describe('useMissionSimulation', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('advances the local replay clock only after start', () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useMissionSimulation())

    act(() => vi.advanceTimersByTime(500))
    expect(result.current.progress).toBe(0)

    act(() => result.current.start())
    act(() => vi.advanceTimersByTime(500))

    expect(result.current.status).toBe('running')
    expect(result.current.elapsedMs).toBe(500)
    expect(result.current.progress).toBe(500 / missionDurationMs)
  })

  it('can auto-start a local replay when preview mode opts in', () => {
    vi.useFakeTimers()
    const { result } = renderHook(() =>
      useMissionSimulation({ autoStart: true }),
    )

    expect(result.current.status).toBe('running')

    act(() => vi.advanceTimersByTime(500))

    expect(result.current.elapsedMs).toBe(500)
    expect(result.current.progress).toBe(500 / missionDurationMs)
  })

  it('does not auto-start when the option is omitted', () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useMissionSimulation())

    expect(result.current.status).toBe('idle')

    act(() => vi.advanceTimersByTime(500))

    expect(result.current.elapsedMs).toBe(0)
    expect(result.current.progress).toBe(0)
  })

  it('pauses, stops, and resets the replay controls', () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useMissionSimulation())

    act(() => result.current.start())
    act(() => vi.advanceTimersByTime(500))
    act(() => result.current.pause())
    act(() => vi.advanceTimersByTime(500))
    expect(result.current.status).toBe('paused')
    expect(result.current.elapsedMs).toBe(500)

    act(() => result.current.stop())
    expect(result.current.status).toBe('idle')
    expect(result.current.progress).toBe(0)

    act(() => result.current.start())
    act(() => vi.advanceTimersByTime(500))
    act(() => result.current.reset())
    expect(result.current.status).toBe('idle')
    expect(result.current.elapsedMs).toBe(0)
  })

  it('jumps to a mission stage and pauses there for operator sync', () => {
    const { result } = renderHook(() => useMissionSimulation())

    act(() => result.current.selectStage(4))

    expect(result.current.status).toBe('paused')
    expect(result.current.stageIndex).toBe(4)
    expect(result.current.progress).toBe(missionStages[4].routeProgress)
  })
})
