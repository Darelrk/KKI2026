import type { AsvLive, UnderwaterFrame } from './asv-types'
import type { AsvTelemetry } from './asv-telemetry'
import type { VisionMetadata } from './vision-metadata'

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

export const fixtureVisionMetadata = {
  schema_version: 1,
  asv_id: 'default',
  frame_id: 1,
  captured_at: '2026-07-20T09:30:00.000Z',
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
  captured_at: '2026-07-20T09:30:00.000Z',
  frame_id: 'fixture-underwater-001',
} satisfies UnderwaterFrame

export const fixtureTelemetry = {
  connected: true,
  position: {
    latitude: -6.1224,
    longitude: 106.8226,
    captured_at: '2026-07-20T09:32:00.000Z',
  },
  heading_deg: 144,
  speed_mps: 0.6,
  captured_at: '2026-07-20T09:32:00.000Z',
  heartbeat_at: '2026-07-20T09:31:59.000Z',
  track: [
    {
      latitude: -6.1234,
      longitude: 106.821,
      captured_at: '2026-07-20T09:30:00.000Z',
    },
    {
      latitude: -6.123,
      longitude: 106.8218,
      captured_at: '2026-07-20T09:31:00.000Z',
    },
    {
      latitude: -6.1224,
      longitude: 106.8226,
      captured_at: '2026-07-20T09:32:00.000Z',
    },
  ],
} satisfies AsvTelemetry
