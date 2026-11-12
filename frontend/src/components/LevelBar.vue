<script setup lang="ts">
import { computed } from 'vue'
import { labToCss, type Lab } from '../lib/colour'

/** Reservoir level: a bar in the paint's own colour (rack: thin; detail card: tall). */
const props = withDefaults(defineProps<{ pct: number | null; lab: Lab; low?: boolean; size?: 'row' | 'card'; label: string }>(), {
  size: 'row',
})
const fill = computed(() => labToCss(props.lab).css)
</script>

<template>
  <div
    class="relative overflow-hidden bg-line"
    :class="size === 'card' ? 'h-5 rounded-colour' : 'h-1.5 rounded-pill'"
    role="meter"
    :aria-label="label"
    aria-valuemin="0"
    aria-valuemax="100"
    :aria-valuenow="pct ?? undefined"
  >
    <div v-if="pct != null" class="pm-colour h-full" :class="size === 'card' && 'pm-ink'" :style="{ width: `${Math.min(100, Math.max(0, pct))}%`, background: fill }" />
    <span v-if="low" class="absolute inset-y-0 right-0 w-1 bg-warning" aria-hidden="true" />
  </div>
</template>
