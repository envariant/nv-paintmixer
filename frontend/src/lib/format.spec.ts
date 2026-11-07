import { describe, expect, it } from 'vitest'
import { formatDeltaE } from './format'

describe('formatDeltaE', () => {
  it('uses two decimals below 10', () => {
    expect(formatDeltaE(0.456)).toBe('0.46')
  })
  it('uses one decimal from 10', () => {
    expect(formatDeltaE(12.34)).toBe('12.3')
  })
})
