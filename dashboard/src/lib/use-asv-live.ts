import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { getAsvDataMode } from './asv-data-mode'
import { fetchDirectAsvLive } from './direct-live'
import { fetchAsvLive } from './asv-live-query'
import { asvLiveSchema } from './asv-types'
import { getFixtureAsvLive } from './fixture-data'
import { asvBridgeUrl } from './stream-urls'
import { getSupabaseBrowser } from './supabase-browser'
import { ensureSupabaseRealtimeAuth } from './supabase-realtime-auth'

import type { AsvDataMode } from './asv-data-mode'
import type { RealtimeChannel } from '@supabase/supabase-js'

export type AsvRealtimeStatus = 'fixture' | 'connecting' | 'connected' | 'error'


export function useAsvLive(
  asvId: string,
  mode: AsvDataMode = getAsvDataMode(import.meta.env.VITE_ASV_DATA_MODE),
) {
  const queryClient = useQueryClient()
  const [realtimeStatus, setRealtimeStatus] = useState<AsvRealtimeStatus>(
    mode === 'fixture' ? 'fixture' : 'connecting',
  )
  const queryKey = ['asv-live', asvId] as const
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) =>
      mode === 'fixture'
        ? Promise.resolve(getFixtureAsvLive(asvId))
        : mode === 'direct'
          ? fetchDirectAsvLive(asvBridgeUrl, asvId, signal)
          : fetchAsvLive(getSupabaseBrowser(), asvId),
    staleTime: mode === 'fixture' ? Number.POSITIVE_INFINITY : 0,
    refetchInterval: mode === 'direct' ? 2000 : false,
  })

  useEffect(() => {
    if (mode === 'fixture' || mode === 'direct') {
      setRealtimeStatus(mode === 'fixture' ? 'fixture' : 'connecting')
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
          .channel(`asv-live:${asvId}`)
          .on(
            'postgres_changes',
            {
              event: '*',
              schema: 'public',
              table: 'asv_live',
              filter: `id=eq.${asvId}`,
            },
            (payload) => {
              const parsed = asvLiveSchema.safeParse(payload.new)
              if (parsed.success) {
                queryClient.setQueryData(queryKey, parsed.data)
              }
            },
          )
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
  }, [asvId, mode, queryClient])

  const directRealtimeStatus: AsvRealtimeStatus =
    query.isError ? 'error' : query.isSuccess ? 'connected' : 'connecting'
  return {
    ...query,
    realtimeStatus:
      mode === 'fixture'
        ? 'fixture'
        : mode === 'direct'
          ? directRealtimeStatus
          : realtimeStatus,
  }
}
