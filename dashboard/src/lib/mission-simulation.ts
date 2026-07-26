export const missionDurationMs = 30_000

export const missionStages = [
  { id: 'ready', label: 'Ready / Preparation', detail: 'Preflight checks' },
  { id: 'start', label: 'Start', detail: 'Departure dock' },
  { id: 'navigation', label: 'Navigation', detail: '10 buoy pairs' },
  { id: 'surface', label: 'Surface imaging', detail: 'Green mission zone' },
  { id: 'underwater', label: 'Underwater imaging', detail: 'Blue mission zone' },
  { id: 'docking', label: 'Docking', detail: '3 blue docking balls' },
  { id: 'finish', label: 'Finish', detail: 'Run complete' },
] as const

export type MissionSimulationStatus = 'idle' | 'running' | 'paused' | 'complete'

export type MissionSimulationState = {
  status: MissionSimulationStatus
  elapsedMs: number
  progress: number
}

export type MissionSimulationAction =
  | { type: 'start' }
  | { type: 'pause' }
  | { type: 'stop' }
  | { type: 'reset' }
  | { type: 'tick'; deltaMs: number }

export type MissionRoutePoint = { x: number; y: number }

export const missionRoute: readonly MissionRoutePoint[] = [
  { x: 78, y: 80 },
  { x: 67, y: 84 },
  { x: 52, y: 88 },
  { x: 33, y: 84 },
  { x: 19, y: 75 },
  { x: 13, y: 57 },
  { x: 17, y: 38 },
  { x: 30, y: 21 },
  { x: 50, y: 17 },
  { x: 63, y: 19 },
  { x: 70, y: 32 },
  { x: 65, y: 48 },
  { x: 58, y: 59 },
  { x: 67, y: 69 },
  { x: 78, y: 80 },
]

export const initialMissionSimulationState: MissionSimulationState = {
  status: 'idle',
  elapsedMs: 0,
  progress: 0,
}

export function reduceMissionSimulation(
  state: MissionSimulationState,
  action: MissionSimulationAction,
): MissionSimulationState {
  switch (action.type) {
    case 'start':
      return { ...state, status: 'running', elapsedMs: state.status === 'complete' ? 0 : state.elapsedMs, progress: state.status === 'complete' ? 0 : state.progress }
    case 'pause':
      return state.status === 'running' ? { ...state, status: 'paused' } : state
    case 'stop':
    case 'reset':
      return initialMissionSimulationState
    case 'tick': {
      if (state.status !== 'running') {
        return state
      }
      const elapsedMs = Math.min(missionDurationMs, state.elapsedMs + Math.max(0, action.deltaMs))
      const progress = elapsedMs / missionDurationMs
      return {
        status: progress >= 1 ? 'complete' : 'running',
        elapsedMs,
        progress,
      }
    }
  }
}

export function missionRoutePosition(progress: number): MissionRoutePoint {
  const clamped = Math.min(1, Math.max(0, progress))
  const scaled = clamped * (missionRoute.length - 1)
  const segment = Math.min(missionRoute.length - 2, Math.floor(scaled))
  const fraction = scaled - segment
  const start = missionRoute[segment]
  const end = missionRoute[segment + 1]
  return {
    x: start.x + (end.x - start.x) * fraction,
    y: start.y + (end.y - start.y) * fraction,
  }
}

export function missionStageIndex(progress: number): number {
  return Math.min(
    missionStages.length - 1,
    Math.floor(Math.min(1, Math.max(0, progress)) * missionStages.length),
  )
}

export function formatMissionTime(elapsedMs: number): string {
  const seconds = Math.floor(elapsedMs / 1000)
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}
