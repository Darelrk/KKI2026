import type { AsvLive, UnderwaterFrame } from './asv-types'
import type { AsvTelemetry } from './asv-telemetry'
import type { VisionMetadata } from './vision-metadata'
import { coursePointToGeo, kolamDeliSite } from './mission-site'
import { missionRouteHeading, missionRoutePosition } from './mission-simulation'

const fixtureStartTime = '2026-07-26T03:00:00.000Z'
const fixtureTrack = [0, 0.5, 1].map((progress, index) => ({
  ...coursePointToGeo(missionRoutePosition(progress), kolamDeliSite),
  captured_at: new Date(
    Date.parse(fixtureStartTime) + index * 15_000,
  ).toISOString(),
}))
const fixturePosition = fixtureTrack[fixtureTrack.length - 1]

export function getFixtureAsvLive(id: string): AsvLive {
  return {
    id,
    online: true,
    model_status: 'running',
    camera: 'surface',
    stream_url: null,
    run_id: 'KDI-LA-260726-01',
    updated_at: '2026-07-26T03:00:30.000Z',
  }
}

export const fixtureVisionMetadata = {
  schema_version: 1,
  asv_id: 'default',
  frame_id: 1,
  captured_at: fixtureStartTime,
  source_width: 1280,
  source_height: 720,
  detections: [
    {
      track_id: null,
      label: 'buoy',
      confidence: 0.91,
      x: 0.4,
      y: 0.25,
      width: 0.2,
      height: 0.2,
    },
  ],
} satisfies VisionMetadata

export const fixtureUnderwaterFrame = {
  mime: 'image/jpeg',
  data_base64:
    '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCAAJABADASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAABf/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AJpAIAn/2Q==',
  captured_at: fixtureStartTime,
  frame_id: 'fixture-underwater-001',
} satisfies UnderwaterFrame

export const fixtureTelemetry = {
  connected: true,
  position: fixturePosition,
  heading_deg: missionRouteHeading(1),
  speed_mps: 0,
  captured_at: fixturePosition.captured_at,
  heartbeat_at: fixturePosition.captured_at,
  track: fixtureTrack,
} satisfies AsvTelemetry
