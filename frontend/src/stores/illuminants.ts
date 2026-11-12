import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type Schemas, unwrap } from '../api/client'
import { indexIlluminants, nearestInSeries as nearest, SERIES, type IlluminantSeries } from '../lib/colour'

/** GET /illuminants rows in the shape the UI components use (the handoff's IlluminantSeries). */
export function seriesFromApi(rows: Schemas['IlluminantSeriesOut'][]): IlluminantSeries[] {
  return rows.map((s) => ({
    id: s.id,
    name: s.name,
    desc: s.description,
    default: s.default,
    members: s.members.map((m) => ({ code: m.code, cct: m.cct })),
  }))
}

/**
 * The illuminant catalogue for LightTabs / IlluminantMenu, loaded from the API. Until it loads (or
 * if it cannot), the built-in catalogue is used: the same data, kept in sync by the parity fixture.
 */
export const useIlluminantsStore = defineStore('illuminants', () => {
  const series = ref<IlluminantSeries[]>(SERIES)
  const loaded = ref(false)
  const error = ref<string | null>(null)
  const byCode = computed(() => indexIlluminants(series.value))

  async function load(): Promise<void> {
    try {
      series.value = seriesFromApi(unwrap(await api.GET('/api/v1/illuminants')))
      loaded.value = true
      error.value = null
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    }
  }

  /** Switching to series ``seriesId`` keeps the member closest in temperature to ``current``. */
  function nearestInSeries(seriesId: string, current: string): string {
    const s = series.value.find((x) => x.id === seriesId)
    return s ? nearest(s, current, byCode.value) : current
  }

  return { series, loaded, error, byCode, load, nearestInSeries }
})
