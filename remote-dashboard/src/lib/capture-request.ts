export type CaptureResponse = { dashboards: number }

export function buildCaptureRequestUrl(backendOrigin: string): string {
  return new URL('/api/capture/request', backendOrigin).toString()
}

export async function requestDashboardCapture(
  backendOrigin: string,
  fetchImpl: typeof fetch = fetch,
): Promise<CaptureResponse> {
  const response = await fetchImpl(buildCaptureRequestUrl(backendOrigin), {
    method: 'POST',
    headers: { Accept: 'application/json' },
  })

  if (!response.ok) {
    throw new Error(`capture request failed: ${response.status}`)
  }

  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new Error(`capture request failed: ${response.status}`)
  }

  if (
    typeof payload !== 'object'
    || payload === null
    || !('ok' in payload)
    || payload.ok !== true
    || !('dashboards' in payload)
    || typeof payload.dashboards !== 'number'
    || !Number.isInteger(payload.dashboards)
    || payload.dashboards < 0
  ) {
    throw new Error(`capture request failed: ${response.status}`)
  }

  return { dashboards: payload.dashboards }
}
