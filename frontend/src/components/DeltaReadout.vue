<script setup lang="ts">
import { computed } from 'vue'
import { tierOf, TIER_LABEL, fmt } from '../lib/colour'
import { ICON } from '../lib/icons'

/**
 * ΔE00 number + tier icon + plain label.
 *   size="row":     14 px number, 12 px label (mix rows, machine popover).
 *   size="display": 30 px number, 16 px label (run screen band, uncertain state).
 * With `uncertainty`, the tier is judged on value + uncertainty and reads "Could be visible" when that is worse.
 */
const props = withDefaults(defineProps<{ value: number; uncertainty?: number; size?: 'row' | 'display' }>(), { size: 'row' })

const tier = computed(() => tierOf(props.uncertainty ? props.value + props.uncertainty : props.value))
const label = computed(() => (props.uncertainty && tier.value > tierOf(props.value) ? 'Could be visible' : TIER_LABEL[tier.value]))
const tone = computed(() => ['', 'text-success', 'text-fg', 'text-warning', 'text-danger'][tier.value])
</script>

<template>
  <span class="inline-flex flex-col">
    <span class="n" :class="size === 'display' ? 'text-display font-medium' : 'text-ui font-medium'">
      <template v-if="size === 'row'">ΔE </template>{{ fmt(value) }}<span v-if="uncertainty" class="text-body text-fg-2 ml-3">± {{ fmt(uncertainty, 1) }}</span>
    </span>
    <span :class="[tone, 'inline-flex items-center gap-1 font-semibold', size === 'display' ? 'text-body' : 'text-caption']">
      <svg :width="size === 'display' ? 18 : 12" :height="size === 'display' ? 18 : 12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="ICON.tier[tier]" /></svg>
      {{ label }}
    </span>
  </span>
</template>
