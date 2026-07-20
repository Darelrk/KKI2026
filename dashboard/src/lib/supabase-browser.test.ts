import { describe, expect, it } from 'vitest'

import { createSupabaseBrowser } from './supabase-browser'

describe('createSupabaseBrowser', () => {
  it('rejects a missing public URL', () => {
    expect(() => createSupabaseBrowser('', 'public-key')).toThrow(
      'VITE_SUPABASE_URL is required',
    )
  })

  it('rejects a missing publishable key', () => {
    expect(() => createSupabaseBrowser('https://example.supabase.co', '')).toThrow(
      'VITE_SUPABASE_PUBLISHABLE_KEY is required',
    )
  })
})
