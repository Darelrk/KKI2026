import { z } from 'zod'

export const cameraKindSchema = z.enum(['surface', 'underwater'])
export const modelStatusSchema = z.enum([
  'offline',
  'starting',
  'running',
  'error',
])

export const asvLiveSchema = z.object({
  id: z.string().min(1),
  online: z.boolean(),
  model_status: modelStatusSchema,
  camera: cameraKindSchema,
  stream_url: z.url().nullable(),
  run_id: z.string().min(1).nullable(),
  updated_at: z.string().datetime({ offset: true }),
})

export const maxUnderwaterFrameBase64Length = 180_000

const base64Pattern =
  /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/

export const underwaterFrameSchema = z.object({
  mime: z.literal('image/jpeg'),
  data_base64: z
    .string()
    .min(1)
    .max(maxUnderwaterFrameBase64Length)
    .regex(base64Pattern)
    .startsWith('/9j/'),
  captured_at: z.string().datetime({ offset: true }),
  frame_id: z.string().min(1),
})

export function keepLatestUnderwaterFrame(
  previous: UnderwaterFrame | null,
  payload: unknown,
): UnderwaterFrame | null {
  const parsed = underwaterFrameSchema.safeParse(payload)

  return parsed.success ? parsed.data : previous
}

export type AsvId = string
export type CameraKind = z.infer<typeof cameraKindSchema>
export type ModelStatus = z.infer<typeof modelStatusSchema>
export type AsvLive = z.infer<typeof asvLiveSchema>
export type UnderwaterFrame = z.infer<typeof underwaterFrameSchema>
