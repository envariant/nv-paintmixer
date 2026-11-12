import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RackRow from './RackRow.vue'

const paint = (over: Record<string, unknown> = {}) =>
  ({
    id: 'pb15',
    name: 'Cyan (Phthalo Blue)',
    pigment_code: 'PB15:3',
    role: 'chromatic',
    body_type: '',
    dispenser_channel: 3,
    model_lab: [16.7, 27.1, -50.1],
    model_hex: '#002868',
    level_ml: 45,
    level_pct: 18,
    low: true,
    ...over,
  }) as never

const accuracy = (status: string) =>
  ({
    paint_id: 'pb15',
    status,
    calibrated_at: '2026-11-02T10:00:00Z',
    samples: [
      { id: 'S1', de2000: 0.4, holdout: false, outlier: false, major: true },
      { id: 'S2', de2000: 3.2, holdout: true, outlier: false, major: true },
    ],
  }) as never

describe('RackRow', () => {
  it('shows channel, level, accuracy strip and status with its date', () => {
    const w = mount(RackRow, { props: { paint: paint(), accuracy: accuracy('review'), selected: false } })
    const t = w.text()
    expect(t).toContain('Channel 3')
    expect(t).toContain('18% · 45 ml')
    expect(t).toContain('Review samples')
    expect(t).toContain('2 Nov 2026')
    expect(t).toContain('· PB15:3')
    expect(w.get('[role=meter]').attributes('aria-valuenow')).toBe('18')
    expect(w.findAll('[aria-label^="Sample"]')).toHaveLength(2)
  })

  it('uses the viewed model’s masstone when given', () => {
    const w = mount(RackRow, { props: { paint: paint(), accuracy: accuracy('stale'), selected: false, masstoneHex: '#002967' } })
    expect(w.text()).toContain('#002967')
    expect(w.text()).toContain('Stale · new batch')
  })

  it('says when a paint is not tracked or not calibrated', () => {
    const w = mount(RackRow, {
      props: { paint: paint({ level_pct: null, level_ml: null, low: false, dispenser_channel: null }), accuracy: null, selected: false },
    })
    expect(w.text()).toContain('Not loaded')
    expect(w.text()).toContain('Level not tracked')
    expect(w.text()).toContain('Not calibrated')
  })
})
