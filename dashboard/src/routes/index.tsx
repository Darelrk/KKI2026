import { createFileRoute } from '@tanstack/react-router'

import { DashboardClient } from '../components/dashboard-client'
import { getAsvDataMode } from '../lib/asv-data-mode'

export const Route = createFileRoute('/')({ component: Home })

function Home() {
  return (
    <DashboardClient
      asvId={import.meta.env.VITE_ASV_ID || 'default'}
      mode={getAsvDataMode(import.meta.env.VITE_ASV_DATA_MODE)}
    />
  )
}
