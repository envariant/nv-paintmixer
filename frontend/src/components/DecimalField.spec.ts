import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DecimalField from './DecimalField.vue'

describe('DecimalField', () => {
  it('commits on change, clamps to its limits and reverts what is not a number', async () => {
    const w = mount(DecimalField, { props: { modelValue: 1, min: 0.1, max: 5, label: 'Tolerance' } })
    const input = w.get('input')
    // setValue fires input and change, like typing then leaving the field
    await input.setValue('0.8')
    await input.setValue('9')
    await input.setValue('abc')
    expect(w.emitted('update:modelValue')).toEqual([[0.8], [5]])
    expect((input.element as HTMLInputElement).value).toBe('1') // reverted to the model value
  })
})
