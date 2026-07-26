import { describe, expect, it } from 'vitest'

import {
  initialMissionSimulationState,
  missionDurationMs,
  missionStages,
  missionRoutePosition,
  reduceMissionSimulation,
} from './mission-simulation'

describe('mission simulation model', () => {
  it('starts from an idle route at zero progress', () => {
    expect(initialMissionSimulationState).toEqual({
      status: 'idle',
      elapsedMs: 0,
      progress: 0,
    })
  })

  it('advances only while running and completes at the route end', () => {
    const running = reduceMissionSimulation(initialMissionSimulationState, {
      type: 'start',
    })
    const halfway = reduceMissionSimulation(running, {
      type: 'tick',
      deltaMs: missionDurationMs / 2,
    })
    const complete = reduceMissionSimulation(halfway, {
      type: 'tick',
      deltaMs: missionDurationMs,
    })

    expect(running.status).toBe('running')
    expect(halfway.progress).toBe(0.5)
    expect(complete).toMatchObject({
      status: 'complete',
      elapsedMs: missionDurationMs,
      progress: 1,
    })
  })

  it('pauses, stops, and replays without retaining stale progress', () => {
    const running = reduceMissionSimulation(initialMissionSimulationState, {
      type: 'start',
    })
    const halfway = reduceMissionSimulation(running, {
      type: 'tick',
      deltaMs: missionDurationMs / 2,
    })
    const paused = reduceMissionSimulation(halfway, { type: 'pause' })
    const stopped = reduceMissionSimulation(paused, { type: 'stop' })
    const replaying = reduceMissionSimulation(stopped, { type: 'start' })

    expect(paused).toEqual({
      status: 'paused',
      elapsedMs: missionDurationMs / 2,
      progress: 0.5,
    })
    expect(stopped).toEqual(initialMissionSimulationState)
    expect(replaying).toEqual({
      status: 'running',
      elapsedMs: 0,
      progress: 0,
    })
  })

  it('maps progress to the simulation route and mission stages', () => {
    expect(missionRoutePosition(0)).toEqual({ x: 78, y: 80 })
    expect(missionRoutePosition(1)).toEqual({ x: 78, y: 80 })
    expect(missionStages).toHaveLength(7)
  })
})
