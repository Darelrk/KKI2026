import { useEffect, useState } from 'react'

import { getAsvDataMode } from './asv-data-mode'
import { asvTelemetrySchema } from './asv-telemetry'
import { fixtureTelemetry } from './fixture-data'
import { getSupabaseBrowser } from './supabase-browser'
import { ensureSupabaseRealtimeAuth } from './supabase-realtime-auth'

import type { AsvDataMode } from './asv-data-mode'
import type { AsvTelemetry } from './asv-telemetry'
import type { RealtimeChannel } from '@supabase/supabase-js'

export type TelemetryRealtimeStatus =
  | 'fixture'
  | 'connecting'
  | 'connected'
  | 'error'

export function useTelemetryBroadcast(
  asvId: string,
  mode: AsvDataMode = getAsvDataMode(import.meta.env.VITE_ASV_DATA_MODE),
) {
  const [telemetry, setTelemetry] = useState<AsvTelemetry | null>(
    mode === 'fixture' ? fixtureTelemetry : null,
  )
  const [realtimeStatus, setRealtimeStatus] = useState<TelemetryRealtimeStatus>(
    mode === 'fixture' ? 'fixture' : 'connecting',
  )

  useEffect(() => {
    if (mode === 'fixture') {
      setTelemetry(fixtureTelemetry)
      setRealtimeStatus('fixture')
      return
    }

    setTelemetry(null)
    setRealtimeStatus('connecting')

    const supabase = getSupabaseBrowser()
    let cancelled = false
    let channel: RealtimeChannel | undefined

    async function subscribe() {
      try {
        await ensureSupabaseRealtimeAuth(supabase)
        if (cancelled) {
          return
        }

        channel = supabase
          .channel(`asv-telemetry:${asvId}`, { config: { private: true } })
          .on('broadcast', { event: 'telemetry' }, ({ payload }) => {
            const parsed = asvTelemetrySchema.safeParse(payload)
            if (parsed.success) {
              setTelemetry(parsed.data)
            }
          })
          .subscribe((status) => {
            setRealtimeStatus(status === 'SUBSCRIBED' ? 'connected' : 'error')
          })
      } catch {
        if (!cancelled) {
          setRealtimeStatus('error')
        }
      }
    }

    void subscribe()

    return () => {
      cancelled = true
      if (channel) {
        void supabase.removeChannel(channel)
      }
    }
  }, [asvId, mode])

  return { telemetry, realtimeStatus }
}
