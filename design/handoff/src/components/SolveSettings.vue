<script setup lang="ts">
import IlluminantField from './IlluminantField.vue'
import StepperField from './StepperField.vue'
import NumberField from './NumberField.vue'

/** The inputs under the target on Mix: label column (88 px) + full-width underlined fields. No hint text. */
const illuminant = defineModel<string>('illuminant', { required: true })
const maxPaints = defineModel<number>('maxPaints', { default: 4 })
const volume = defineModel<number>('volume', { default: 250 })
defineProps<{ paintsInModel: number; machineMaxMl?: number }>()
</script>

<template>
  <div role="group" aria-label="Solve settings" class="grid grid-cols-[88px_minmax(0,1fr)] items-center gap-x-4 gap-y-2 text-ui">
    <span class="text-fg-2">Match under</span>
    <IlluminantField v-model="illuminant" />
    <span class="text-fg-2">Max paints</span>
    <StepperField v-model="maxPaints" :max="paintsInModel" label="Maximum number of paints" />
    <span class="text-fg-2">Volume</span>
    <NumberField v-model="volume" :max="machineMaxMl ?? 250" unit="ml" label="Target volume" />
  </div>
</template>
