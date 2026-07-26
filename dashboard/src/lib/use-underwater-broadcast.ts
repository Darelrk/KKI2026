import { useEffect, useState } from 'react'

import { getAsvDataMode } from './asv-data-mode'
import { fixtureUnderwaterFrame } from './fixture-data'

import type { AsvDataMode } from './asv-data-mode'
import type { UnderwaterFrame } from './asv-types'

export type UnderwaterRealtimeStatus =
  | 'fixture'
  | 'connecting'
  | 'connected'
  | 'error'

export function useUnderwaterBroadcast(
  _asvId: string,
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

    if (mode === 'direct') {
      setFrame(null)
      setRealtimeStatus('connected')
      return
    }
  }, [mode])


  return { frame, realtimeStatus }
}
