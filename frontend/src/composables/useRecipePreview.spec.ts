import { afterEach, describe, expect, it, vi } from 'vitest'
import { ref, shallowRef } from 'vue'
import fixture from '../lib/km.parity.json'
import type { ForwardModel } from '../lib/km'
import { mockFetch } from '../test/mockFetch'
import { loadForwardModel, useRecipePreview } from './useRecipePreview'

const spectra = {
  version: 3,
  k1: fixture.model.k1,
  k2: fixture.model.k2,
  reference_version: null,
  wavelengths: fixture.colorimetry.wavelengths,
  tau: [],
  substrate_white: [],
  substrate_black: [],
  paints: fixture.model.paint_ids.map((id, i) => ({
    paint_id: id,
    name: id,
    K: fixture.model.K[i],
    S: fixture.model.S[i],
    ks: [],
    masstone: [],
    masstone_hex: '#000000',
  })),
}

afterEach(() => vi.unstubAllGlobals())

describe('useRecipePreview', () => {
  it('loads the model from the API and previews recipes locally', async () => {
    const { calls } = mockFetch({
      'GET /api/v1/models/3/spectra': { json: spectra },
      'GET /api/v1/colorimetry': { json: fixture.colorimetry },
    })
    const m = shallowRef<ForwardModel | null>(await loadForwardModel(3))
    expect(calls.map((c) => c.path).sort()).toEqual(['/api/v1/colorimetry', '/api/v1/models/3/spectra'])
    const c = fixture.cases[7]!
    const fractions = ref<Record<string, number>>({ ...(c.fractions as Record<string, number>) })
    const target = ref<number[] | null>(fixture.target_lab)
    const { prediction, deltaE, error } = useRecipePreview(m, fractions, target)
    expect(error.value).toBeNull()
    expect(prediction.value?.hex).toBe(c.hex)
    expect(Math.abs(deltaE.value! - c.de2000_to_target)).toBeLessThan(1e-6)
    // editing the recipe updates the preview without any further request
    const n = calls.length
    fractions.value = { 'titanium-white': 1 }
    expect(prediction.value?.lab[0]).toBeGreaterThan(90)
    expect(calls.length).toBe(n)
    fractions.value = { 'titanium-white': 0 }
    expect(prediction.value).toBeNull()
    expect(error.value).toMatch(/at least one paint/)
    fractions.value = { 'unknown-paint': 1 }
    expect(error.value).toMatch(/not in the model/)
  })

  it('is empty until a model is loaded', () => {
    const { prediction, deltaE, error } = useRecipePreview(shallowRef<ForwardModel | null>(null), ref({ a: 1 }))
    expect(prediction.value).toBeNull()
    expect(deltaE.value).toBeNull()
    expect(error.value).toBeNull()
  })
})
