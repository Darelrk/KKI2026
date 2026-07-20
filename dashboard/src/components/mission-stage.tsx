import { useState } from 'react'

const missionStages = [
  { id: 'ready', label: 'Ready / Preparation' },
  { id: 'start', label: 'Start' },
  { id: 'navigation', label: 'Navigasi lintasan' },
  { id: 'surface', label: 'Surface imaging' },
  { id: 'underwater', label: 'Underwater imaging' },
  { id: 'docking', label: 'Docking' },
  { id: 'finish', label: 'Finish' },
] as const

type MissionStageId = (typeof missionStages)[number]['id']

export function MissionStage() {
  const [activeStage, setActiveStage] = useState<MissionStageId>('ready')
  const activeStageLabel = missionStages.find((stage) => stage.id === activeStage)?.label ?? 'Ready / Preparation'

  return (
    <section className="mission-stage" aria-labelledby="mission-stage-title">
      <div className="mission-stage__header">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Formalitas operasi</p>
            <h2 id="mission-stage-title">Mission stage</h2>
          </div>
          <span className="mockup-badge">MISSION MOCKUP</span>
        </div>
        <p>Kontrol lokal untuk pratinjau UI. Tidak terhubung ke Supabase atau autopilot.</p>
      </div>

      <div className="mission-stage__controls" role="group" aria-label="Mission mockup stages">
        {missionStages.map((stage) => (
          <button
            key={stage.id}
            type="button"
            aria-pressed={activeStage === stage.id}
            className={activeStage === stage.id ? 'mission-stage__button mission-stage__button--active' : 'mission-stage__button'}
            onClick={() => setActiveStage(stage.id)}
          >
            {stage.label}
          </button>
        ))}
      </div>

      <div className="mission-stage__readout" role="status">
        <span className="mission-stage__pulse" aria-hidden="true" />
        <span>Active stage</span>
        <strong>{activeStageLabel}</strong>
      </div>
    </section>
  )
}
