import { z } from 'zod'

const visionDetectionBoxSchema = z
  .object({
    label: z.string().min(1),
    confidence: z.number().finite().min(0).max(1),
    track_id: z.number().int().nullable(),
    x: z.number().finite().min(0).max(1),
    y: z.number().finite().min(0).max(1),
    width: z.number().finite().positive().max(1),
    height: z.number().finite().positive().max(1),
  })
  .strict()
  .refine((box) => box.x + box.width <= 1 && box.y + box.height <= 1, {
    message: 'detection box must fit inside source frame',
  })

export const visionMetadataSchema = z
  .object({
    schema_version: z.literal(1),
    asv_id: z.string().min(1),
    frame_id: z.number().int().nonnegative(),
    captured_at: z.string().datetime({ offset: true }),
    source_width: z.number().int().positive(),
    source_height: z.number().int().positive(),
    detections: z.array(visionDetectionBoxSchema),
  })
  .strict()

export type VisionMetadata = z.infer<typeof visionMetadataSchema>
export type VisionDetectionBox = z.infer<typeof visionDetectionBoxSchema>

export type VisionMetadataCache = {
  payload: VisionMetadata
  receivedAtMs: number
}

export type VisionSourceRect = {
  x: number
  y: number
  width: number
  height: number
}

export function isVisionMetadataFresh(
  cache: VisionMetadataCache | null,
  nowMs: number,
  staleAfterMs = 1000,
): boolean {
  return cache !== null && nowMs - cache.receivedAtMs < staleAfterMs
}

export function projectVisionBox(
  box: VisionDetectionBox,
  sourceRect: VisionSourceRect,
): VisionSourceRect {
  return {
    x: sourceRect.x + box.x * sourceRect.width,
    y: sourceRect.y + box.y * sourceRect.height,
    width: box.width * sourceRect.width,
    height: box.height * sourceRect.height,
  }
}
