<script setup lang="ts">
import { fmt, hexToLab } from '../lib/colour'
import type { Round } from '../stores/run'
import InkWell from './InkWell.vue'

/** The rounds of a job: "First pour", "Fix 1 · +2.7 ml", each with its measured colour and ΔE. */
defineProps<{ rounds: Round[]; modelValue: number | null }>()
const emit = defineEmits<{ 'update:modelValue': [iteration: number] }>()
</script>

<template>
  <div class="flex gap-1.5 overflow-x-auto" role="radiogroup" aria-label="Rounds">
    <button
      v-for="r in rounds"
      :key="r.iteration"
      role="radio"
      :aria-checked="r.iteration === modelValue"
      class="flex-none inline-flex items-center gap-2 h-touch pl-1.5 pr-3 rounded-pill border focus-ring"
      :class="r.iteration === modelValue ? 'bg-page border-fg' : 'border-transparent hover:bg-page'"
      @click="emit('update:modelValue', r.iteration)"
    >
      <InkWell :a="hexToLab(r.hex)" :size="24" :label="`${r.label}: measured colour`" />
      <span class="flex flex-col items-start leading-tight">
        <span class="text-caption font-semibold">{{ r.label }}<template v-if="r.iteration > 0"> · +{{ fmt(r.added_ml, 1) }} ml</template></span>
        <span class="n text-caption text-fg-3">ΔE {{ fmt(r.de) }}</span>
      </span>
    </button>
  </div>
</template>
