<script setup lang="ts">
import { computed } from 'vue'
import { labToCss, type Lab } from '../colour'
import SpectrumChart, { type Curve } from './SpectrumChart.vue'
import ReachChart from './ReachChart.vue'

/**
 * Formula → Spectrum → Reach. Opens inside the joined card, anchored above the card footer's divider and
 * rising no higher than the card's top (with a margin). Three equal columns; the two graphs share one row
 * (subgrid) so they are always the same height. No scrolling — everything flexes to the available height.
 */
const props = defineProps<{
  mix: { name: string; lab: Lab; dE: number; volumeMl: number; paints: { name: string; lab: Lab; fraction: number; ml: number; sgd: number }[] }
  target: Lab
  targetCurve: Curve[]
  mixCurve: Curve[]
  gamut: [number, number][]
  margin: number
}>()
const rows = computed(() => props.mix.paints.map((p) => ({ ...p, css: labToCss(p.lab).css })))
</script>

<template>
  <section
    aria-label="Formula, spectrum and reach"
    class="absolute -inset-x-4 -top-4 -bottom-2.5 z-10 overflow-hidden grid grid-cols-3 grid-rows-[auto_minmax(0,1fr)_auto_auto] gap-x-10 gap-y-1.5 px-5 py-4 bg-soft border border-line rounded-card shadow-popover"
  >
    <div class="row-span-4 flex flex-col gap-1.5 min-w-0">
      <span class="text-caption text-fg-3">Formula · {{ mix.name }} · {{ mix.volumeMl }} ml</span>
      <table class="n w-full border-collapse text-caption">
        <thead>
          <tr class="text-fg-3 [&>th]:font-medium [&>th]:py-1 [&>th]:border-b [&>th]:border-line">
            <th class="text-left">Paint</th><th class="text-right">%</th><th class="text-right">ml</th><th class="text-right">SGD</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in rows" :key="p.name" class="[&>td]:py-1 [&>td]:border-b [&>td]:border-line">
            <td><span class="inline-flex items-center gap-2"><span class="pm-colour pm-ink w-2.5 h-2.5 rounded-full" :style="{ background: p.css }" />{{ p.name }}</span></td>
            <td class="text-right">{{ (p.fraction * 100).toFixed(1) }}</td>
            <td class="text-right">{{ p.ml.toFixed(1) }}</td>
            <td class="text-right">{{ p.sgd.toFixed(2) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <SpectrumChart :target="targetCurve" :mix="mixCurve" :mix-name="mix.name" :mix-lab="mix.lab" />
    <ReachChart :target="target" :mix="mix.lab" :mix-name="mix.name" :d-e="mix.dE" :margin="margin" :gamut="gamut" />
  </section>
</template>
