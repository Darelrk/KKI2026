import { useEffect, useReducer, useRef } from 'react'

import {
  initialMissionSimulationState,
  missionRoutePosition,
  missionStageIndex,
  missionStages,
  reduceMissionSimulation,
} from './mission-simulation'

type UseMissionSimulationOptions = {
  /**
   * Start the local route replay once when the hook mounts.
   *
   * The default remains `false` so a live/direct dashboard never starts a
   * synthetic route unless the caller explicitly opts into preview behavior.
   */
  autoStart?: boolean
}

export function useMissionSimulation({
  autoStart = false,
}: UseMissionSimulationOptions = {}) {
  const [state, dispatch] = useReducer(
    reduceMissionSimulation,
    initialMissionSimulationState,
  )
  const hasAutoStarted = useRef(false)

  useEffect(() => {
    if (!autoStart || hasAutoStarted.current) {
      return
    }
    hasAutoStarted.current = true
    dispatch({ type: 'start' })
  }, [autoStart])

  useEffect(() => {
    if (state.status !== 'running') {
      return
    }
    const timer = window.setInterval(() => {
      dispatch({ type: 'tick', deltaMs: 50 })
    }, 50)
    return () => window.clearInterval(timer)
  }, [state.status])

  const start = () => dispatch({ type: 'start' })
  const stop = () => dispatch({ type: 'stop' })
  const reset = () => dispatch({ type: 'reset' })
  const selectStage = (index: number) => {
    const stageIndex = Math.min(
      missionStages.length - 1,
      Math.max(0, Math.floor(index)),
    )
    dispatch({
      type: 'seek',
      progress: missionStages[stageIndex].routeProgress,
    })
  }

  return {
    ...state,
    stageIndex: missionStageIndex(state.progress),
    position: missionRoutePosition(state.progress),
    start,
    pause: () => dispatch({ type: 'pause' }),
    stop,
    reset,
    selectStage,
  }
}

export type MissionSimulationController = ReturnType<
  typeof useMissionSimulation
>
