import { useEffect, useState } from 'react'

import { getAsvDataMode } from './asv-data-mode'
import { keepLatestUnderwaterFrame } from './asv-types'
import { fixtureUnderwaterFrame } from './fixture-data'
import { getSupabaseBrowser } from './supabase-browser'
import { ensureSupabaseRealtimeAuth } from './supabase-realtime-auth'

import type { AsvDataMode } from './asv-data-mode'
import type { UnderwaterFrame } from './asv-types'
import type { RealtimeChannel } from '@supabase/supabase-js'

export type UnderwaterRealtimeStatus =
  | 'fixture'
  | 'connecting'
  | 'connected'
  | 'error'

export function useUnderwaterBroadcast(
  asvId: string,
  mode: AsvDataMode = getAsvDataMode(import.meta.env.VITE_ASV_DATA_MODE),
) {
  const [frame, setFrame] = useState<UnderwaterFrame | null>(
    mode === 'fixture' ? fixtureUnderwaterFrame : null,
  )
  const [realtimeStatus, setRealtimeStatus] = useState<UnderwaterRealtimeStatus>(
    mode === 'fixture' ? 'fixture' : 'connecting',
  )

  useEffect(() => {
    if (mode === 'fixture') {
      setFrame(fixtureUnderwaterFrame)
      setRealtimeStatus('fixture')
      return
    }

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
          .channel(`asv-camera:${asvId}`, { config: { private: true } })
          .on('broadcast', { event: 'underwater_frame' }, ({ payload }) => {
            setFrame((previous) => keepLatestUnderwaterFrame(previous, payload))
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

  return { frame, realtimeStatus }
}
