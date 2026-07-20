import type { SupabaseClient } from '@supabase/supabase-js'

import { asvLiveSchema } from './asv-types'

import type { AsvLive } from './asv-types'

const asvLiveColumns =
  'id, online, model_status, camera, stream_url, run_id, updated_at'

export async function fetchAsvLive(
  client: Pick<SupabaseClient, 'from'>,
  asvId: string,
): Promise<AsvLive | null> {
  const { data, error } = await client
    .from('asv_live')
    .select(asvLiveColumns)
    .eq('id', asvId)
    .maybeSingle()

  if (error) {
    throw error
  }

  return data === null ? null : asvLiveSchema.parse(data)
}
