import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../test/mockFetch'
import { useLibraryStore } from './library'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const colour = (id: number, match: unknown) => ({ id, name: `C${id}`, hex: '#777777', lab: [50, 0, 0], match })
const match = { model_version: 1, de: 0.4, n_paints: 3, cost_per_250ml: 15, reach: 'within', best_components: [] }

describe('library store', () => {
  it('asks for match summaries and keeps polling while some are pending', async () => {
    vi.useFakeTimers()
    let n = 0
    const { calls } = mockFetch({
      'GET /api/v1/colors': () => ({ json: [colour(1, match), colour(2, ++n > 1 ? match : null)] }),
    })
    const s = useLibraryStore()
    await s.follow(1000)
    expect(calls[0]!.query).toBe('?with_match=true')
    expect(s.pending).toBe(1)
    await vi.advanceTimersByTimeAsync(1000)
    expect(s.pending).toBe(0)
    await vi.advanceTimersByTimeAsync(5000)
    expect(calls).toHaveLength(2) // stopped once everything was matched
  })

  it('creates a palette, then updates it', async () => {
    const { calls } = mockFetch({
      'POST /api/v1/palettes': { status: 201, json: { id: 4, name: 'P', color_ids: [2, 1] } },
      'PATCH /api/v1/palettes/4': { json: { id: 4, name: 'P', color_ids: [1] } },
      'GET /api/v1/palettes': { json: [] },
    })
    const s = useLibraryStore()
    expect((await s.savePalette(null, 'P', [2, 1])).id).toBe(4)
    await s.savePalette(4, 'P', [1])
    expect(calls.filter((c) => c.method !== 'GET').map((c) => [c.method, c.body])).toEqual([
      ['POST', { name: 'P', color_ids: [2, 1] }],
      ['PATCH', { name: 'P', color_ids: [1] }],
    ])
  })
})
