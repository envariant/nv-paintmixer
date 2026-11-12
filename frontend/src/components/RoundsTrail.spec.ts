import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ProgressSteps from './ProgressSteps.vue'
import RoundsTrail from './RoundsTrail.vue'

const rounds = [
  { iteration: 0, label: 'First pour', hex: '#7a5c80', de: 1.84, added_ml: 100, poured_ml: 100 },
  { iteration: 1, label: 'Fix 1', hex: '#785b7f', de: 0.62, added_ml: 2.7, poured_ml: 102.7 },
]

describe('RoundsTrail', () => {
  it('labels fixes with the volume they added and picks a round', async () => {
    const w = mount(RoundsTrail, { props: { rounds, modelValue: 1 } })
    const chips = w.findAll('[role=radio]')
    expect(chips.map((c) => c.text())).toEqual(['First pourΔE 1.84', 'Fix 1 · +2.7 mlΔE 0.62'])
    expect(chips[1]!.attributes('aria-checked')).toBe('true')
    await chips[0]!.trigger('click')
    expect(w.emitted('update:modelValue')).toEqual([[0]])
  })
})

describe('ProgressSteps', () => {
  it('marks the current step', () => {
    const w = mount(ProgressSteps, { props: { steps: ['Pour', 'Measure', 'Decide'], current: 1 } })
    const items = w.findAll('li')
    expect(items[1]!.attributes('aria-current')).toBe('step')
    expect(items[0]!.find('svg').exists()).toBe(true) // done: check mark
    expect(items[2]!.text()).toContain('3')
  })
})
