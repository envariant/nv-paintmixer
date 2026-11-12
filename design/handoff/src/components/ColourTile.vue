<script setup lang="ts">
import { labToCss, type Lab } from '../colour'
import ColourMeta from './ColourMeta.vue'

/**
 * Library / palette-builder tile: swatch on the N5 surround joined to a pale caption (name + ColourMeta).
 * Reach problems are a dot after the name (amber = uncertain, red = out of reach), word on hover.
 * Grid: repeat(auto-fill, minmax(156px, 1fr)).
 */
const props = defineProps<{
  name: string
  lab: Lab
  hex?: string
  selected?: boolean
  status?: 'uncertain' | 'out-of-reach'
  badge?: 'add' | 'added'   // palette builder
}>()
defineEmits<{ select: [] }>()
const STATUS = { uncertain: ['Uncertain', 'bg-warning'], 'out-of-reach': ['Out of reach', 'bg-danger'] } as const
</script>

<template>
  <button
    class="flex flex-col rounded-tile text-left focus-ring"
    :class="selected && 'shadow-selected'"
    :aria-pressed="selected"
    :aria-label="name"
    @click="$emit('select')"
  >
    <span class="relative block p-2 bg-surround rounded-t-tile">
      <span class="pm-colour pm-ink block h-[72px] rounded-swatch" :style="{ background: labToCss(props.lab).css }" />
      <span v-if="badge" class="absolute -top-2 -right-2 w-[26px] h-[26px] rounded-full flex items-center justify-center"
        :class="badge === 'added' ? 'bg-fg text-page' : 'bg-page text-fg shadow-[0_0_0_1px_rgb(var(--pm-line-strong))]'">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path :d="badge === 'added' ? 'M5 12.5l4.5 4.5L19 7.5' : 'M12 5v14M5 12h14'" /></svg>
      </span>
    </span>
    <span class="flex flex-col gap-0.5 min-h-[34px] px-2.5 py-2 bg-soft rounded-b-tile">
      <span class="flex items-center gap-1.5 text-ui font-medium min-w-0">
        <span class="truncate">{{ name }}</span>
        <span v-if="status" role="img" :aria-label="STATUS[status][0]" :title="STATUS[status][0]" class="flex-none w-2 h-2 rounded-full" :class="STATUS[status][1]" />
      </span>
      <ColourMeta :lab="lab" :hex="hex" />
    </span>
  </button>
</template>
