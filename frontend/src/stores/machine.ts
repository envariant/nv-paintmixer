import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type Schemas, unwrap } from '../api/client'
import { usePolling } from '../composables/usePolling'

export type MachineStatus = Schemas['MachineStatus']
export type JobBrief = Schemas['JobBrief']

/** The machine pill and popover: GET /machine, polled (the frontend does not use /events yet). */
export const useMachineStore = defineStore('machine', () => {
  const status = ref<MachineStatus | null>(null)
  const error = ref<string | null>(null)

  async function refresh(): Promise<MachineStatus> {
    const s = unwrap(await api.GET('/api/v1/machine'))
    status.value = s
    error.value = null
    return s
  }

  const poll = usePolling(
    () =>
      refresh().catch((e: unknown) => {
        error.value = e instanceof Error ? e.message : String(e)
        return null
      }),
    () => false,
    2000,
  )

  async function cancelJob(id: number, reason = ''): Promise<void> {
    unwrap(await api.POST('/api/v1/jobs/{job_id}/cancel', { params: { path: { job_id: id } }, body: { reason } }))
    await refresh()
  }

  return { status, error, refresh, cancelJob, startPolling: poll.start, stopPolling: poll.stop }
})
