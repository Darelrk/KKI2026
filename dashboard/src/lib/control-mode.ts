import { z } from 'zod'

export const controlModeSchema = z.enum(['MANUAL', 'AUTONOMOUS'])

export const controlModeResponseSchema = z
  .object({ mode: controlModeSchema })
  .strict()

export type ControlMode = z.infer<typeof controlModeSchema>
