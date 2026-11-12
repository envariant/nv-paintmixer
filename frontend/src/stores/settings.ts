import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type Schemas, unwrap } from '../api/client'

/** As read from the API: the settable fields plus the fixed observer and geometry. */
export type AppSettings = Schemas['AppSettingsRead']

/** GET / PATCH /settings. */
export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<AppSettings | null>(null)
  const error = ref<string | null>(null)

  async function load(): Promise<AppSettings | null> {
    try {
      settings.value = unwrap(await api.GET('/api/v1/settings'))
      error.value = null
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    }
    return settings.value
  }

  async function save(patch: Schemas['AppSettingsUpdate']): Promise<AppSettings> {
    settings.value = unwrap(await api.PATCH('/api/v1/settings', { body: patch }))
    return settings.value
  }

  return { settings, error, load, save }
})
