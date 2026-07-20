import { describe, expect, it } from 'vitest'

import { getAsvDataMode } from './asv-data-mode'

describe('getAsvDataMode', () => {
  it('accepts the explicit fixture mode', () => {
    expect(getAsvDataMode('fixture')).toBe('fixture')
  })

  it('rejects an unrecognised mode', () => {
    expect(() => getAsvDataMode('demo')).toThrow()
  })
})
