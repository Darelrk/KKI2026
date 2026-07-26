import { Flag } from '@phosphor-icons/react'

const missionStages = [
  { id: 'ready', label: 'Ready / Preparation', detail: 'Preflight checks' },
  { id: 'start', label: 'Start', detail: 'Departure dock' },
  { id: 'navigation', label: 'Navigation', detail: '10 buoy pairs' },
  { id: 'surface', label: 'Surface imaging', detail: 'Green mission zone' },
  { id: 'underwater', label: 'Underwater imaging', detail: 'Blue mission zone' },
  { id: 'docking', label: 'Docking', detail: '3 blue docking balls' },
  { id: 'finish', label: 'Finish', detail: 'Run complete' },
] as const

export function MissionStage() {
  return (
    <section className="mission-stage" aria-labelledby="mission-stage-title">
      <div className="mission-stage__header">
        <div className="panel-heading">
          <Flag aria-hidden="true" />
          <div>
            <p className="eyebrow">Operational phase</p>
            <h2 id="mission-stage-title">Mission sequence</h2>
          </div>
        </div>
      </div>

      <div className="mission-stage__summary">
        <div>
          <span className="mission-stage__label">Current phase</span>
          <strong>Ready / Preparation</strong>
          <small>Autonomous sequence available</small>
        </div>
        <div>
          <span className="mission-stage__label">Run timer</span>
          <strong>--:--</strong>
          <small>Awaiting start event</small>
        </div>
      </div>

      <ol className="mission-stage__timeline">
        {missionStages.map((stage, index) => (
          <li
            key={stage.id}
            className={index === 0 ? 'mission-stage__item mission-stage__item--current' : 'mission-stage__item'}
          >
            <span className="mission-stage__step">{String(index + 1).padStart(2, '0')}</span>
            <div>
              <strong>{stage.label}</strong>
              <span>{stage.detail}</span>
            </div>
          </li>
        ))}
      </ol>

      <div className="mission-stage__targets" aria-label="Mission targets">
        <div>
          <span>Route</span>
          <strong>10 pairs</strong>
        </div>
        <div>
          <span>Imaging</span>
          <strong>Surface + underwater</strong>
        </div>
        <div>
          <span>Docking</span>
          <strong>3 balls</strong>
        </div>
      </div>

      <div className="mission-stage__readout" role="status">
        <span className="mission-stage__pulse" aria-hidden="true" />
        <span>Operational state</span>
        <strong>Standby</strong>
      </div>
    </section>
  )
}
