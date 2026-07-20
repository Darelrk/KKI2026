import { CheckCircle, WarningCircle } from '@phosphor-icons/react'

import type { AsvLive } from '../lib/asv-types'

type SignalRailProps = {
  live: AsvLive | null
}


export function SignalRail({ live }: SignalRailProps) {
  const modelStatus = live?.model_status ?? 'offline'
  const isRunning = live?.online && modelStatus === 'running'

  return (
    <aside className="signal-rail" aria-label="Operational signal summary">
      <div className="signal-rail__status">
        {isRunning ? <CheckCircle weight="fill" /> : <WarningCircle weight="fill" />}
        <div>
          <p className="eyebrow">Autonomy model</p>
          <strong>MODEL {modelStatus.toUpperCase()}</strong>
        </div>
      </div>

      <dl className="signal-list">
        <div>
          <dt>Camera selected</dt>
          <dd>{live?.camera ?? 'Unavailable'}</dd>
        </div>
        <div>
          <dt>Run ID</dt>
          <dd>{live?.run_id ?? 'Awaiting run'}</dd>
        </div>
        <div>
          <dt>Last update</dt>
          <dd>
            {live
              ? live.updated_at.replace('T', ' ').replace(/\.\d+Z$/, ' UTC')
              : 'Awaiting status'}
          </dd>
        </div>
        <div>
          <dt>Navigation feed</dt>
          <dd>Not connected</dd>
        </div>
      </dl>
    </aside>
  )
}
