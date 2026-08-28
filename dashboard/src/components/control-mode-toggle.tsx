import type { ControlMode } from '../lib/control-mode'

type ControlModeToggleProps = {
  mode: ControlMode | null
  canEdit: boolean
  isUpdating: boolean
  updateError: Error | null
  onChange: (mode: ControlMode) => void
}

const controlModes: ControlMode[] = ['MANUAL', 'AUTONOMOUS']

export function ControlModeToggle({
  mode,
  canEdit,
  isUpdating,
  updateError,
  onChange,
}: ControlModeToggleProps) {
  const disabled = !canEdit || isUpdating

  const handleChange = (nextMode: ControlMode) => {
    if (disabled || mode === null || mode === nextMode) return
    onChange(nextMode)
  }

  return (
    <section
      className="control-mode-toggle"
      aria-label="Runtime control mode"
    >
      <p className="eyebrow">CONTROL MODE</p>
      <div
        className="control-mode-toggle__choices"
        role="group"
        aria-label="Runtime control mode"
        aria-disabled={disabled}
      >
        {controlModes.map((controlMode) => (
          <button
            key={controlMode}
            type="button"
            className="control-mode-toggle__button"
            aria-pressed={mode === controlMode}
            disabled={disabled}
            onClick={() => handleChange(controlMode)}
          >
            {controlMode}
          </button>
        ))}
      </div>
      {isUpdating ? (
        <p className="control-mode-toggle__status" role="status">
          Updating control mode…
        </p>
      ) : null}
      {updateError ? (
        <p className="control-mode-toggle__error" role="alert">
          {updateError.message}
        </p>
      ) : null}
      {!canEdit && !isUpdating ? (
        <p className="control-mode-toggle__note" role="note">
          Fixture mode is read-only.
        </p>
      ) : null}
    </section>
  )
}
