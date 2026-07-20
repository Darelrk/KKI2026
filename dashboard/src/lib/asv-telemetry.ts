import { z } from 'zod'

const gpsPointSchema = z.object({
  latitude: z.number().finite().min(-90).max(90),
  longitude: z.number().finite().min(-180).max(180),
  captured_at: z.string().datetime({ offset: true }),
})

export const asvTelemetrySchema = z.object({
  connected: z.boolean(),
  position: gpsPointSchema.nullable(),
  heading_deg: z.number().finite().nullable(),
  speed_mps: z.number().finite().nullable(),
  captured_at: z.string().datetime({ offset: true }),
  heartbeat_at: z.string().datetime({ offset: true }).nullable(),
  track: z.array(gpsPointSchema).max(500),
})

export type AsvTelemetry = z.infer<typeof asvTelemetrySchema>
