import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PaletteBand from './PaletteBand.vue'

const palette = { id: 1, name: 'Facade', color_ids: [1, 2], created_at: '', updated_at: '' }
const colours = [1, 2].map((id) => ({ id, name: `C${id}`, hex: '#777777', lab: [50, 0, 0] })) as never

describe('PaletteBand', () => {
  it('summarises reach and the worst ΔE, and offers edit / export', async () => {
    const summary = { n: 5, within: 3, uncertain: 1, out: 1, pending: 0, worst_de: 12.28 }
    const w = mount(PaletteBand, { props: { palette, colours, summary } })
    expect(w.get('[data-testid=palette-summary]').text()).toBe(
      '5 colours · 3 within reach · 1 uncertain · 1 out of reach · worst ΔE 12.28',
    )
    await w.findAll('button')[1]!.trigger('click')
    expect(w.emitted('edit')).toHaveLength(1)
  })
})
