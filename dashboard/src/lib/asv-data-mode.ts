import { z } from 'zod'

export const asvDataModeSchema = z.enum(['fixture', 'direct', 'supabase'])

export type AsvDataMode = z.infer<typeof asvDataModeSchema>

export function getAsvDataMode(value: string): AsvDataMode {
  return asvDataModeSchema.parse(value)
}
