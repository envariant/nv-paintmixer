import { describe, expect, it } from 'vitest'
import { deltaEBadge, formatMoney, isHex, normaliseHex, parseLab } from './colour'

describe('colour helpers', () => {
  it('tiers dE with text labels and icons', () => {
    expect(deltaEBadge(0.4)).toMatchObject({ tier: 'excellent', icon: 'check-double' })
    expect(deltaEBadge(1.5).label).toBe('Good match')
    expect(deltaEBadge(3).tier).toBe('fair')
    expect(deltaEBadge(9).icon).toBe('cross')
  })
  it('handles hex and Lab input', () => {
    expect(isHex('#AbC')).toBe(true)
    expect(isHex('12345')).toBe(false)
    expect(normaliseHex('AbC')).toBe('#aabbcc')
    expect(() => normaliseHex('zz')).toThrow()
    expect(parseLab('50 -10 20')).toEqual([50, -10, 20])
    expect(parseLab('a b c')).toBeNull()
  })
  it('formats SGD', () => {
    expect(formatMoney(1.5)).toMatch(/1\.50/)
  })
})
