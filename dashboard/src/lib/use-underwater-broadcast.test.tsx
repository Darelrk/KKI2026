import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { getSupabaseBrowser } from './supabase-browser'
import { ensureSupabaseRealtimeAuth } from './supabase-realtime-auth'
import { useUnderwaterBroadcast } from './use-underwater-broadcast'

vi.mock('./supabase-browser', () => ({ getSupabaseBrowser: vi.fn() }))
vi.mock('./supabase-realtime-auth', () => ({
  ensureSupabaseRealtimeAuth: vi.fn(),
}))

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

  it('updates only from a valid private Broadcast payload', async () => {
    const originalFrame = {
      mime: 'image/jpeg',
      data_base64: '/9j/4AAQSkZJRgABAQAAAQABAAD/2w==',
      captured_at: '2026-07-20T09:30:00.000Z',
      frame_id: 'underwater-001',
    }
    const updatedFrame = {
      ...originalFrame,
      captured_at: '2026-07-20T09:30:01.000Z',
      frame_id: 'underwater-002',
    }
    const channel = {
      on: vi.fn(),
      subscribe: vi.fn(),
    }
    channel.on.mockReturnValue(channel)
    channel.subscribe.mockReturnValue(channel)
    const client = {
      channel: vi.fn(() => channel),
      removeChannel: vi.fn(),
    }

    vi.mocked(getSupabaseBrowser).mockReturnValue(client as never)
    vi.mocked(ensureSupabaseRealtimeAuth).mockResolvedValue()

    const { result, unmount } = renderHook(() =>
      useUnderwaterBroadcast('default', 'supabase'),
    )

    await waitFor(() => {
      expect(channel.on).toHaveBeenCalledOnce()
    })

    const onFrame = channel.on.mock.calls[0]?.[2]
    if (typeof onFrame !== 'function') {
      throw new Error('Expected an underwater Broadcast callback')
    }
    onFrame({ payload: updatedFrame })

    await waitFor(() => {
      expect(result.current.frame).toEqual(updatedFrame)
    })

    onFrame({ payload: { ...updatedFrame, mime: 'image/png' } })

    expect(result.current.frame).toEqual(updatedFrame)

    unmount()

    expect(client.removeChannel).toHaveBeenCalledWith(channel)
  })

  it('keeps direct mode on the raw tunnel stream without Supabase', async () => {
    vi.mocked(getSupabaseBrowser).mockClear()
    const { result } = renderHook(() =>
      useUnderwaterBroadcast('default', 'direct'),
    )

    await waitFor(() => {
      expect(result.current.realtimeStatus).toBe('connected')
    })

    expect(result.current.frame).toBeNull()
    expect(getSupabaseBrowser).not.toHaveBeenCalled()
  })
})
