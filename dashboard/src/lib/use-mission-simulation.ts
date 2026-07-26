import { useEffect, useReducer, useState } from 'react'

import {
  initialMissionSimulationState,
  missionRoutePosition,
  missionStageIndex,
  missionStages,
  reduceMissionSimulation,
} from './mission-simulation'

export function useMissionSimulation() {
  const [state, dispatch] = useReducer(
    reduceMissionSimulation,
    initialMissionSimulationState,
  )
  const [selectedStage, setSelectedStage] = useState<number | null>(null)

  useEffect(() => {
    if (state.status !== 'running') {
      return
    }
    const timer = window.setInterval(() => {
      dispatch({ type: 'tick', deltaMs: 100 })
    }, 100)
    return () => window.clearInterval(timer)
  }, [state.status])

  const start = () => {
    setSelectedStage(null)
    dispatch({ type: 'start' })
  }
  const stop = () => {
    setSelectedStage(null)
    dispatch({ type: 'stop' })
  }
  const reset = () => {
    setSelectedStage(null)
    dispatch({ type: 'reset' })
  }
  const selectStage = (index: number) => {
    setSelectedStage(
      Math.min(missionStages.length - 1, Math.max(0, Math.floor(index))),
    )
  }

  return {
    ...state,
    stageIndex: selectedStage ?? missionStageIndex(state.progress),
    position: missionRoutePosition(state.progress),
    start,
    pause: () => dispatch({ type: 'pause' }),
    stop,
    reset,
    selectStage,
  }
}

export type MissionSimulationController = ReturnType<typeof useMissionSimulation>
