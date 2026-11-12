import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type Schemas, unwrap } from '../api/client'

export type Job = Schemas['JobRead']
export interface Round {
  iteration: number
  label: string
  hex: string
  de: number
  added_ml: number
  poured_ml: number
}

/** The job running on the Mix screen (GET /jobs/{id} polled while the machine holds it). */
export const useRunStore = defineStore('run', () => {
  const job = ref<Job | null>(null)
  const error = ref<string | null>(null)
  const busy = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null

  const rounds = computed<Round[]>(() =>
    (job.value?.corrections ?? []).filter((e) => e['kind'] === 'round') as unknown as Round[],
  )

  async function refresh(id: number): Promise<Job> {
    job.value = unwrap(await api.GET('/api/v1/jobs/{job_id}', { params: { path: { job_id: id } } }))
    return job.value
  }

  function stop(): void {
    if (timer) clearTimeout(timer)
    timer = null
  }

  /** Follow job ``id``: poll every ``ms`` while the machine holds it. */
  async function follow(id: number, ms = 700): Promise<void> {
    stop()
    try {
      const j = await refresh(id)
      error.value = null
      if (j.running) timer = setTimeout(() => void follow(id, ms), ms)
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    }
  }

  async function act(fn: () => Promise<unknown>): Promise<void> {
    if (!job.value) return
    busy.value = true
    error.value = null
    try {
      await fn()
      await follow(job.value.id)
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      busy.value = false
    }
  }

  const path = () => ({ params: { path: { job_id: job.value!.id } } })
  const dispense = () => act(async () => unwrap(await api.POST('/api/v1/jobs/{job_id}/dispense', { ...path(), body: {} })))
  const accept = () => act(async () => unwrap(await api.POST('/api/v1/jobs/{job_id}/accept', path())))
  const pause = () => act(async () => unwrap(await api.POST('/api/v1/jobs/{job_id}/pause', path())))
  const resume = () => act(async () => unwrap(await api.POST('/api/v1/jobs/{job_id}/resume', path())))
  /** Correct again: one correction from the latest measurement, then pour it. */
  const correctAgain = () =>
    act(async () => {
      const j = unwrap(await api.POST('/api/v1/jobs/{job_id}/correct', { ...path(), body: {} }))
      if (j.status === 'correcting') unwrap(await api.POST('/api/v1/jobs/{job_id}/dispense', { ...path(), body: {} }))
    })

  return { job, error, busy, rounds, refresh, follow, stop, dispense, accept, pause, resume, correctAgain }
})
