import { describe, expect, it } from 'vitest'

import { controlModeResponseSchema, controlModeSchema } from './control-mode'

const validModes = ['MANUAL', 'AUTONOMOUS'] as const

const invalidModes = ['manual', 'autonomous', 'UNKNOWN']

describe('control mode schemas', () => {
  it.each(validModes)('accepts the exact %s control mode', (mode) => {
    expect(controlModeSchema.parse(mode)).toBe(mode)
  })

  it('accepts the control mode response shape', () => {
    expect(controlModeResponseSchema.parse({ mode: 'MANUAL' })).toEqual({
      mode: 'MANUAL',
    })
  })

  it.each(invalidModes)('rejects invalid mode %s', (mode) => {
    expect(controlModeSchema.safeParse(mode).success).toBe(false)
  })

  it('rejects extra response fields', () => {
    expect(
      controlModeResponseSchema.safeParse({ mode: 'AUTONOMOUS', extra: true })
        .success,
    ).toBe(false)
  })
})
