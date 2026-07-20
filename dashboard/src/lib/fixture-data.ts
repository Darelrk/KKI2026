import type { AsvLive, UnderwaterFrame } from './asv-types'
import type { AsvTelemetry } from './asv-telemetry'

export function getFixtureAsvLive(id: string): AsvLive {
  return {
    id,
    online: true,
    model_status: 'running',
    camera: 'surface',
    stream_url: null,
    run_id: 'fixture-run-001',
    updated_at: '2026-07-20T09:30:00.000Z',
  }
}

export const fixtureUnderwaterFrame = {
  mime: 'image/jpeg',
  data_base64:
    '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCAAJABADASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAABf/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AJpAIAn/2Q==',
  captured_at: '2026-07-20T09:30:00.000Z',
  frame_id: 'fixture-underwater-001',
} satisfies UnderwaterFrame

export const fixtureTelemetry = {
  connected: true,
  position: null,
  heading_deg: 144,
  speed_mps: 0,
  captured_at: '2026-07-20T09:30:00.000Z',
  heartbeat_at: '2026-07-20T09:29:59.000Z',
  track: [],
} satisfies AsvTelemetry
