import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { JobBrief, MachineStatus } from '../stores/machine'
import MachinePopover from './MachinePopover.vue'

const brief = (over: Partial<JobBrief> = {}): JobBrief => ({
  id: 7,
  name: 'Plum Mist',
  status: 'pouring',
  target_hex: '#7a5c80',
  last_hex: null,
  last_de: null,
  round: 0,
  batch_volume_ml: 100,
  poured_ml: 42.5,
  step: 'Pouring Magenta · 2 of 4',
  progress: 0.4,
  paused: false,
  running: true,
  updated_at: '2026-11-02T10:00:00Z',
  ...over,
})

const machine = (current: JobBrief | null, recent: JobBrief[] = []): MachineStatus => ({
  name: 'DSP-01 (simulated)',
  transport: 'none',
  channels: 10,
  channels_loaded: 5,
  state: current ? 'pouring' : 'ready',
  label: current ? `Pouring · ${current.name}` : 'Machine ready',
  current_job: current,
  recent,
})

describe('MachinePopover', () => {
  it('shows the running job and asks before cancelling it', async () => {
    const w = mount(MachinePopover, { props: { machine: machine(brief()) } })
    const card = w.get('[data-testid=running-job]')
    expect(card.text()).toContain('Plum Mist')
    expect(card.text()).toContain('Pouring Magenta · 2 of 4')
    expect(card.text()).toContain('42.5 of 100 ml poured')
    expect(w.get('[role=progressbar]').attributes('aria-valuenow')).toBe('40')
    await w.get('button.btn-link').trigger('click') // Cancel job
    expect(w.emitted('cancel-job')).toBeUndefined() // only asked
    expect(w.text()).toContain('What is poured stays in the cup.')
    const confirm = w.findAll('button').find((b) => b.text() === 'Cancel job')!
    await confirm.trigger('click')
    expect(w.emitted('cancel-job')).toEqual([[7]])
  })

  it('lists recent jobs with dates that carry the year', async () => {
    const done = brief({ id: 3, name: 'Sage', status: 'done', running: false, last_de: 0.63, last_hex: '#859072' })
    const w = mount(MachinePopover, { props: { machine: machine(null, [done]) } })
    expect(w.find('[data-testid=running-job]').exists()).toBe(false)
    expect(w.text()).toContain('Done · 2 Nov 2026')
    expect(w.text()).toContain('ΔE 0.63')
    await w.get('ul button').trigger('click')
    expect(w.emitted('go-to-job')).toEqual([[3]])
  })

  it('says when the job is paused', () => {
    const w = mount(MachinePopover, { props: { machine: machine(brief({ paused: true, step: 'Paused' })) } })
    expect(w.get('[data-testid=running-job]').text()).toContain('Paused')
  })
})
