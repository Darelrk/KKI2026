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
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

describe('DashboardClient', () => {
  it('loads the complete fixture dashboard with direct raw camera streams', async () => {
    render(<DashboardClient asvId="default" mode="fixture" />, {
      wrapper: createWrapper(),
    })

    expect(await screen.findByText('MODEL RUNNING')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Live surface camera' })).toHaveAttribute(
      'src',
      'https://monitor-kapal-pora-pora.web.id/stream/atas',
    )
    expect(screen.getByRole('img', { name: 'Live underwater action camera' })).toHaveAttribute(
      'src',
      'https://monitor-kapal-pora-pora.web.id/stream/bawah',
    )
    expect(screen.getByRole('heading', { name: 'Live boat track' })).toBeInTheDocument()
    expect(screen.getByText('GPS position available')).toBeInTheDocument()
    expect(screen.getByText('GPS track · 3 points')).toBeInTheDocument()
    expect(
      within(screen.getByRole('region', { name: 'Live boat track' })).queryByText('MISSION MOCKUP'),
    ).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Ready / Preparation')
  })
})
