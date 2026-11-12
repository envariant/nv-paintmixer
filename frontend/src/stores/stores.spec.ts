import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../test/mockFetch'
import { useCalibrationStore } from './calibration'
import { buildTarget, useMixerStore } from './mixer'
import { loadedSetWarnings, type Paint, usePaintsStore } from './paints'

const paint = (id: string, role: string, loaded = true): Paint =>
  ({ id, name: id, role, loaded, active: true, calibrated: true, created_at: '', updated_at: '' }) as Paint

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('loadedSetWarnings', () => {
  it('flags missing white, black and chromatics', () => {
    const w = loadedSetWarnings([paint('b', 'chromatic')])
    expect(w).toHaveLength(3)
  })
  it('accepts the W K C M Y starter set', () => {
    const set = [paint('w', 'white'), paint('k', 'black'), paint('c', 'chromatic'), paint('m', 'chromatic'), paint('y', 'chromatic')]
    expect(loadedSetWarnings(set)).toEqual([])
  })
  it('ignores paints that are not loaded', () => {
    const set = [paint('w', 'white', false), paint('k', 'black'), paint('c', 'chromatic'), paint('m', 'chromatic'), paint('y', 'chromatic')]
    expect(loadedSetWarnings(set)[0]).toMatch(/No white/)
  })
})

describe('paints store', () => {
  it('fetches, creates and updates', async () => {
    const { calls } = mockFetch({
      'GET /api/v1/paints': { json: [paint('w', 'white')] },
      'POST /api/v1/paints': { status: 201, json: paint('a', 'chromatic', false) },
      'PATCH /api/v1/paints/a': { json: paint('a', 'chromatic', true) },
    })
    const s = usePaintsStore()
    await s.fetchAll()
    expect(s.items.map((p) => p.id)).toEqual(['w'])
    await s.create({ id: 'a', name: 'a' } as never)
    expect(s.items.map((p) => p.id)).toEqual(['a', 'w'])
    await s.update('a', { loaded: true, dispenser_channel: 2 })
    expect(s.loaded.map((p) => p.id)).toEqual(['a', 'w'])
    expect(calls[2]).toMatchObject({ method: 'PATCH', body: { loaded: true, dispenser_channel: 2 } })
  })
  it('surfaces API errors', async () => {
    mockFetch({ 'GET /api/v1/paints': { status: 500, json: { error: { code: 'internal_error', message: 'boom' } } } })
    const s = usePaintsStore()
    await s.fetchAll()
    expect(s.error).toBe('boom')
    expect(s.loading).toBe(false)
  })
})

describe('mixer store', () => {
  it('builds targets from each picker mode', () => {
    expect(buildTarget('hex', 'ABC', null)).toEqual({ hex: '#aabbcc' })
    expect(buildTarget('hex', 'nope', null)).toBeNull()
    expect(buildTarget('lab', '50, 10 -20', null)).toEqual({ lab: [50, 10, -20] })
    expect(buildTarget('lab', '150 0 0', null)).toBeNull()
    expect(buildTarget('library', '', 7)).toEqual({ library_id: 7 })
    expect(buildTarget('library', '', null)).toBeNull()
  })
  it('solves and creates a job from a candidate', async () => {
    const candidate = { rank: 1, components: [{ paint_id: 'w', fraction: 0.7 }, { paint_id: 'c', fraction: 0.3 }] }
    const { calls } = mockFetch({
      'POST /api/v1/solve': { json: { candidates: [candidate], batch_volume_ml: 100 } },
      'POST /api/v1/jobs': { status: 201, json: { id: 1, status: 'draft' } },
    })
    const s = useMixerStore()
    s.mode = 'lab'
    s.value = '60 0 0'
    s.constraints = { max_paints: 3 }
    await s.solve()
    expect(s.status).toBe('done')
    expect(calls[0]!.body).toEqual({ max_paints: 3, target: { lab: [60, 0, 0] } })
    expect(s.best?.rank).toBe(1)
    const job = await s.createJob(s.best!)
    expect(job.id).toBe(1)
    const jobCall = calls.find((c) => c.path === '/api/v1/jobs')!
    expect(jobCall.body).toMatchObject({ components: { w: 0.7, c: 0.3 }, batch_volume_ml: 100 })
  })
  it('keeps the backend error code', async () => {
    mockFetch({ 'POST /api/v1/solve': { status: 409, json: { error: { code: 'no_active_model', message: 'fit first' } } } })
    const s = useMixerStore()
    s.value = '#7a9e9f' // the store starts without a target
    await s.solve()
    expect(s.status).toBe('error')
    expect(s.error).toEqual({ code: 'no_active_model', message: 'fit first' })
  })
})

describe('calibration store', () => {
  it('uploads a file as multipart and follows a fit run', async () => {
    let polls = 0
    const { calls } = mockFetch({
      'POST /api/v1/calibration/upload': { json: { report: { ok: true, issues: [] }, stored: 124, replaced: 0, upload_id: 1 } },
      'POST /api/v1/calibration/fit': { status: 202, json: { id: 5, status: 'queued', progress: 0 } },
      'GET /api/v1/calibration/fits/5': () => ({ json: { id: 5, status: ++polls > 1 ? 'succeeded' : 'running', progress: polls > 1 ? 1 : 0.5 } }),
    })
    const s = useCalibrationStore()
    const res = await s.uploadFile(new File(['a,b\n'], 'cal.csv', { type: 'text/csv' }), 'replace')
    expect(res?.stored).toBe(124)
    expect(calls[0]!.query).toBe('?mode=replace')
    await s.startFit({ activate: true } as never)
    expect((await s.refreshRun()).status).toBe('running')
    expect((await s.refreshRun()).status).toBe('succeeded')
  })
})

describe('mixer store: the Mix screen', () => {
  it('drops an answer that a newer solve overtook, and loads the appearance', async () => {
    let n = 0
    const cand = (rank: number) => ({ rank, predicted_spectrum: [0.5], predicted_lab: [50, 0, 0], components: [], tags: [] })
    const { calls } = mockFetch({
      'POST /api/v1/solve': () => ({ json: { candidates: [cand(++n)], reference_spectrum: [0.5], batch_volume_ml: 100 } }),
      'POST /api/v1/appearance': { json: { under: [{ illuminant: 'A', spectra: [{ display_lab: [40, 1, 2] }], de2000: [1.5] }] } },
    })
    const s = useMixerStore()
    s.mode = 'hex'
    s.value = '#7a5c80'
    s.preview = 'A'
    const first = s.solve()
    const second = s.solve()
    await Promise.all([first, second])
    expect(s.result?.candidates[0]!.rank).toBe(2) // the later solve wins
    expect(s.selectedRank).toBe(2)
    expect(s.appearance?.de2000).toEqual([1.5])
    expect(calls.find((c) => c.path === '/api/v1/appearance')!.body).toMatchObject({ illuminants: ['A'] })
  })
})
