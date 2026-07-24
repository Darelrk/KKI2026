import { z } from 'zod'

export const asvDataModeSchema = z.enum(['fixture', 'direct', 'supabase'])

export type AsvDataMode = z.infer<typeof asvDataModeSchema>

export function getAsvDataMode(value?: string | null): AsvDataMode {
  if (!value || typeof value !== 'string' || !value.trim() || value.trim() === 'supabase') {
    return 'direct'
  }
  const parsed = asvDataModeSchema.safeParse(value.trim())
  return parsed.success ? parsed.data : 'direct'
}
