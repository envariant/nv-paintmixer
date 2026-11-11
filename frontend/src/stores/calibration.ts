import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type Schemas, unwrap } from '../api/client'

export type FitRun = Schemas['FitRunRead']

export const useCalibrationStore = defineStore('calibration', () => {
  const report = ref<Schemas['ValidationReportOut'] | null>(null)
  const upload = ref<Schemas['UploadResult'] | null>(null)
  const run = ref<FitRun | null>(null)
  const models = ref<Schemas['ModelSummary'][]>([])
  const busy = ref(false)
  const error = ref<string | null>(null)

  function form(file: File): FormData {
    const fd = new FormData()
    fd.append('file', file)
    return fd
  }

  async function guarded<T>(fn: () => Promise<T>): Promise<T | undefined> {
    busy.value = true
    error.value = null
    try {
      return await fn()
    } catch (e) {
      error.value = (e as Error).message
      return undefined
    } finally {
      busy.value = false
    }
  }

  const validate = (file: File) =>
    guarded(async () => {
      report.value = unwrap(
        await api.POST('/api/v1/calibration/validate', {
          body: form(file) as never,
          bodySerializer: (b) => b as unknown as FormData,
        }),
      )
      return report.value
    })

  const uploadFile = (file: File, mode: 'append' | 'replace' = 'append') =>
    guarded(async () => {
      upload.value = unwrap(
        await api.POST('/api/v1/calibration/upload', {
          params: { query: { mode } },
          body: form(file) as never,
          bodySerializer: (b) => b as unknown as FormData,
        }),
      )
      report.value = upload.value.report
      return upload.value
    })

  async function startFit(body: Schemas['FitRequest'] = {} as Schemas['FitRequest']): Promise<FitRun> {
    run.value = unwrap(await api.POST('/api/v1/calibration/fit', { body }))
    return run.value
  }

  async function refreshRun(): Promise<FitRun> {
    if (!run.value) throw new Error('no fit started')
    run.value = unwrap(
      await api.GET('/api/v1/calibration/fits/{run_id}', { params: { path: { run_id: run.value.id } } }),
    )
    return run.value
  }

  async function fetchModels(): Promise<void> {
    models.value = unwrap(await api.GET('/api/v1/models'))
  }

  /** Activate a model by ref: global version (12), line id, line@3 or line@latest. */
  async function activate(ref: number | string): Promise<void> {
    unwrap(await api.POST('/api/v1/models/{ref}/activate', { params: { path: { ref: String(ref) } } }))
    await fetchModels()
  }

  return { report, upload, run, models, busy, error, validate, uploadFile, startFit, refreshRun, fetchModels, activate }
})
