<script setup lang="ts">
import { computed } from 'vue'
import { labToCss, type Lab } from '../colour'

export interface MixLine { name: string; lab: Lab; fraction: number /* 0–1 */ }

/**
 * Composition for the footer pane: legend first (dot · percent · name, ellipsised on one line),
 * then a 20 px bar with radius 4 and 3 px gaps. The Dispense button sits to its right in the footer.
 */
const props = withDefaults(defineProps<{ lines: MixLine[]; minSegmentPx?: number; label: string }>(), { minSegmentPx: 6 })

const items = computed(() => props.lines.map((l) => ({ ...l, css: labToCss(l.lab).css, pct: Math.round(l.fraction * 100) })))
const aria = computed(() => `${props.label}: ` + items.value.map((i) => `${i.name} ${i.pct}%`).join(', '))
</script>

<template>
  <div class="flex-1 min-w-0 h-11 flex flex-col justify-between">
    <div class="flex gap-5 overflow-hidden whitespace-nowrap text-caption">
      <span v-for="i in items" :key="i.name" class="inline-flex items-center gap-1.5 min-w-0 truncate">
        <span class="pm-colour pm-ink flex-none w-2 h-2 rounded-full" :style="{ background: i.css }" />
        <span class="n text-fg-3">{{ i.pct }}%</span>{{ i.name }}
      </span>
    </div>
    <div class="flex gap-[3px] h-bar rounded-colour overflow-hidden" role="img" :aria-label="aria">
      <div v-for="i in items" :key="i.name" class="pm-colour pm-ink" :style="{ flex: `${i.fraction} 1 0`, minWidth: `${minSegmentPx}px`, background: i.css }" />
    </div>
  </div>
</template>
