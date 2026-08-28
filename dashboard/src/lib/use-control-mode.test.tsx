import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchControlMode, putControlMode } from './direct-live'
import { useControlMode } from './use-control-mode'

vi.mock('./direct-live', () => ({
  fetchControlMode: vi.fn(),
  putControlMode: vi.fn(),
}))

const bridgeUrl = 'https://monitor-kapal-pora-pora.web.id'

function createWrapper(
  queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  }),
) {
  return function QueryWrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('useControlMode', () => {
  it('loads the initial direct mode as MANUAL', async () => {
    vi.mocked(fetchControlMode).mockResolvedValue('MANUAL')

    const { result } = renderHook(() => useControlMode('default', 'direct'), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.mode).toBe('MANUAL')
    })

    expect(fetchControlMode).toHaveBeenCalledWith(bridgeUrl, expect.any(AbortSignal))
    expect(result.current.canEdit).toBe(true)
    expect(result.current.readOnly).toBe(false)
  })

  it('isolates direct and fixture caches for the same ASV', async () => {
    vi.mocked(fetchControlMode).mockResolvedValue('MANUAL')

    const queryClient = new QueryClient({
      defaultOptions: {
        mutations: { retry: false },
        queries: { retry: false },
      },
    })
    const { result, rerender } = renderHook(
      ({ dataMode }: { dataMode: 'direct' | 'fixture' }) =>
        useControlMode('shared-asv', dataMode),
      {
        initialProps: { dataMode: 'direct' },
        wrapper: createWrapper(queryClient),
      },
    )

    await waitFor(() => {
      expect(result.current.mode).toBe('MANUAL')
    })

    rerender({ dataMode: 'fixture' })
    await waitFor(() => {
      expect(result.current.mode).toBe('AUTONOMOUS')
    })
    expect(result.current.readOnly).toBe(true)

    rerender({ dataMode: 'direct' })
    await waitFor(() => {
      expect(result.current.mode).toBe('MANUAL')
    })
    expect(fetchControlMode).toHaveBeenCalledTimes(2)
  })

  it('cancels an in-flight read before caching a successful mode update', async () => {
    let resolveStaleFetch!: (mode: 'MANUAL' | 'AUTONOMOUS') => void
    const staleFetch = new Promise<'MANUAL' | 'AUTONOMOUS'>((resolve) => {
      resolveStaleFetch = resolve
    })
    vi.mocked(fetchControlMode).mockReturnValue(staleFetch)
    vi.mocked(putControlMode).mockResolvedValue('AUTONOMOUS')

    const queryClient = new QueryClient({
      defaultOptions: {
        mutations: { retry: false },
        queries: { retry: false },
      },
    })
    const cancelQueries = vi.spyOn(queryClient, 'cancelQueries')
    const { result } = renderHook(() => useControlMode('default', 'direct'), {
      wrapper: createWrapper(queryClient),
    })

    await waitFor(() => {
      expect(fetchControlMode).toHaveBeenCalled()
    })

    act(() => {
      result.current.updateMode('AUTONOMOUS')
    })
    await waitFor(() => {
      expect(result.current.mode).toBe('AUTONOMOUS')
    })

    resolveStaleFetch('MANUAL')
    await staleFetch
    await waitFor(() => {
      expect(result.current.mode).toBe('AUTONOMOUS')
    })
    expect(cancelQueries).toHaveBeenCalledWith({
      queryKey: ['asv-control-mode', 'default', 'direct'],
    })
  })

  it('keeps a pending direct mutation bound to its original cache', async () => {
    vi.mocked(fetchControlMode).mockResolvedValue('MANUAL')
    let resolvePut!: (mode: 'MANUAL' | 'AUTONOMOUS') => void
    const pendingPut = new Promise<'MANUAL' | 'AUTONOMOUS'>((resolve) => {
      resolvePut = resolve
    })
    vi.mocked(putControlMode).mockReturnValue(pendingPut)

    const queryClient = new QueryClient({
      defaultOptions: {
        mutations: { retry: false },
        queries: { retry: false },
      },
    })
    const setQueryData = vi.spyOn(queryClient, 'setQueryData')
    const { result, rerender } = renderHook(
      ({ dataMode }: { dataMode: 'direct' | 'fixture' }) =>
        useControlMode('shared-asv', dataMode),
      {
        initialProps: { dataMode: 'direct' },
        wrapper: createWrapper(queryClient),
      },
    )

    await waitFor(() => {
      expect(result.current.mode).toBe('MANUAL')
    })

    act(() => {
      result.current.updateMode('AUTONOMOUS')
    })
    await waitFor(() => {
      expect(putControlMode).toHaveBeenCalledWith(bridgeUrl, 'AUTONOMOUS')
    })

    rerender({ dataMode: 'fixture' })
    await waitFor(() => {
      expect(result.current.mode).toBe('AUTONOMOUS')
      expect(result.current.readOnly).toBe(true)
    })
    setQueryData.mockClear()

    await act(async () => {
      resolvePut('AUTONOMOUS')
      await pendingPut
    })
    await waitFor(() => {
      expect(result.current.isUpdating).toBe(false)
    })

    expect(result.current.mode).toBe('AUTONOMOUS')
    expect(result.current.readOnly).toBe(true)
    expect(setQueryData).toHaveBeenCalledWith(
      ['asv-control-mode', 'shared-asv', 'direct'],
      'AUTONOMOUS',
    )
    expect(setQueryData).not.toHaveBeenCalledWith(
      ['asv-control-mode', 'shared-asv', 'fixture'],
      'AUTONOMOUS',
    )
    expect(
      queryClient.getQueryData(['asv-control-mode', 'shared-asv', 'fixture']),
    ).toBe('AUTONOMOUS')
  })

  it('transitions between MANUAL and AUTONOMOUS', async () => {
    vi.mocked(fetchControlMode).mockResolvedValue('MANUAL')
    vi.mocked(putControlMode).mockImplementation(async (_baseUrl, mode) => mode)

    const { result } = renderHook(() => useControlMode('default', 'direct'), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.mode).toBe('MANUAL')
    })

    act(() => {
      result.current.updateMode('AUTONOMOUS')
    })
    await waitFor(() => {
      expect(result.current.mode).toBe('AUTONOMOUS')
    })

    act(() => {
      result.current.updateMode('MANUAL')
    })
    await waitFor(() => {
      expect(result.current.mode).toBe('MANUAL')
    })

    expect(putControlMode).toHaveBeenNthCalledWith(1, bridgeUrl, 'AUTONOMOUS')
    expect(putControlMode).toHaveBeenNthCalledWith(2, bridgeUrl, 'MANUAL')
  })

  it('preserves the last valid mode when an update fails', async () => {
    const error = new Error('bridge refused mode change')
    vi.mocked(fetchControlMode).mockResolvedValue('MANUAL')
    vi.mocked(putControlMode).mockRejectedValue(error)

    const { result } = renderHook(() => useControlMode('default', 'direct'), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.mode).toBe('MANUAL')
    })

    act(() => {
      result.current.updateMode('AUTONOMOUS')
    })
    await waitFor(() => {
      expect(result.current.error).toBe(error)
    })

    expect(result.current.mode).toBe('MANUAL')
    expect(result.current.isError).toBe(true)
  })

  it('uses fixture AUTONOMOUS mode without HTTP access', async () => {
    const { result } = renderHook(() => useControlMode('fixture-asv', 'fixture'), {
      wrapper: createWrapper(),
    })

    await waitFor(() => {
      expect(result.current.mode).toBe('AUTONOMOUS')
    })

    expect(result.current.readOnly).toBe(true)
    expect(result.current.canEdit).toBe(false)
    await act(async () => {
      result.current.updateMode('MANUAL')
      await Promise.resolve()
    })
    expect(result.current.mode).toBe('AUTONOMOUS')
    expect(fetchControlMode).not.toHaveBeenCalled()
    expect(putControlMode).not.toHaveBeenCalled()
  })
})
