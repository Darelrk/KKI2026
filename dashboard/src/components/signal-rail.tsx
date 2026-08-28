import { CheckCircle, WarningCircle } from '@phosphor-icons/react'

import { ControlModeToggle } from './control-mode-toggle'
import { formatSiteTime } from '../lib/format-site-time'

import type { AsvLive } from '../lib/asv-types'
import type { ControlMode } from '../lib/control-mode'
import type { ConnectionStatus } from './connection-bar'

type SignalRailProps = {
  live: AsvLive | null
  telemetryConnected: boolean | null
  telemetryStatus: ConnectionStatus
  controlMode?: ControlMode | null
  controlModeCanEdit?: boolean
  controlModeUpdating?: boolean
  controlModeError?: Error | null
  onControlModeChange?: (mode: ControlMode) => void
}

export function SignalRail({
  live,
  telemetryConnected,
  telemetryStatus,
  controlMode = null,
  controlModeCanEdit = false,
  controlModeUpdating = false,
  controlModeError = null,
  onControlModeChange = () => undefined,
}: SignalRailProps) {
  const modelStatus = live?.model_status ?? 'offline'
  const isRunning = live?.online && modelStatus === 'running'
  const telemetryStatusCopy = {
    fixture: 'Connected',
    connecting: 'Connecting',
    connected: 'Connected',
    error: 'Error',
  } satisfies Record<ConnectionStatus, string>

  return (
    <aside className="signal-rail" aria-label="Operational signal summary">
      <div className="signal-rail__status">
        {isRunning ? (
          <CheckCircle weight="fill" />
        ) : (
          <WarningCircle weight="fill" />
        )}
        <div>
          <p className="eyebrow">MODEL MONITORING</p>
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
          <dd>{live ? formatSiteTime(live.updated_at) : 'Awaiting status'}</dd>
        </div>
        {telemetryConnected ? (
          <div>
            <dt>Navigation feed</dt>
            <dd>Pixhawk connected</dd>
          </div>
        ) : null}
        <div>
          <dt>Autonomy target</dt>
          <dd>{controlMode ?? 'Unavailable'}</dd>
        </div>
        {telemetryConnected ? (
          <div>
            <dt>Telemetry channel</dt>
            <dd>{telemetryStatusCopy[telemetryStatus]}</dd>
          </div>
        ) : null}
      </dl>

      <ControlModeToggle
        mode={controlMode}
        canEdit={controlModeCanEdit}
        isUpdating={controlModeUpdating}
        updateError={controlModeError}
        onChange={onControlModeChange}
      />
    </aside>
  )
}
