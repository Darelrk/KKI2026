import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DashboardClient } from './dashboard-client'
import { useAsvLive } from '../lib/use-asv-live'
import { useUnderwaterBroadcast } from '../lib/use-underwater-broadcast'
import { useTelemetryBroadcast } from '../lib/use-telemetry-broadcast'
import { useVisionMetadata } from '../lib/use-vision-metadata'

vi.mock('../lib/use-asv-live', () => ({ useAsvLive: vi.fn() }))
vi.mock('../lib/use-underwater-broadcast', () => ({
  useUnderwaterBroadcast: vi.fn(),
}))
vi.mock('../lib/use-telemetry-broadcast', () => ({
  useTelemetryBroadcast: vi.fn(),
}))
vi.mock('../lib/use-vision-metadata', () => ({
  useVisionMetadata: vi.fn(),
}))

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

describe('DashboardClient states', () => {
  it('renders the dashboard while the ASV status is pending', () => {
    vi.mocked(useAsvLive).mockReturnValue({
      isPending: true,
      isError: false,
      data: undefined,
      realtimeStatus: 'connecting',
    } as ReturnType<typeof useAsvLive>)
    vi.mocked(useUnderwaterBroadcast).mockReturnValue({
      frame: null,
      realtimeStatus: 'connecting',
    })
    vi.mocked(useTelemetryBroadcast).mockReturnValue({
      telemetry: null,
      realtimeStatus: 'connecting',
    })
    vi.mocked(useVisionMetadata).mockReturnValue({
      cache: null,
      realtimeStatus: 'error',
    })
    render(<DashboardClient asvId="default" mode="direct" />)

    expect(screen.getByRole('main')).not.toHaveAttribute('aria-busy', 'true')
    expect(
      screen.getByRole('heading', { name: 'Mission route' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('Telemetry unavailable')).not.toBeInTheDocument()
    expect(screen.getByText('MANUAL', { selector: 'dd' })).toBeInTheDocument()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('keeps the dashboard available when the live status request fails', () => {
    vi.mocked(useAsvLive).mockReturnValue({
      isPending: false,
      isError: true,
      data: undefined,
      realtimeStatus: 'error',
    } as ReturnType<typeof useAsvLive>)
    vi.mocked(useUnderwaterBroadcast).mockReturnValue({
      frame: null,
      realtimeStatus: 'error',
    })
    vi.mocked(useTelemetryBroadcast).mockReturnValue({
      telemetry: null,
      realtimeStatus: 'error',
    })
    vi.mocked(useVisionMetadata).mockReturnValue({
      cache: null,
      realtimeStatus: 'error',
    })
    render(<DashboardClient asvId="default" mode="direct" />)

    expect(
      screen.getByRole('heading', { name: 'Mission route' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('Telemetry unavailable')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Retry connection' }),
    ).not.toBeInTheDocument()
  })
})
