import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { describe, expect, it } from 'vitest'

import { DashboardClient } from './dashboard-client'

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

describe('DashboardClient', () => {
  it('loads the complete fixture dashboard with direct raw camera streams', async () => {
    render(<DashboardClient asvId="default" mode="fixture" />, {
      wrapper: createWrapper(),
    })

    expect(await screen.findByText('MODEL RUNNING')).toBeInTheDocument()
    expect(screen.getByText('MODEL MONITORING')).toBeInTheDocument()
    expect(screen.getByText('Control mode')).toBeInTheDocument()
    expect(screen.getByText('MANUAL', { selector: 'dd' })).toBeInTheDocument()
    expect(screen.queryByText('AUTO / ONBOARD')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'AUTONOMOUS' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'MANUAL' })).not.toBeInTheDocument()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
    expect(screen.queryByText(/RC MANUAL|MAVLink/i)).not.toBeInTheDocument()
    expect(
      screen.getByRole('img', { name: 'Live surface camera' }),
    ).toHaveAttribute(
      'src',
      'https://monitor-kapal-pora-pora.web.id/stream/atas',
    )
    expect(
      screen.getByRole('img', { name: 'Live underwater action camera' }),
    ).toHaveAttribute(
      'src',
      'https://monitor-kapal-pora-pora.web.id/stream/bawah',
    )
    expect(
      screen.getByRole('heading', { name: 'Mission route' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/Lintasan A · \d+%/)).toBeInTheDocument()
    expect(
      screen.getByText('ASV navigation · mission active'),
    ).toBeInTheDocument()
    expect(
      within(screen.getByRole('region', { name: 'Mission route' })).queryByText(
        'MISSION MOCKUP',
      ),
    ).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Mission route active')
  })
})
