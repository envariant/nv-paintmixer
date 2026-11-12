<script setup lang="ts">
import { computed } from 'vue'

/**
 * Calibration accuracy as a density strip (Models rack, accuracy column).
 * Every sample is a 10 px dot on the centre line at 25 % ink, so overlaps composite darker (1 − 0.75ⁿ);
 * amber 55 % for ΔE 2–3; hollow red ring for ≥ 3. The pale surface is on the strip only, not the row.
 */
const props = withDefaults(defineProps<{ samples: { id: string; dE: number }[]; max?: number; marks?: number[]; label: string }>(),
  { max: 5, marks: () => [1, 2] })
const emit = defineEmits<{ select: [id: string] }>()

const dots = computed(() => props.samples.map((s) => ({
  ...s,
  left: `${(Math.min(props.max, s.dE) / props.max) * 100}%`,
  kind: s.dE >= 3 ? 'outlier' : s.dE >= 2 ? 'review' : 'ok'
})))
const worst = computed(() => (props.samples.length ? Math.max(...props.samples.map((s) => s.dE)) : 0))
</script>

<template>
  <div class="relative h-5 rounded-colour bg-soft" role="img" :aria-label="`${label}: ${samples.length} samples, worst ΔE ${worst.toFixed(2)}`">
    <span v-for="m in marks" :key="m" class="absolute inset-y-0 w-px bg-line" :style="{ left: `${(m / max) * 100}%` }" />
    <button
      v-for="d in dots" :key="d.id"
      class="absolute top-1/2 w-2.5 h-2.5 -ml-[5px] -mt-[5px] rounded-full box-border focus-ring"
      :class="{
        'bg-fg/25': d.kind === 'ok',
        'bg-warning/55': d.kind === 'review',
        'border-[1.5px] border-danger bg-transparent': d.kind === 'outlier'
      }"
      :style="{ left: d.left }"
      :aria-label="`Sample ${d.id}, ΔE ${d.dE.toFixed(2)}`"
      @click="emit('select', d.id)"
    />
  </div>
</template>
