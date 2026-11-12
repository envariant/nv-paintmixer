import { describe, expect, it } from 'vitest'
import { seriesFromApi } from '../stores/illuminants'
import {
  calibrationGrade,
  colourMeta,
  fmt,
  formatMoney,
  ILLUMINANT,
  isHex,
  lab,
  labToCss,
  labToHex,
  nearestInSeries,
  normaliseHex,
  parseLab,
  SERIES,
  seriesRange,
  tierOf,
  TIER_LABEL,
} from './colour'
import parity from './km.parity.json'

describe('match tiers and calibration grades', () => {
  it('words matches by perceptual tier (design: 1 / 2 / 5)', () => {
    expect([0.3, 1, 1.9, 2, 4.9, 5].map((d) => TIER_LABEL[tierOf(d)])).toEqual([
      'Indistinguishable',
      'Barely visible',
      'Barely visible',
      'Visible difference',
      'Visible difference',
      'Mismatch',
    ])
  })
  it('grades calibration like the backend (0.4 / 1 / 2)', () => {
    expect([0.39, 0.4, 0.99, 1, 1.99, 2].map(calibrationGrade)).toEqual([
      'Excellent',
      'Good',
      'Good',
      'Fair',
      'Fair',
      'Poor',
    ])
  })
})

describe('formatting', () => {
  it('uses U+2212 minus and never prints a negative zero', () => {
    expect(fmt(-9.62, 1)).toBe('−9.6')
    expect(fmt(0.634)).toBe('0.63')
    expect(fmt(2.7, 1, true)).toBe('+2.7')
    expect(fmt(-0.04, 1)).toBe('0.0')
  })
  it('captions a colour as hex · L a b (· pigment)', () => {
    const m = colourMeta(lab([34.2, -27.0, 3.8]), 'PG7')
    expect(m.text).toMatch(/^#[0-9A-F]{6} · 34\.2 −27\.0 3\.8 · PG7$/)
    expect(m.title).toContain('a* −27.0')
  })
  it('formats money as the design shows it', () => {
    expect(formatMoney(12.765)).toBe('SGD 12.77')
    expect(formatMoney(1.5, 'EUR')).toBe('EUR 1.50')
  })
})

describe('Lab → screen matches the backend', () => {
  it('reproduces every backend swatch hex, gamut mapping included', () => {
    const cases = [
      ...parity.gamut_map.map((g) => ({ lab: g.lab, hex: g.hex, oog: g.out_of_gamut })),
      ...parity.ramp.lab.map((l, i) => ({ lab: l, hex: parity.ramp.hex[i]!, oog: undefined })),
    ]
    expect(cases.length).toBeGreaterThan(5)
    expect(parity.gamut_map.some((g) => g.out_of_gamut)).toBe(true)
    for (const c of cases) {
      expect(labToHex(lab(c.lab))).toBe(c.hex.toUpperCase())
      if (c.oog !== undefined) expect(labToCss(lab(c.lab)).clipped).toBe(c.oog)
    }
  })
  it('renders css rgb()', () => {
    expect(labToCss(lab([100, 0, 0]))).toEqual({ css: 'rgb(255 255 255)', clipped: false })
  })
})

describe('illuminants', () => {
  it('ships the same catalogue as GET /illuminants', () => {
    expect(seriesFromApi(parity.illuminants as never)).toEqual(SERIES)
  })
  it('keeps the closest temperature when switching series', () => {
    const led = SERIES.find((s) => s.id === 'LED')!
    expect(nearestInSeries(led, 'D50')).toBe('LED-B4')
    expect(seriesRange(SERIES[0]!)).toBe('5003–9300 K')
    expect(ILLUMINANT['F11']!.series.id).toBe('F')
  })
})

describe('input helpers', () => {
  it('parses hex and Lab', () => {
    expect(isHex('#abc') && isHex('a1b2c3') && !isHex('#ab')).toBe(true)
    expect(normaliseHex('ABC')).toBe('#aabbcc')
    expect(parseLab('60, -10 15')).toEqual([60, -10, 15])
    expect(parseLab('120 0 0')).toBeNull()
  })
})
