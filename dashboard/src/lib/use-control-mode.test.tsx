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

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  })

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
    expect(result.current.isError).toBe(false)
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
