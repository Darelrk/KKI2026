import { describe, expect, it, vi } from 'vitest'
import {
  buildCaptureRequestUrl,
  requestDashboardCapture,
} from '../src/lib/capture-request'

const BACKEND_ORIGIN = 'https://remote.example.test'

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

describe('capture request', () => {
  it('builds the capture endpoint URL from the backend origin', () => {
    expect(buildCaptureRequestUrl(`${BACKEND_ORIGIN}/api`)).toBe(
      `${BACKEND_ORIGIN}/api/capture/request`,
    )
  })

  it('sends a bodyless POST with the JSON accept header', async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      response({ ok: true, dashboards: 2 }),
    )

    await expect(requestDashboardCapture(BACKEND_ORIGIN, fetchImpl)).resolves.toEqual({
      dashboards: 2,
    })

    expect(fetchImpl).toHaveBeenCalledTimes(1)
    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe(`${BACKEND_ORIGIN}/api/capture/request`)
    expect(init).toMatchObject({
      method: 'POST',
      headers: { Accept: 'application/json' },
    })
    expect(init?.body).toBeUndefined()
  })

  it('returns zero when no dashboard listeners are connected', async () => {
    const fetchImpl = vi.fn(async () => response({ ok: true, dashboards: 0 }))

    await expect(requestDashboardCapture(BACKEND_ORIGIN, fetchImpl)).resolves.toEqual({
      dashboards: 0,
    })
  })

  it('throws with the status code for a non-success response', async () => {
    const fetchImpl = vi.fn(async () => response({ ok: true, dashboards: 2 }, 503))

    await expect(requestDashboardCapture(BACKEND_ORIGIN, fetchImpl)).rejects.toThrow(/503/)
  })

  it('throws with the status code when the response marks itself invalid', async () => {
    const fetchImpl = vi.fn(async () => response({ ok: false, dashboards: 2 }))

    await expect(requestDashboardCapture(BACKEND_ORIGIN, fetchImpl)).rejects.toThrow(/200/)
  })

  it.each([
    ['a non-integer', 1.5],
    ['a negative integer', -1],
  ])('throws with the status code for %s dashboards', async (_description, dashboards) => {
    const fetchImpl = vi.fn(async () => response({ ok: true, dashboards }))

    await expect(requestDashboardCapture(BACKEND_ORIGIN, fetchImpl)).rejects.toThrow(/200/)
  })
})
