import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { fetchAsvLive } from './asv-live-query'
import { fetchDirectAsvLive } from './direct-live'
import type { AsvLive } from './asv-types'
import { getSupabaseBrowser } from './supabase-browser'
import { ensureSupabaseRealtimeAuth } from './supabase-realtime-auth'
import { useAsvLive } from './use-asv-live'

vi.mock('./asv-live-query', () => ({ fetchAsvLive: vi.fn() }))
vi.mock('./direct-live', () => ({ fetchDirectAsvLive: vi.fn() }))
vi.mock('./supabase-browser', () => ({ getSupabaseBrowser: vi.fn() }))
vi.mock('./supabase-realtime-auth', () => ({
  ensureSupabaseRealtimeAuth: vi.fn(),
}))

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return function QueryWrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
  }
}

describe('useAsvLive', () => {
  it('returns fixture state through TanStack Query', async () => {
    const { result } = renderHook(() => useAsvLive('fixture-asv', 'fixture'), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.data).toMatchObject({
        id: 'fixture-asv',
        model_status: 'running',
      })
    })

    expect(result.current.realtimeStatus).toBe('fixture')
  })

  it('subscribes to Supabase updates and refreshes the query cache', async () => {
    const liveStatus = {
      id: 'default',
      online: true,
      model_status: 'running',
      camera: 'surface',
      stream_url: null,
      run_id: 'run-001',
      updated_at: '2026-07-20T09:30:00.000Z',
    } satisfies AsvLive
    const updatedStatus = {
      ...liveStatus,
      online: false,
      model_status: 'offline',
      updated_at: '2026-07-20T09:30:05.000Z',
    } satisfies AsvLive
    const channel = {
      on: vi.fn(),
      subscribe: vi.fn(),
    }
    channel.on.mockReturnValue(channel)
    channel.subscribe.mockReturnValue(channel)
    const client = {
      channel: vi.fn(() => channel),
      removeChannel: vi.fn(),
    }

    vi.mocked(getSupabaseBrowser).mockReturnValue(client as never)
    vi.mocked(fetchAsvLive).mockResolvedValue(liveStatus)
    vi.mocked(ensureSupabaseRealtimeAuth).mockResolvedValue()

    const { result, unmount } = renderHook(
      () => useAsvLive('default', 'supabase'),
      { wrapper: createWrapper() },
    )

    await waitFor(() => {
      expect(result.current.data).toEqual(liveStatus)
    })
    await waitFor(() => {
      expect(channel.on).toHaveBeenCalledOnce()
    })

    const onChange = channel.on.mock.calls[0]?.[2]
    if (typeof onChange !== 'function') {
      throw new Error('Expected a Postgres Changes callback')
    }
    onChange({ new: updatedStatus })

    await waitFor(() => {
      expect(result.current.data).toEqual(updatedStatus)
    })

    unmount()

    expect(client.removeChannel).toHaveBeenCalledWith(channel)
  })

  it('polls direct bridge status without creating a Supabase client', async () => {
    vi.mocked(getSupabaseBrowser).mockClear()
    const liveStatus = {
      id: 'default',
      online: true,
      model_status: 'running',
      camera: 'surface',
      stream_url: 'https://camera.example.test/stream.mjpg',
      run_id: 'run-001',
      updated_at: '2026-07-24T10:00:00.000Z',
    } satisfies AsvLive

    vi.mocked(fetchDirectAsvLive).mockResolvedValue(liveStatus)

    const { result, unmount } = renderHook(
      () => useAsvLive('default', 'direct'),
      { wrapper: createWrapper() },
    )

    await waitFor(() => {
      expect(result.current.data).toEqual(liveStatus)
    })

    expect(fetchDirectAsvLive).toHaveBeenCalledWith(
      'https://monitor-kapal-pora-pora.web.id',
      'default',
      expect.any(AbortSignal),
    )
    expect(getSupabaseBrowser).not.toHaveBeenCalled()
    unmount()
  })
})
