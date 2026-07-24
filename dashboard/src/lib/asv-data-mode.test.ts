import { describe, expect, it } from 'vitest'

import { getAsvDataMode } from './asv-data-mode'

describe('getAsvDataMode', () => {
  it('accepts the explicit fixture mode', () => {
    expect(getAsvDataMode('fixture')).toBe('fixture')
  })
  it('accepts the direct tunnel mode', () => {
    expect(getAsvDataMode('direct')).toBe('direct')
  })

  it('defaults to direct when mode is undefined, null, empty, or supabase', () => {
    expect(getAsvDataMode(undefined)).toBe('direct')
    expect(getAsvDataMode(null)).toBe('direct')
    expect(getAsvDataMode('')).toBe('direct')
    expect(getAsvDataMode('supabase')).toBe('direct')
    expect(getAsvDataMode('unrecognised')).toBe('direct')
  })
})
