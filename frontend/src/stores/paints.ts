import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type Schemas, unwrap } from '../api/client'

export type Paint = Schemas['PaintRead']

/** Warnings for the set of loaded paints (minimum full-range set is W, K + 3 chromatics). */
export function loadedSetWarnings(paints: Paint[]): string[] {
  const loaded = paints.filter((p) => p.loaded && p.active !== false)
  const out: string[] = []
  if (!loaded.some((p) => p.role === 'white')) out.push('No white loaded: pale colours are unreachable.')
  if (!loaded.some((p) => p.role === 'black')) out.push('No black loaded: deep darks and clean neutrals are limited.')
  if (loaded.filter((p) => p.role === 'chromatic').length < 3)
    out.push('Fewer than 3 chromatic paints loaded: the hue range is limited.')
  return out
}

export const usePaintsStore = defineStore('paints', () => {
  const items = ref<Paint[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const loaded = computed(() => items.value.filter((p) => p.loaded))
  const warnings = computed(() => loadedSetWarnings(items.value))

  async function fetchAll(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      items.value = unwrap(await api.GET('/api/v1/paints'))
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  }

  async function create(body: Schemas['PaintCreate']): Promise<Paint> {
    const p = unwrap(await api.POST('/api/v1/paints', { body }))
    items.value = [...items.value, p].sort((a, b) => a.id.localeCompare(b.id))
    return p
  }

  async function update(id: string, body: Schemas['PaintUpdate']): Promise<Paint> {
    const p = unwrap(await api.PATCH('/api/v1/paints/{paint_id}', { params: { path: { paint_id: id } }, body }))
    items.value = items.value.map((x) => (x.id === id ? p : x))
    return p
  }

  async function remove(id: string): Promise<void> {
    unwrap(await api.DELETE('/api/v1/paints/{paint_id}', { params: { path: { paint_id: id } } }))
    items.value = items.value.filter((x) => x.id !== id)
  }

  return { items, loading, error, loaded, warnings, fetchAll, create, update, remove }
})
