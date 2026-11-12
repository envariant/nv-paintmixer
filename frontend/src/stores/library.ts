import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type Schemas, unwrap } from '../api/client'

export type Colour = Schemas['ColorRead']
export type Palette = Schemas['PaletteRead']
export type PaletteSummary = Schemas['PaletteSummary']

/** The colour library with cached match summaries, and the palettes. */
export const useLibraryStore = defineStore('library', () => {
  const colours = ref<Colour[]>([])
  const palettes = ref<Palette[]>([])
  const error = ref<string | null>(null)
  let timer: ReturnType<typeof setTimeout> | null = null

  const byId = computed(() => new Map(colours.value.map((c) => [c.id, c])))
  const pending = computed(() => colours.value.filter((c) => c.match == null).length)

  async function loadColours(): Promise<void> {
    try {
      colours.value = unwrap(await api.GET('/api/v1/colors', { params: { query: { with_match: true } } }))
      error.value = null
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    }
  }

  /** Reload while matches are still being computed (the backend fills them in the background). */
  async function follow(ms = 2000, maxRounds = 60): Promise<void> {
    stop()
    await loadColours()
    if (pending.value && maxRounds > 0) timer = setTimeout(() => void follow(ms, maxRounds - 1), ms)
  }
  function stop(): void {
    if (timer) clearTimeout(timer)
    timer = null
  }

  async function loadPalettes(): Promise<void> {
    palettes.value = unwrap(await api.GET('/api/v1/palettes'))
  }

  async function summary(id: number): Promise<PaletteSummary> {
    return unwrap(await api.GET('/api/v1/palettes/{palette_id}/summary', { params: { path: { palette_id: id } } }))
  }

  async function savePalette(id: number | null, name: string, colorIds: number[]): Promise<Palette> {
    const saved = id
      ? unwrap(await api.PATCH('/api/v1/palettes/{palette_id}', { params: { path: { palette_id: id } }, body: { name, color_ids: colorIds } }))
      : unwrap(await api.POST('/api/v1/palettes', { body: { name, color_ids: colorIds } }))
    await loadPalettes()
    return saved
  }

  return { colours, palettes, error, byId, pending, loadColours, follow, stop, loadPalettes, summary, savePalette }
})
