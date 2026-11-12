<script setup lang="ts">
import { computed } from 'vue'
import { hexToLab, lab, type Lab } from '../lib/colour'
import { formatDate } from '../lib/format'
import type { PaintAccuracy } from '../stores/rack'
import type { Schemas } from '../api/client'
import ColourMeta from './ColourMeta.vue'
import LevelBar from './LevelBar.vue'
import ResidualStrip from './ResidualStrip.vue'

/** One paint in the rack: paint · channel / type · level · accuracy strip · status + date. */
const props = defineProps<{ paint: Schemas['PaintRead']; accuracy: PaintAccuracy | null; selected: boolean; masstoneHex?: string }>()
const emit = defineEmits<{ select: [] }>()

// the viewed model's masstone when given, else the active model's
const paintLab = computed<Lab>(() =>
  props.masstoneHex ? hexToLab(props.masstoneHex) : props.paint.model_lab ? lab(props.paint.model_lab) : { L: 50, a: 0, b: 0 },
)
const hex = computed(() => props.masstoneHex ?? props.paint.model_hex ?? '#767676')
export type Status = PaintAccuracy['status']
const STATUS: Record<Status, [string, string]> = {
  ok: ['Calibrated', 'text-fg-2'],
  review: ['Review samples', 'text-warning'],
  needs_samples: ['Needs samples', 'text-warning'],
  stale: ['Stale · new batch', 'text-danger'],
  uncalibrated: ['Not calibrated', 'text-fg-3'],
}
const status = computed(() => STATUS[props.accuracy?.status ?? 'uncalibrated'])
const type = computed(() => props.paint.body_type || { white: 'White', black: 'Black', chromatic: 'Colour' }[props.paint.role ?? 'chromatic'])
</script>

<template>
  <button
    class="grid grid-cols-[minmax(0,1.6fr)_110px_minmax(0,1fr)_minmax(0,1.3fr)_150px] gap-5 items-center w-full px-4 py-3 text-left border-b border-line focus-ring"
    :class="selected ? 'bg-soft' : 'hover:bg-soft'"
    :aria-pressed="selected"
    @click="emit('select')"
  >
    <span class="flex items-center gap-3 min-w-0">
      <span class="pm-colour pm-ink flex-none w-8 h-8 rounded-swatch" :style="{ background: hex }" />
      <span class="flex flex-col min-w-0">
        <span class="text-ui font-semibold truncate">{{ paint.name }}</span>
        <ColourMeta v-if="masstoneHex || paint.model_lab" :lab="paintLab" :hex="hex.toUpperCase()" :pigment="paint.pigment_code || undefined" :pigment-name="paint.name" />
      </span>
    </span>
    <span class="flex flex-col">
      <span class="n text-ui">{{ paint.dispenser_channel ? `Channel ${paint.dispenser_channel}` : 'Not loaded' }}</span>
      <span class="text-caption text-fg-3">{{ type }}</span>
    </span>
    <span class="flex flex-col gap-1.5">
      <LevelBar :pct="paint.level_pct ?? null" :lab="paintLab" :low="paint.low" :label="`${paint.name} level`" />
      <span class="n text-caption" :class="paint.low ? 'text-warning font-semibold' : 'text-fg-3'">
        <template v-if="paint.level_pct != null">{{ Math.round(paint.level_pct) }}% · {{ Math.round(paint.level_ml ?? 0) }} ml</template>
        <template v-else>Level not tracked</template>
      </span>
    </span>
    <span>
      <ResidualStrip v-if="accuracy?.samples.length" :samples="accuracy.samples.map((s) => ({ id: s.id, dE: s.de2000 }))" :label="`${paint.name} calibration accuracy`" />
      <span v-else class="text-caption text-fg-3">No samples</span>
    </span>
    <span class="flex flex-col">
      <span class="text-ui font-medium" :class="status[1]">{{ status[0] }}</span>
      <span v-if="accuracy && accuracy.status !== 'uncalibrated'" class="text-caption text-fg-3">{{ formatDate(accuracy.calibrated_at) }}</span>
    </span>
  </button>
</template>
