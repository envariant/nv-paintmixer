<script setup lang="ts">
import { computed } from 'vue'
import { labToCss, tierOf, TIER_LABEL, fmt, type Lab } from '../lib/colour'
import { ICON } from '../lib/icons'
import InkWell from './InkWell.vue'
import ColourMeta from './ColourMeta.vue'

export interface Mix {
  id: string
  name: string          // "Mix A"
  tag: string           // "closest", "no black", "fewest paints"
  lab: Lab              // predicted, D65
  dE: number            // under the solve illuminant
  paints: { name: string; lab: Lab; fraction: number }[]
  cost: number          // SGD for the chosen volume
}

/**
 * One row of "Ways to mix it". Every column is two lines:
 * well · name + tag / ColourMeta · ΔE / tier · n paints / dots · SGD / premium ("Baseline" for the cheapest).
 */
const props = withDefaults(
  defineProps<{ mix: Mix; target: Lab; selected: boolean; wellMode: 'split' | 'concentric' | 'hover'; cheapest: number; currency?: string }>(),
  { currency: 'SGD' },
)
const emit = defineEmits<{ select: [id: string] }>()

const tier = computed(() => tierOf(props.mix.dE))
const tone = computed(() => ['', 'text-success', 'text-fg', 'text-warning', 'text-danger'][tier.value])
const premium = computed(() => {
  const p = Math.round(((props.mix.cost - props.cheapest) / props.cheapest) * 1000) / 10
  return p <= 0 ? 'Baseline' : `+${p}% premium`
})
</script>

<template>
  <button
    class="grid grid-cols-[46px_minmax(0,1fr)_150px_80px_110px] gap-4 items-center w-full px-4 py-2.5 rounded-option text-left border-[1.5px] focus-ring"
    :class="selected ? 'bg-page border-fg' : 'border-transparent hover:bg-page'"
    :aria-pressed="selected"
    @click="emit('select', mix.id)"
  >
    <InkWell :a="target" :b="mix.lab" :mode="wellMode" :size="36" />
    <span class="flex flex-col min-w-0">
      <span class="truncate text-ui"><span class="font-semibold">{{ mix.name }}</span><span v-if="mix.tag" class="text-fg-3"> · {{ mix.tag }}</span></span>
      <ColourMeta :lab="mix.lab" />
    </span>
    <span class="flex flex-col">
      <span class="n text-ui font-medium">ΔE {{ fmt(mix.dE) }}</span>
      <span :class="[tone, 'inline-flex items-center gap-1 text-caption font-semibold']">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="ICON.tier[tier]" /></svg>
        {{ TIER_LABEL[tier] }}
      </span>
    </span>
    <span class="flex flex-col items-end">
      <span class="n text-ui font-medium">{{ mix.paints.length }} paints</span>
      <span class="flex gap-0.5" aria-hidden="true">
        <span v-for="p in mix.paints" :key="p.name" class="pm-colour pm-ink w-2 h-2 rounded-full" :style="{ background: labToCss(p.lab).css }" />
      </span>
    </span>
    <span class="flex flex-col items-end">
      <span class="n text-ui font-medium">{{ currency }} {{ mix.cost.toFixed(2) }}</span>
      <span class="text-caption text-fg-3">{{ premium }}</span>
    </span>
  </button>
</template>
