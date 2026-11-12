import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../test/mockFetch'
import SettingsView from './SettingsView.vue'

const settings = {
  illuminant: 'D65', accept_tolerance_de: 1, check_illuminants: ['A', 'F11'],
  dispenser_channels: 10, machine_max_batch_ml: 250, batch_volume_ml: 100, dispenser_resolution_ml: 0.05,
  dispenser_transport: 'none', dispenser_address: '', low_level_warn_pct: 25, currency: 'SGD', max_paints: 5,
  saunderson_k1: 0, saunderson_k2: 0.5, min_fraction: 0.02, out_of_gamut_de: 1,
  weights: { de: 1, n_paints: 0.05, cost: 0.5, metamerism: 0.05 },
  observer: 'CIE 1931 2°', geometry: '45/0, UV-cut (M2-like)', read_only: ['observer', 'geometry'],
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('SettingsView', () => {
  it('counts unsaved changes, saves only what changed, and discards', async () => {
    const { calls } = mockFetch({
      'GET /api/v1/settings': { json: settings },
      'PATCH /api/v1/settings': (_req, body) => ({ json: { ...settings, ...(body as object) } }),
    })
    const w = mount(SettingsView, { global: { stubs: { IlluminantField: true } } })
    await flushPromises()
    const tol = w.get('input[aria-label="Accept tolerance (ΔE)"]')
    await tol.setValue('0.8')
    await tol.trigger('change')
    await w.findAll('button').find((b) => b.text() === 'D50')!.trigger('click')
    expect(w.text()).toContain('2 unsaved changes')

    await w.findAll('button').find((b) => b.text() === 'Discard')!.trigger('click')
    expect(w.text()).not.toContain('unsaved')

    await tol.setValue('0.8')
    await tol.trigger('change')
    await w.get('[data-testid=save-settings]').trigger('click')
    await flushPromises()
    const patch = calls.find((c) => c.method === 'PATCH')!
    expect(patch.body).toEqual({ accept_tolerance_de: 0.8 })
    expect(w.text()).toContain('Saved')
  })

  it('bounds Max paints by the active model and shows the fixed observer and geometry', async () => {
    mockFetch({
      'GET /api/v1/settings': { json: settings },
      'GET /api/v1/models/active': { json: { version: 1, paint_ids: ['w', 'k', 'c', 'm', 'y', 'r'] } },
    })
    const w = mount(SettingsView, { global: { stubs: { IlluminantField: true } } })
    await flushPromises()
    expect(w.get('[aria-label="Default maximum number of paints"]').attributes('aria-valuemax')).toBe('6')
    expect(w.find('[data-testid=observer]').exists()).toBe(false) // Advanced is collapsed
    await w.findAll('button').find((b) => b.text().includes('Advanced colour science'))!.trigger('click')
    expect(w.get('[data-testid=observer]').text()).toContain('CIE 1931 2°')
    expect(w.get('[data-testid=geometry]').text()).toContain('45/0')
    expect(w.text()).toContain('fixed')
  })
})
