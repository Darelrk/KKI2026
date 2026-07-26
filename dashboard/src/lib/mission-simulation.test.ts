import { describe, expect, it } from 'vitest'

import {
  initialMissionSimulationState,
  missionDurationMs,
  missionRouteHeading,
  missionRoutePosition,
  missionRouteTravelledPoints,
  missionStageIndex,
  missionStages,
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
    expect(missionRoutePosition(0)).toEqual({ x: 85.1, y: 85.8 })
    // The live run leaves the upper-right dock down the right-hand side.
    expect(missionRoutePosition(0.05).y).toBeLessThan(85.8)
    expect(missionRoutePosition(1)).toEqual({ x: 85.1, y: 85.8 })
    expect(missionRouteHeading(0) > 330 || missionRouteHeading(0) < 30).toBe(
      true,
    )
    const surfacePoint = missionRoutePosition(missionStages[3].routeProgress)
    const underwaterPoint = missionRoutePosition(missionStages[4].routeProgress)
    expect(surfacePoint.x).toBeGreaterThanOrEqual(75)
    expect(surfacePoint.x).toBeLessThanOrEqual(85)
    expect(surfacePoint.y).toBeGreaterThanOrEqual(24)
    expect(surfacePoint.y).toBeLessThanOrEqual(32)
    expect(underwaterPoint.x).toBeGreaterThanOrEqual(60)
    expect(underwaterPoint.x).toBeLessThanOrEqual(72)
    expect(underwaterPoint.y).toBeGreaterThanOrEqual(20)
    expect(underwaterPoint.y).toBeLessThanOrEqual(28)
    expect(missionRouteTravelledPoints(0.5).length).toBeGreaterThan(2)
    expect(missionRouteTravelledPoints(0.5).length).toBeLessThan(
      missionRouteTravelledPoints(1).length,
    )
    expect(missionStages).toHaveLength(7)
    expect(missionStageIndex(0)).toBe(0)
    expect(missionStageIndex(0.05)).toBe(1)
    expect(missionStageIndex(0.24)).toBe(3)
    expect(missionStageIndex(0.3)).toBe(4)
    expect(missionStageIndex(0.5)).toBe(2)
    expect(missionStageIndex(1)).toBe(6)
  })

  it('seeks to a local mission stage without starting a command', () => {
    const seeked = reduceMissionSimulation(initialMissionSimulationState, {
      type: 'seek',
      progress: missionStages[4].routeProgress,
    })

    expect(seeked).toEqual({
      status: 'paused',
      elapsedMs: missionDurationMs * missionStages[4].routeProgress,
      progress: missionStages[4].routeProgress,
    })
  })

  it('keeps the mission running when seeking while it is already running', () => {
    const running = reduceMissionSimulation(initialMissionSimulationState, {
      type: 'start',
    })
    const seeked = reduceMissionSimulation(running, {
      type: 'seek',
      progress: missionStages[3].routeProgress,
    })

    expect(seeked).toEqual({
      status: 'running',
      elapsedMs: missionDurationMs * missionStages[3].routeProgress,
      progress: missionStages[3].routeProgress,
    })
  })
})
