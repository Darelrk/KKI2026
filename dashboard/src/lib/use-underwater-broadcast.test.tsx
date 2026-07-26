import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useUnderwaterBroadcast } from './use-underwater-broadcast'


describe('useUnderwaterBroadcast', () => {
  it('returns the deterministic fixture frame', () => {
    const { result } = renderHook(() =>
      useUnderwaterBroadcast('fixture-asv', 'fixture'),
    )

    expect(result.current.frame).toMatchObject({
      mime: 'image/jpeg',
      frame_id: 'fixture-underwater-001',
    })
    expect(result.current.realtimeStatus).toBe('fixture')
  })


  it('keeps direct mode on the raw tunnel stream', async () => {
    const { result } = renderHook(() =>
      useUnderwaterBroadcast('default', 'direct'),
    )

    await waitFor(() => {
      expect(result.current.realtimeStatus).toBe('connected')
    })

    expect(result.current.frame).toBeNull()
  })
})
