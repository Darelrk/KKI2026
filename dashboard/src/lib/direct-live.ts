import { asvTelemetrySchema } from './asv-telemetry'
import { asvLiveSchema } from './asv-types'

import type { AsvLive } from './asv-types'
import type { AsvTelemetry } from './asv-telemetry'


async function fetchJson(baseUrl: string, path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(`${baseUrl.replace(/\/+$/, '')}${path}`, {
    headers: { accept: 'application/json' },
    cache: 'no-store',
    signal,
  })

  if (!response.ok) {
    throw new Error(`Direct bridge request failed: ${response.status}`)
  }

  return response.json()
}

export async function fetchDirectAsvLive(
  baseUrl: string,
  asvId: string,
  signal?: AbortSignal,
): Promise<AsvLive> {
  const status = asvLiveSchema.parse(await fetchJson(baseUrl, '/api/status', signal))
  if (status.id !== asvId) {
    throw new Error(`Direct bridge returned ASV ${status.id}, expected ${asvId}`)
  }
  return status
}

export async function fetchDirectTelemetry(
  baseUrl: string,
  signal?: AbortSignal,
): Promise<AsvTelemetry> {
  return asvTelemetrySchema.parse(await fetchJson(baseUrl, '/api/telemetry', signal))
}
