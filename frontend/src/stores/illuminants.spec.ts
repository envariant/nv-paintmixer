import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SERIES } from '../lib/colour'
import parity from '../lib/km.parity.json'
import { mockFetch } from '../test/mockFetch'
import { useIlluminantsStore } from './illuminants'

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('illuminants store', () => {
  it('starts from the built-in catalogue and loads the API one', async () => {
    const api = parity.illuminants.map((s) => (s.id === 'A' ? { ...s, description: 'Tungsten' } : s))
    mockFetch({ 'GET /api/v1/illuminants': { json: api } })
    const s = useIlluminantsStore()
    expect(s.series).toEqual(SERIES)
    await s.load()
    expect(s.loaded).toBe(true)
    expect(s.series.find((x) => x.id === 'A')!.desc).toBe('Tungsten')
    expect(s.byCode['LED-B3']!.cct).toBe(4103)
    expect(s.nearestInSeries('D', 'F12')).toBe('D50')
  })
  it('keeps the built-in catalogue when the API fails', async () => {
    mockFetch({})
    const s = useIlluminantsStore()
    await s.load()
    expect(s.loaded).toBe(false)
    expect(s.error).toBeTruthy()
    expect(s.series).toEqual(SERIES)
  })
})
