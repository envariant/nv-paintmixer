import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../test/mockFetch'
import { useRunStore } from './run'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

const job = (over: Record<string, unknown> = {}) => ({
  id: 9,
  status: 'measured',
  running: false,
  corrections: [
    { kind: 'round', iteration: 0, label: 'First pour', hex: '#7a5c80', de: 1.8, added_ml: 100, poured_ml: 100 },
    { iteration: 0, result: 'corrected' },
  ],
  ...over,
})

describe('run store', () => {
  it('reads rounds out of the job log', async () => {
    mockFetch({ 'GET /api/v1/jobs/9': { json: job() } })
    const s = useRunStore()
    await s.follow(9)
    expect(s.rounds.map((r) => r.label)).toEqual(['First pour'])
  })

  it('Correct again corrects, then pours the correction', async () => {
    const { calls } = mockFetch({
      'GET /api/v1/jobs/9': { json: job() },
      'POST /api/v1/jobs/9/correct': { json: job({ status: 'correcting' }) },
      'POST /api/v1/jobs/9/dispense': { status: 202, json: job({ status: 'queued', running: true }) },
    })
    const s = useRunStore()
    await s.follow(9)
    await s.correctAgain()
    s.stop()
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual([
      '/api/v1/jobs/9/correct',
      '/api/v1/jobs/9/dispense',
    ])
  })

  it('does not pour when the correction finished the job', async () => {
    const { calls } = mockFetch({
      'GET /api/v1/jobs/9': { json: job() },
      'POST /api/v1/jobs/9/correct': { json: job({ status: 'done' }) },
    })
    const s = useRunStore()
    await s.follow(9)
    await s.correctAgain()
    expect(calls.some((c) => c.path.endsWith('/dispense'))).toBe(false)
  })
})
