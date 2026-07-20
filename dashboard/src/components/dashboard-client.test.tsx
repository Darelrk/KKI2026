import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
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
  it('loads the complete fixture dashboard without Supabase credentials', async () => {
    render(<DashboardClient asvId="default" mode="fixture" />, {
      wrapper: createWrapper(),
    })

    expect(await screen.findByText('MODEL RUNNING')).toBeInTheDocument()
    expect(screen.getByText('Surface stream unavailable')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Latest underwater frame' })).toBeInTheDocument()
  })
})
