import { describe, expect, it } from 'vitest'
import fixture from './km.parity.json'
import { deltaE2000, ForwardModel, gamutMapLrgb, lrgbToOklab, rampFractions, type ModelTables } from './km'

const model = new ForwardModel(fixture.model as ModelTables, fixture.colorimetry)

// Sharma, Wu & Dalal (2005) CIEDE2000 test pairs (same data as backend/tests/data)
const SHARMA: [number[], number[], number][] = [
  [[50, 2.6772, -79.7751], [50, 0, -82.7485], 2.0425],
  [[50, 3.1571, -77.2803], [50, 0, -82.7485], 2.8615],
  [[50, 2.8361, -74.02], [50, 0, -82.7485], 3.4412],
  [[50, -1.3802, -84.2814], [50, 0, -82.7485], 1.0],
  [[50, -1.1848, -84.8006], [50, 0, -82.7485], 1.0],
  [[50, -0.9009, -85.5211], [50, 0, -82.7485], 1.0],
  [[50, 0, 0], [50, -1, 2], 2.3669],
  [[50, -1, 2], [50, 0, 0], 2.3669],
  [[50, 2.49, -0.001], [50, -2.49, 0.0009], 7.1792],
  [[50, 2.49, -0.001], [50, -2.49, 0.001], 7.1792],
  [[50, 2.49, -0.001], [50, -2.49, 0.0011], 7.2195],
  [[50, 2.49, -0.001], [50, -2.49, 0.0012], 7.2195],
  [[50, -0.001, 2.49], [50, 0.0009, -2.49], 4.8045],
  [[50, -0.001, 2.49], [50, 0.001, -2.49], 4.8045],
  [[50, -0.001, 2.49], [50, 0.0011, -2.49], 4.7461],
  [[50, 2.5, 0], [50, 0, -2.5], 4.3065],
  [[50, 2.5, 0], [73, 25, -18], 27.1492],
  [[50, 2.5, 0], [61, -5, 29], 22.8977],
  [[50, 2.5, 0], [56, -27, -3], 31.903],
  [[50, 2.5, 0], [58, 24, 15], 19.4535],
  [[50, 2.5, 0], [50, 3.1736, 0.5854], 1.0],
  [[50, 2.5, 0], [50, 3.2972, 0], 1.0],
  [[50, 2.5, 0], [50, 1.8634, 0.5757], 1.0],
  [[50, 2.5, 0], [50, 3.2592, 0.335], 1.0],
  [[60.2574, -34.0099, 36.2677], [60.4626, -34.1751, 39.4387], 1.2644],
  [[63.0109, -31.0961, -5.8663], [62.8187, -29.7946, -4.0864], 1.263],
  [[61.2901, 3.7196, -5.3901], [61.4292, 2.248, -4.962], 1.8731],
  [[35.0831, -44.1164, 3.7933], [35.0232, -40.0716, 1.5901], 1.8645],
  [[22.7233, 20.0904, -46.694], [23.0331, 14.973, -42.5619], 2.0373],
  [[36.4612, 47.858, 18.3852], [36.2715, 50.5065, 21.2231], 1.4146],
  [[90.8027, -2.0831, 1.441], [91.1528, -1.6435, 0.0447], 1.4441],
  [[90.9257, -0.5406, -0.9208], [88.6381, -0.8985, -0.7239], 1.5381],
  [[6.7747, -0.2908, -2.4247], [5.8714, -0.0985, -2.2286], 0.6377],
  [[2.0776, 0.0795, -1.135], [0.9033, -0.0636, -0.5514], 0.9082],
]

const close = (a: number[], b: number[], tol: number): void => {
  expect(a.length).toBe(b.length)
  a.forEach((x, i) => expect(Math.abs(x - b[i]!)).toBeLessThan(tol))
}

describe('forward model parity with the backend', () => {
  it('reproduces reflectance, Lab under D65/A/F11, swatch and dE for every case', () => {
    expect(fixture.cases.length).toBeGreaterThan(10)
    for (const c of fixture.cases) {
      const fr = c.fractions as Record<string, number>
      const R = model.reflectance(fr)
      close(R, c.reflectance, 1e-9)
      for (const ill of ['D65', 'A', 'F11'] as const) close(model.lab(R, ill), c.lab[ill], 1e-6)
      const p = model.predict(fr)
      expect(p.hex).toBe(c.hex)
      expect(p.outOfGamut).toBe(c.out_of_gamut)
      expect(Math.abs(deltaE2000(p.lab, fixture.target_lab) - c.de2000_to_target)).toBeLessThan(1e-6)
    }
  })

  it('gamut-maps exactly like the backend', () => {
    let mapped = 0
    for (const g of fixture.gamut_map) {
      const s = model.swatch(g.lab)
      expect(s.outOfGamut).toBe(g.out_of_gamut)
      expect(s.hex).toBe(g.hex)
      if (g.out_of_gamut) mapped++
    }
    expect(mapped).toBeGreaterThan(10)
  })

  it('builds the same tint ladder', () => {
    const r = fixture.ramp
    close(rampFractions(r.fractions.length, 'log', 0.02), r.fractions, 1e-12)
    const steps = model.ramp(r.paint_a, r.paint_b, r.fractions)
    expect(steps.map((s) => s.hex)).toEqual(r.hex)
    steps.forEach((s, i) => close(s.lab, r.lab[i]!, 1e-6))
  })
})

describe('colour maths', () => {
  it('dE2000 passes all 34 Sharma pairs, including the 180-degree tie', () => {
    for (const [a, b, de] of SHARMA) expect(Math.abs(deltaE2000(a, b) - de)).toBeLessThan(1e-4)
  })

  it('maps out-of-gamut linear RGB into gamut and leaves in-gamut colours alone', () => {
    expect(gamutMapLrgb([0.2, 0.4, 0.6])).toEqual([0.2, 0.4, 0.6])
    const m = gamutMapLrgb([-0.2, 0.3, 1.4])
    m.forEach((x) => expect(x).toBeGreaterThanOrEqual(0))
    m.forEach((x) => expect(x).toBeLessThanOrEqual(1))
    expect(Math.abs(lrgbToOklab(m)[0] - lrgbToOklab([-0.2, 0.3, 1.4])[0])).toBeLessThan(0.04)
  })

  it('rejects unknown paints and empty mixtures', () => {
    expect(() => model.reflectance({ nope: 1 })).toThrow(/not in the model/)
    expect(() => model.reflectance({ 'titanium-white': 0 })).toThrow(/positive sum/)
  })
})
