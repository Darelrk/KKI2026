import { asvTelemetrySchema } from './asv-telemetry'
import {
  controlModeResponseSchema,
  type ControlMode,
} from './control-mode'
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

export async function fetchControlMode(
  baseUrl: string,
  signal?: AbortSignal,
): Promise<ControlMode> {
  const response = controlModeResponseSchema.parse(
    await fetchJson(baseUrl, '/api/control/mode', signal),
  )
  return response.mode
}

export async function putControlMode(
  baseUrl: string,
  mode: ControlMode,
  signal?: AbortSignal,
): Promise<ControlMode> {
  const response = await fetch(
    `${baseUrl.replace(/\/+$/, '')}/api/control/mode`,
    {
      method: 'PUT',
      headers: {
        accept: 'application/json',
        'content-type': 'application/json',
      },
      cache: 'no-store',
      body: JSON.stringify({ mode }),
      signal,
    },
  )

  if (!response.ok) {
    throw new Error(`Direct bridge mode request failed: ${response.status}`)
  }

  return controlModeResponseSchema.parse(await response.json()).mode
}
