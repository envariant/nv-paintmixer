import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type Schemas, unwrap } from '../api/client'

export type PaintAccuracy = Schemas['PaintAccuracyOut']
export type FitRun = Schemas['FitRunRead']

/** The Models screen: per-paint accuracy of the chosen model, readings and the latest fit. */
export const useRackStore = defineStore('rack', () => {
  const accuracy = ref<PaintAccuracy[]>([])
  const masstones = ref<Record<string, string>>({}) // paint id -> masstone hex in the viewed model
  const readings = ref<number | null>(null)
  const lastRun = ref<FitRun | null>(null)
  const error = ref<string | null>(null)

  async function loadAccuracy(ref_: string): Promise<void> {
    try {
      accuracy.value = unwrap(
        await api.GET('/api/v1/models/{ref}/paint-accuracy', { params: { path: { ref: ref_ } } }),
      )
      error.value = null
    } catch (e) {
      accuracy.value = []
      error.value = e instanceof Error ? e.message : String(e)
    }
  }

  /** Each paint's masstone as the viewed model predicts it (PaintRead.model_hex is the active model's). */
  async function loadMasstones(ref_: string): Promise<void> {
    try {
      const s = unwrap(await api.GET('/api/v1/models/{ref}/spectra', { params: { path: { ref: ref_ } } }))
      masstones.value = Object.fromEntries(s.paints.map((p) => [p.paint_id, p.masstone_hex]))
    } catch {
      masstones.value = {}
    }
  }

  async function loadReadings(): Promise<void> {
    const samples = unwrap(await api.GET('/api/v1/calibration/samples'))
    readings.value = samples.length
    const runs = unwrap(await api.GET('/api/v1/calibration/fits'))
    lastRun.value = runs[0] ?? null
  }

  return { accuracy, masstones, readings, lastRun, error, loadAccuracy, loadMasstones, loadReadings }
})
