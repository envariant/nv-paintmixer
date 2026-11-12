<script setup lang="ts">
import { computed } from 'vue'
import { reflectancePeak, colourImpression, type Lab } from '../colour'

export interface Curve { nm: number; r: number /* reflectance 0–1 */ }

/**
 * Reflectance, target (solid fg) vs mix (dashed accent). Fills its column; the SVG stretches
 * (preserveAspectRatio="none", non-scaling strokes) and the axis labels are HTML aligned to the edges,
 * so they never overflow. Below: one Peak row (Target | Mix) and one subjective colour-impression line.
 */
const props = withDefaults(defineProps<{ target: Curve[]; mix: Curve[]; mixName: string; mixLab: Lab; rMax?: number }>(), { rMax: 0.42 })

const X0 = 400, X1 = 700
const pts = (c: Curve[]) => c.map((p) => `${((p.nm - X0) / (X1 - X0)) * 100},${(1 - p.r / props.rMax) * 100}`).join(' ')
const gridY = computed(() => (1 - 0.25 / props.rMax) * 100)
const peakT = computed(() => reflectancePeak(props.target))
const peakM = computed(() => reflectancePeak(props.mix))
const impression = computed(() => colourImpression(props.mixLab))
</script>

<template>
  <div class="grid grid-rows-subgrid row-span-4 min-w-0 min-h-0">
    <div class="flex justify-between items-center gap-3 text-caption text-fg-3">
      <span>Reflectance</span>
      <span class="flex items-center gap-3.5 min-w-0">
        <span class="inline-flex items-center gap-1.5"><svg width="20" height="6" aria-hidden="true"><line x1="0" y1="3" x2="20" y2="3" class="stroke-fg" stroke-width="1.5" /></svg>Target</span>
        <span class="inline-flex items-center gap-1.5 min-w-0"><svg width="20" height="6" aria-hidden="true" class="flex-none"><line x1="0" y1="3" x2="20" y2="3" class="stroke-accent" stroke-width="1.5" stroke-dasharray="4 3" /></svg><span class="truncate">{{ mixName }}</span></span>
      </span>
    </div>

    <div role="img" :aria-label="`Reflectance curves of target and ${mixName}, ${X0} to ${X1} nanometres`" class="h-full min-h-0 flex flex-col gap-1 px-3 pt-2.5 pb-2 bg-page rounded-field">
      <div class="relative flex-1 min-h-0">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true" class="absolute inset-0 w-full h-full overflow-visible">
          <line x1="0" y1="100" x2="100" y2="100" class="stroke-line" vector-effect="non-scaling-stroke" />
          <line x1="0" :y1="gridY" x2="100" :y2="gridY" class="stroke-line" vector-effect="non-scaling-stroke" />
          <polyline :points="pts(target)" fill="none" class="stroke-fg" stroke-width="1.5" vector-effect="non-scaling-stroke" />
          <polyline :points="pts(mix)" fill="none" class="stroke-accent" stroke-width="1.5" stroke-dasharray="4 3" vector-effect="non-scaling-stroke" />
        </svg>
        <span class="absolute left-0 text-caption text-fg-3" :style="{ bottom: `calc(${100 - gridY}% + 2px)` }">25%</span>
      </div>
      <div class="grid grid-cols-[1fr_auto_1fr] text-caption text-fg-3"><span>400</span><span>550</span><span class="text-right">700 nm</span></div>
    </div>

    <div class="grid grid-cols-[auto_minmax(0,1fr)_minmax(0,1fr)] gap-x-4 text-caption">
      <span /><span class="py-1 text-right text-fg-3">Target</span><span class="py-1 text-right text-fg-3 truncate">{{ mixName }}</span>
      <span class="col-span-3 h-px bg-line" aria-hidden="true" />
      <span class="py-1 text-fg-3">Peak</span>
      <span class="n py-1 text-right">{{ peakT.nm }} nm · {{ peakT.pct }}%</span>
      <span class="n py-1 text-right">{{ peakM.nm }} nm · {{ peakM.pct }}%</span>
    </div>

    <p class="m-0 text-caption text-fg-2">{{ impression }}</p>
  </div>
</template>
