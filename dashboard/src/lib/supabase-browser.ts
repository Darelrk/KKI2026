import { createClient } from '@supabase/supabase-js'

import type { SupabaseClient } from '@supabase/supabase-js'

let browserClient: SupabaseClient | undefined

export function createSupabaseBrowser(url: string, publishableKey: string) {
  if (!url) {
    throw new Error('VITE_SUPABASE_URL is required')
  }

  if (!publishableKey) {
    throw new Error('VITE_SUPABASE_PUBLISHABLE_KEY is required')
  }

  return createClient(url, publishableKey, {
    auth: {
      autoRefreshToken: true,
      detectSessionInUrl: false,
      persistSession: true,
    },
  })
}

export function getSupabaseBrowser(): SupabaseClient {
  browserClient ??= createSupabaseBrowser(
    import.meta.env.VITE_SUPABASE_URL,
    import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY,
  )

  return browserClient
}
