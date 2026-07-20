import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DashboardClient } from './dashboard-client'
import { useAsvLive } from '../lib/use-asv-live'
import { useUnderwaterBroadcast } from '../lib/use-underwater-broadcast'

vi.mock('../lib/use-asv-live', () => ({ useAsvLive: vi.fn() }))
vi.mock('../lib/use-underwater-broadcast', () => ({ useUnderwaterBroadcast: vi.fn() }))

afterEach(() => {
  vi.resetAllMocks()
})

describe('DashboardClient states', () => {
  it('shows a loading state while the ASV status is pending', () => {
    vi.mocked(useAsvLive).mockReturnValue({ isPending: true } as ReturnType<typeof useAsvLive>)
    vi.mocked(useUnderwaterBroadcast).mockReturnValue({
      frame: null,
      realtimeStatus: 'connecting',
    })

    render(<DashboardClient asvId="default" mode="fixture" />)

    expect(screen.getByRole('main')).toHaveAttribute('aria-busy', 'true')
    expect(screen.getByText('Synchronising telemetry')).toBeInTheDocument()
  })

  it('shows a recovery action when the live status request fails', () => {
    const refetch = vi.fn()
    vi.mocked(useAsvLive).mockReturnValue({
      isPending: false,
      isError: true,
      refetch,
    } as unknown as ReturnType<typeof useAsvLive>)
    vi.mocked(useUnderwaterBroadcast).mockReturnValue({
      frame: null,
      realtimeStatus: 'error',
    })

    render(<DashboardClient asvId="default" mode="supabase" />)

    expect(screen.getByRole('alert')).toHaveTextContent('Telemetry link unavailable')
    const retry = screen.getByRole('button', { name: 'Retry connection' })
    expect(retry).toBeInTheDocument()
    fireEvent.click(retry)
    expect(refetch).toHaveBeenCalledOnce()
  })
})
