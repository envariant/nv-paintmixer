import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type Schemas, unwrap } from '../api/client'

export type ModelDetail = Schemas['ModelDetail']
export type GamutSlice = Schemas['GamutSliceOut']

/** The active model (its paints bound Max paints) and its gamut slices (Reach chart). */
export const useModelStore = defineStore('model', () => {
  const active = ref<ModelDetail | null>(null)
  const gamut = ref<{ version: number; slices: GamutSlice[] } | null>(null)
  const error = ref<string | null>(null)

  async function loadActive(): Promise<ModelDetail | null> {
    try {
      active.value = unwrap(await api.GET('/api/v1/models/active'))
      error.value = null
    } catch (e) {
      active.value = null
      error.value = e instanceof Error ? e.message : String(e)
    }
    return active.value
  }

  /** a*b* outline of the gamut slice nearest ``L``, for the Reach chart. */
  async function outlineAt(version: number, L: number): Promise<[number, number][]> {
    if (gamut.value?.version !== version) {
      const g = unwrap(
        await api.GET('/api/v1/models/{ref}/gamut', { params: { path: { ref: String(version) } } }),
      )
      gamut.value = { version, slices: g.slices }
    }
    const slices = gamut.value.slices
    if (!slices.length) return []
    const s = slices.reduce((best, x) => (Math.abs(x.L - L) < Math.abs(best.L - L) ? x : best))
    return s.a.map((a, i) => [a, s.b[i]!] as [number, number]).filter((_p, i) => s.chroma[i]! > 0)
  }

  return { active, gamut, error, loadActive, outlineAt }
})
