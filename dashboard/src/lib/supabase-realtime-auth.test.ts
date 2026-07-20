import { describe, expect, it, vi } from 'vitest'

import { ensureSupabaseRealtimeAuth } from './supabase-realtime-auth'

describe('ensureSupabaseRealtimeAuth', () => {
  it('uses an existing session for the private realtime channel', async () => {
    const getSession = vi.fn().mockResolvedValue({
      data: { session: { access_token: 'existing-token' } },
      error: null,
    })
    const signInAnonymously = vi.fn()
    const setAuth = vi.fn()

    await ensureSupabaseRealtimeAuth({
      auth: { getSession, signInAnonymously },
      realtime: { setAuth },
    } as never)

    expect(signInAnonymously).not.toHaveBeenCalled()
    expect(setAuth).toHaveBeenCalledWith('existing-token')
  })

  it('creates an anonymous session when no session exists', async () => {
    const getSession = vi.fn().mockResolvedValue({
      data: { session: null },
      error: null,
    })
    const signInAnonymously = vi.fn().mockResolvedValue({
      data: { session: { access_token: 'anonymous-token' } },
      error: null,
    })
    const setAuth = vi.fn()

    await ensureSupabaseRealtimeAuth({
      auth: { getSession, signInAnonymously },
      realtime: { setAuth },
    } as never)

    expect(signInAnonymously).toHaveBeenCalledOnce()
    expect(setAuth).toHaveBeenCalledWith('anonymous-token')
  })

  it('propagates an authentication failure', async () => {
    const getSession = vi.fn().mockResolvedValue({
      data: { session: null },
      error: null,
    })
    const signInAnonymously = vi
      .fn()
      .mockResolvedValue({ data: { session: null }, error: new Error('anonymous disabled') })

    await expect(
      ensureSupabaseRealtimeAuth({
        auth: { getSession, signInAnonymously },
        realtime: { setAuth: vi.fn() },
      } as never),
    ).rejects.toThrow('anonymous disabled')
  })
})
