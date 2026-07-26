export const missionDurationMs = 30_000

export const missionStages = [
  {
    id: 'ready',
    label: 'Ready / Preparation',
    detail: 'Preflight checks',
    routeProgress: 0,
  },
  {
    id: 'start',
    label: 'Start',
    detail: 'Departure dock',
    routeProgress: 0.01,
  },
  {
    id: 'navigation',
    label: 'Navigation',
    detail: '10 buoy pairs',
    routeProgress: 0.08,
  },
  {
    id: 'surface',
    label: 'Surface imaging',
    detail: 'Green mission zone',
    routeProgress: 0.24,
  },
  {
    id: 'underwater',
    label: 'Underwater imaging',
    detail: 'Blue mission zone',
    routeProgress: 0.3,
  },
  {
    id: 'docking',
    label: 'Docking',
    detail: '3 blue docking balls',
    routeProgress: 0.94,
  },
  {
    id: 'finish',
    label: 'Finish',
    detail: 'Run complete',
    routeProgress: 1,
  },
] as const

const missionMonitoringResumeProgress = 0.36

export type MissionStageId = (typeof missionStages)[number]['id']

function missionStageProgressById(id: MissionStageId): number {
  const stage = missionStages.find((entry) => entry.id === id)
  if (!stage) {
    throw new RangeError(`Unknown mission stage id: ${id}`)
  }
  return stage.routeProgress
}

/**
 * Progress windows evaluated from the end of the run backwards. The boat
 * rejoins the buoy slalom once imaging stops, so `navigation` owns that
 * stretch a second time.
 */
const missionStageWindows: readonly { id: MissionStageId; from: number }[] = [
  { id: 'finish', from: missionStageProgressById('finish') },
  { id: 'docking', from: missionStageProgressById('docking') },
  { id: 'navigation', from: missionMonitoringResumeProgress },
  { id: 'underwater', from: missionStageProgressById('underwater') },
  { id: 'surface', from: missionStageProgressById('surface') },
  { id: 'navigation', from: missionStageProgressById('navigation') },
  { id: 'start', from: missionStageProgressById('start') },
]

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
  | { type: 'seek'; progress: number }
  | { type: 'tick'; deltaMs: number }

export type MissionRoutePoint = { x: number; y: number }

const referenceMissionRoute: readonly MissionRoutePoint[] = [
  { x: 85.1, y: 85.8 },
  { x: 78.5, y: 93.1 },
  { x: 73.8, y: 93.2 },
  { x: 62, y: 93.9 },
  { x: 50.5, y: 93.4 },
  { x: 40.4, y: 91.8 },
  { x: 29.7, y: 86.4 },
  { x: 15.7, y: 83.7 },
  { x: 10.3, y: 79.2 },
  { x: 9.4, y: 74.6 },
  { x: 10.7, y: 57.8 },
  { x: 10.2, y: 53.1 },
  { x: 13, y: 44.8 },
  { x: 15.6, y: 39.2 },
  { x: 22, y: 27.4 },
  { x: 27.1, y: 26 },
  { x: 34.5, y: 23.8 },
  { x: 44, y: 23.3 },
  { x: 53.4, y: 23.4 },
  { x: 64.5, y: 23.3 },
  { x: 72.5, y: 23.7 },
  { x: 79.4, y: 26.4 },
  { x: 84.4, y: 31.3 },
  { x: 85.7, y: 38.4 },
  { x: 85.6, y: 43 },
  { x: 84.8, y: 47.9 },
  { x: 82.1, y: 52.4 },
  { x: 80.1, y: 54.8 },
  { x: 80.5, y: 56.3 },
  { x: 84.9, y: 69.5 },
  { x: 85, y: 74.7 },
  { x: 85, y: 80.5 },
  { x: 85.1, y: 85.8 },
]

/**
 * The reference drawing is stored in the same vertex order as the supplied
 * course diagram. The live run starts at the upper-right dock and follows the
 * right-hand side downward, so the simulator traverses that closed loop in
 * reverse vertex order.
 */
export const missionRoute: readonly MissionRoutePoint[] = [
  ...referenceMissionRoute,
].reverse()

const missionRouteSegments = missionRoute.slice(0, -1).map((start, index) => {
  const end = missionRoute[index + 1]
  const length = Math.hypot(end.x - start.x, end.y - start.y)
  return { start, end, length }
})

const missionRouteLength = missionRouteSegments.reduce(
  (total, segment) => total + segment.length,
  0,
)

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
      return {
        ...state,
        status: 'running',
        elapsedMs: state.status === 'complete' ? 0 : state.elapsedMs,
        progress: state.status === 'complete' ? 0 : state.progress,
      }
    case 'pause':
      return state.status === 'running' ? { ...state, status: 'paused' } : state
    case 'stop':
    case 'reset':
      return initialMissionSimulationState
    case 'seek': {
      const progress = Math.min(1, Math.max(0, action.progress))
      const status =
        progress === 1
          ? 'complete'
          : state.status === 'running'
            ? 'running'
            : progress === 0
              ? 'idle'
              : 'paused'
      return {
        status,
        elapsedMs: progress * missionDurationMs,
        progress,
      }
    }
    case 'tick': {
      if (state.status !== 'running') {
        return state
      }
      const elapsedMs = Math.min(
        missionDurationMs,
        state.elapsedMs + Math.max(0, action.deltaMs),
      )
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
  if (clamped === 0) {
    return missionRoute[0]
  }
  if (clamped === 1) {
    return missionRoute.at(-1) ?? missionRoute[0]
  }
  let remainingDistance = clamped * missionRouteLength

  for (const segment of missionRouteSegments) {
    if (remainingDistance <= segment.length) {
      const fraction =
        segment.length === 0 ? 0 : remainingDistance / segment.length
      return {
        x: segment.start.x + (segment.end.x - segment.start.x) * fraction,
        y: segment.start.y + (segment.end.y - segment.start.y) * fraction,
      }
    }
    remainingDistance -= segment.length
  }

  return missionRoute.at(-1) ?? missionRoute[0]
}

export function missionRouteTravelledPoints(
  progress: number,
): readonly MissionRoutePoint[] {
  const clamped = Math.min(1, Math.max(0, progress))
  if (clamped === 0) {
    return [missionRoute[0]]
  }

  const targetDistance = clamped * missionRouteLength
  const points: MissionRoutePoint[] = [missionRoute[0]]
  let travelledDistance = 0

  for (const segment of missionRouteSegments) {
    const segmentEndDistance = travelledDistance + segment.length
    if (targetDistance >= segmentEndDistance) {
      points.push(segment.end)
      travelledDistance = segmentEndDistance
      continue
    }

    points.push(missionRoutePosition(clamped))
    break
  }

  return points
}

export function missionRouteHeading(progress: number): number {
  const clamped = Math.min(1, Math.max(0, progress))
  const lookAround = 0.002
  const startProgress =
    clamped >= 1 ? Math.max(0, clamped - lookAround) : clamped
  const endProgress = clamped >= 1 ? clamped : Math.min(1, clamped + lookAround)
  const start = missionRoutePosition(startProgress)
  const end = missionRoutePosition(endProgress)

  const heading = (Math.atan2(end.x - start.x, start.y - end.y) * 180) / Math.PI
  return (heading + 360) % 360
}

export function missionStageIndex(progress: number): number {
  const clamped = Math.min(1, Math.max(0, progress))
  const active = missionStageWindows.find((window) => clamped >= window.from)
  return active
    ? missionStages.findIndex((stage) => stage.id === active.id)
    : 0
}

export function formatMissionTime(elapsedMs: number): string {
  const seconds = Math.floor(elapsedMs / 1000)
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}
