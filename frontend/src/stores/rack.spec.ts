import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../test/mockFetch'
import { useRackStore } from './rack'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('rack store', () => {
  it('loads accuracy and masstones for the viewed model, readings and the last fit', async () => {
    mockFetch({
      'GET /api/v1/models/2/paint-accuracy': { json: [{ paint_id: 'w', status: 'uncalibrated', samples: [] }] },
      'GET /api/v1/models/2/spectra': { json: { paints: [{ paint_id: 'w', masstone_hex: '#eeefe9' }] } },
      'GET /api/v1/calibration/samples': { json: [{}, {}, {}] },
      'GET /api/v1/calibration/fits': { json: [{ id: 2, status: 'succeeded' }, { id: 1 }] },
    })
    const s = useRackStore()
    await Promise.all([s.loadAccuracy('2'), s.loadMasstones('2'), s.loadReadings()])
    expect(s.accuracy[0]!.status).toBe('uncalibrated')
    expect(s.masstones).toEqual({ w: '#eeefe9' })
    expect(s.readings).toBe(3)
    expect(s.lastRun?.id).toBe(2)
  })
})
