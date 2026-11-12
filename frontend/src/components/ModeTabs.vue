<script setup lang="ts">
import { ICON } from '../lib/icons'

/** ModeTabs — comparison style, top-right of the stage. Rounded-rect icons (solid = target) + label ≥ 1180 px. */
type Mode = 'split' | 'concentric' | 'hover'
defineProps<{ modelValue: Mode }>()
const emit = defineEmits<{ 'update:modelValue': [mode: Mode] }>()

const MODES: { id: Mode; label: string; title: string }[] = [
  { id: 'split', label: 'Split', title: 'Left: target · right: mix' },
  { id: 'concentric', label: 'Concentric', title: 'Centre: target · surround: mix' },
  { id: 'hover', label: 'Hover', title: 'Shows the mix; hover to see the target' }
]
</script>

<template>
  <div role="tablist" aria-label="Comparison style" class="seg-stage">
    <button
      v-for="m in MODES"
      :key="m.id"
      role="tab"
      :aria-selected="m.id === modelValue"
      :aria-label="m.label"
      :title="`${m.label} — ${m.title}`"
      class="focus-ring"
      @click="emit('update:modelValue', m.id)"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" aria-hidden="true">
        <path :d="ICON.mode[m.id].outline" />
        <path :d="ICON.mode[m.id].solid" fill="currentColor" stroke="none" />
      </svg>
      <span class="max-[1179px]:hidden">{{ m.label }}</span>
    </button>
  </div>
</template>
