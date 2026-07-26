import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { fetchDirectAsvLive } from './direct-live'
import type { AsvLive } from './asv-types'
import { useAsvLive } from './use-asv-live'

vi.mock('./direct-live', () => ({ fetchDirectAsvLive: vi.fn() }))

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


  it('polls the direct bridge status', async () => {
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
    unmount()
  })
})
