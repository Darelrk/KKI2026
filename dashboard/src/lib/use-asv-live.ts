import { useQuery } from '@tanstack/react-query'

import { getAsvDataMode } from './asv-data-mode'
import { fetchDirectAsvLive } from './direct-live'
import { getFixtureAsvLive } from './fixture-data'
import { asvBridgeUrl } from './stream-urls'
import type { AsvDataMode } from './asv-data-mode'

export type AsvRealtimeStatus = 'fixture' | 'connecting' | 'connected' | 'error'


export function useAsvLive(
  asvId: string,
  mode: AsvDataMode = getAsvDataMode(import.meta.env.VITE_ASV_DATA_MODE),
) {
  const queryKey = ['asv-live', asvId] as const
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) =>
      mode === 'fixture'
        ? Promise.resolve(getFixtureAsvLive(asvId))
        : fetchDirectAsvLive(asvBridgeUrl, asvId, signal),
    staleTime: mode === 'fixture' ? Number.POSITIVE_INFINITY : 0,
    refetchInterval: mode === 'direct' ? 2000 : false,
  })


  const directRealtimeStatus: AsvRealtimeStatus =
    query.isError ? 'error' : query.isSuccess ? 'connected' : 'connecting'
  const resolvedRealtimeStatus: AsvRealtimeStatus =
    mode === 'fixture' ? 'fixture' : directRealtimeStatus
  return {
    ...query,
    realtimeStatus: resolvedRealtimeStatus,
  }
}
