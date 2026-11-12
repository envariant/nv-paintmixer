import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../test/mockFetch'
import { useMachineStore } from './machine'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('machine store', () => {
  it('refreshes the status and cancels a job', async () => {
    const status = { name: 'DSP', transport: 'none', channels: 10, channels_loaded: 5, state: 'ready', label: 'Machine ready', current_job: null, recent: [] }
    const { calls } = mockFetch({
      'GET /api/v1/machine': { json: status },
      'POST /api/v1/jobs/4/cancel': { json: {} },
    })
    const s = useMachineStore()
    await s.refresh()
    expect(s.status?.label).toBe('Machine ready')
    await s.cancelJob(4, 'wrong cup')
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({ reason: 'wrong cup' })
  })
})
