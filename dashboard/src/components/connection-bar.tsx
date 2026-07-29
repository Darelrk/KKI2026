export type ConnectionStatus = 'fixture' | 'connecting' | 'connected' | 'error'

type ConnectionBarProps = {
  online: boolean
  status: ConnectionStatus | null
}

const statusCopy: Record<ConnectionStatus, string> = {
  fixture: 'On-site test',
  connecting: 'Connecting',
  connected: 'Live realtime',
  error: 'Realtime delayed',
}

export function ConnectionBar({ online, status }: ConnectionBarProps) {
  return (
    <section className="connection-bar" aria-label="ASV connection status">
      <div className="connection-bar__brand">
        <div className="connection-bar__logos" aria-label="Institution partners">
          <img
            src="/ditjen-dikti.svg"
            alt="Direktorat Jenderal Pendidikan Tinggi"
            className="connection-bar__logo"
          />
          <img
            src="/berdampak.png"
            alt="Diktisaintek Berdampak"
            className="connection-bar__logo"
          />
          <img
            src="/umsu.png"
            alt="Universitas Muhammadiyah Sumatera Utara"
            className="connection-bar__logo connection-bar__logo--umsu"
          />
        </div>
        <span className="connection-bar__brand-divider" aria-hidden="true" />
        <div className="connection-bar__identity">
          <img
            src="/trifusion.svg"
            alt="TRIFUSION"
            className="connection-bar__team-logo"
          />
        </div>
      </div>
      <div className="connection-bar__signals">
        <span
          className={
            online
              ? 'status-chip status-chip--online'
              : 'status-chip status-chip--offline'
          }
        >
          {online ? 'ASV online' : 'ASV offline'}
        </span>
        {status ? (
          <span className={`status-chip status-chip--${status}`}>
            {statusCopy[status]}
          </span>
        ) : null}
      </div>
    </section>
  )
}
