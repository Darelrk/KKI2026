import { Radio, WarningCircle } from '@phosphor-icons/react'

export type ConnectionStatus = 'fixture' | 'connecting' | 'connected' | 'error'

type ConnectionBarProps = {
  asvId: string
  online: boolean
  status: ConnectionStatus
}

const statusCopy: Record<ConnectionStatus, string> = {
  fixture: 'Fixture data',
  connecting: 'Connecting',
  connected: 'Live realtime',
  error: 'Realtime delayed',
}

export function ConnectionBar({ asvId, online, status }: ConnectionBarProps) {
  const isProblem = !online || status === 'error'

  return (
    <section className="connection-bar" aria-label="ASV connection status">
      <div className="connection-bar__identity">
        {isProblem ? <WarningCircle weight="fill" /> : <Radio weight="fill" />}
        <span>ASV / {asvId}</span>
      </div>
      <div className="connection-bar__signals">
        <span className={online ? 'status-chip status-chip--online' : 'status-chip status-chip--offline'}>
          {online ? 'ASV online' : 'ASV offline'}
        </span>
        <span className={`status-chip status-chip--${status}`}>{statusCopy[status]}</span>
      </div>
    </section>
  )
}
