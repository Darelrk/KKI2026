import type { SupabaseClient } from '@supabase/supabase-js'

export async function ensureSupabaseRealtimeAuth(
  client: Pick<SupabaseClient, 'auth' | 'realtime'>,
): Promise<void> {
  const { data, error } = await client.auth.getSession()

  if (error) {
    throw error
  }

  const signInResult = data.session
    ? { data: { session: data.session }, error: null }
    : await client.auth.signInAnonymously()

  if (signInResult.error) {
    throw signInResult.error
  }

  if (!signInResult.data.session) {
    throw new Error('Supabase did not provide an anonymous session')
  }

  await client.realtime.setAuth(signInResult.data.session.access_token)
}
