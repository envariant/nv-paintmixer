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

describe('formatDate', () => {
  it('always shows the year', async () => {
    const { formatDate } = await import('./format')
    expect(formatDate('2026-11-02T10:00:00Z')).toBe('2 Nov 2026')
    expect(formatDate('2026-09-18T10:00:00Z')).toBe('18 Sep 2026')
  })
})
