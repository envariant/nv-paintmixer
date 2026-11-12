<script setup lang="ts">
import { computed } from 'vue'
import { fmt, labToCss, type Lab } from '../colour'

/**
 * Reach at the target's lightness (a*b* plane). The plot stays square; the axis lines are HTML and
 * span the whole white surface; +a* / +b* labels are 12 px HTML aligned to the axis ends.
 * Below: one L*a*b* row (Target | Mix), then the ΔE line and the margin footnote.
 */
const props = withDefaults(defineProps<{
  target: Lab
  mix: Lab
  mixName: string
  dE: number
  margin: number
  gamut: [number, number][]   // a*, b* outline of what the paints can make at this L*
  range?: number              // ± a*/b* shown
}>(), { range: 60 })

const toXY = ([a, b]: [number, number]) => [((a + props.range) / (2 * props.range)) * 300, ((props.range - b) / (2 * props.range)) * 300]
const poly = computed(() => props.gamut.map((p) => toXY(p).map((v) => v.toFixed(1)).join(',')).join(' '))
const dot = computed(() => toXY([props.target.a, props.target.b]))
const n = (v: number) => fmt(v)
</script>

<template>
  <div class="grid grid-rows-subgrid row-span-4 min-w-0 min-h-0">
    <span class="text-caption text-fg-3">Reach at L* {{ Math.round(target.L) }} (a* b*)</span>

    <div role="img" aria-label="Gamut of your paints at this lightness, with the target marked" class="relative h-full min-h-0 px-3 py-2.5 bg-page rounded-field">
      <span aria-hidden="true" class="absolute left-3 right-3 top-1/2 h-px bg-line" />
      <span aria-hidden="true" class="absolute top-2.5 bottom-2.5 left-1/2 w-px bg-line" />
      <svg viewBox="-30 -30 360 360" preserveAspectRatio="xMidYMid meet" aria-hidden="true" class="relative block w-full h-full">
        <polygon :points="poly" class="fill-soft stroke-line-strong" stroke-width="1.5" vector-effect="non-scaling-stroke" />
        <circle :cx="dot[0]" :cy="dot[1]" r="11" :fill="labToCss(target).css" class="stroke-fg" stroke-width="2" vector-effect="non-scaling-stroke" />
      </svg>
      <span class="absolute right-3 bottom-[calc(50%+2px)] text-caption text-fg-3">+a*</span>
      <span class="absolute top-2.5 right-[calc(50%+6px)] text-caption text-fg-3">+b*</span>
    </div>

    <div class="grid grid-cols-[auto_minmax(0,1fr)_minmax(0,1fr)] gap-x-4 text-caption">
      <span /><span class="py-1 text-right text-fg-3">Target</span><span class="py-1 text-right text-fg-3 truncate">{{ mixName }}</span>
      <span class="col-span-3 h-px bg-line" aria-hidden="true" />
      <span class="py-1 text-fg-3">L*a*b*</span>
      <span class="n py-1 text-right">{{ n(target.L) }} {{ n(target.a) }} {{ n(target.b) }}</span>
      <span class="n py-1 text-right">{{ n(mix.L) }} {{ n(mix.a) }} {{ n(mix.b) }}</span>
    </div>

    <span class="flex flex-col gap-0.5 text-caption text-fg-3">
      <span class="text-fg-2">{{ mixName }} is ΔE <span class="n">{{ fmt(dE) }}</span> from the target.</span>
      <span>Margin to the edge of your paints’ reach: ΔE {{ fmt(margin, 1) }}</span>
    </span>
  </div>
</template>
