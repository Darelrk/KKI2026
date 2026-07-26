import { Flag } from '@phosphor-icons/react'

import { formatMissionTime, missionStages } from '../lib/mission-simulation'
import { kolamDeliSite } from '../lib/mission-site'

import type { MissionSimulationController } from '../lib/use-mission-simulation'

type MissionStageProps = {
  simulation: MissionSimulationController
}

export function MissionStage({ simulation }: MissionStageProps) {
  const currentStage = missionStages[simulation.stageIndex]
  const statusCopy = {
    idle: 'Standby',
    running: 'Mission route active',
    paused: 'Mission route paused',
    complete: 'Mission complete',
  }[simulation.status]

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
        <div className="mission-stage__demo-badge">
          <strong>ASV MISSION CONTROL</strong>
          <span>{kolamDeliSite.name.toUpperCase()} · LINTASAN A</span>
        </div>
      </div>

      <div className="mission-stage__summary">
        <div>
          <span className="mission-stage__label">Mission phase</span>
          <strong>{currentStage.label}</strong>
          <small>{statusCopy}</small>
        </div>
        <div>
          <span className="mission-stage__label">Mission timer</span>
          <strong>{formatMissionTime(simulation.elapsedMs)}</strong>
        </div>
      </div>

      <div className="mission-stage__controls" aria-label="Mission controls">
        <button
          type="button"
          onClick={simulation.start}
          disabled={simulation.status === 'running'}
        >
          Start mission
        </button>
        <button
          type="button"
          onClick={simulation.pause}
          disabled={simulation.status !== 'running'}
        >
          Pause mission
        </button>
        <button
          type="button"
          onClick={simulation.stop}
          disabled={simulation.status === 'idle'}
        >
          Stop mission
        </button>
        <button type="button" onClick={simulation.reset}>
          Reset mission
        </button>
      </div>

      <ol className="mission-stage__timeline">
        {missionStages.map((stage, index) => (
          <li key={stage.id} className="mission-stage__item">
            <button
              type="button"
              className={`mission-stage__step-button${
                index === simulation.stageIndex
                  ? ' mission-stage__step-button--current'
                  : simulation.progress > stage.routeProgress &&
                      index !== simulation.stageIndex
                    ? ' mission-stage__step-button--complete'
                    : ''
              }`}
              onClick={() => simulation.selectStage(index)}
              aria-pressed={index === simulation.stageIndex}
              aria-label={`Jump to ${stage.label}`}
            >
              <span className="mission-stage__step">
                {String(index + 1).padStart(2, '0')}
              </span>
              <span>
                <strong>{stage.label}</strong>
                <span>{stage.detail}</span>
              </span>
            </button>
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
        <strong>{statusCopy}</strong>
      </div>
    </section>
  )
}
