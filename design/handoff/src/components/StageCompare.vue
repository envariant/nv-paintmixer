<script setup lang="ts">
import { computed } from 'vue'
import { labToCss, type Lab } from '../colour'

/**
 * StageCompare — the hero swatch. Joined to a pale card below it (square bottom corners when `joined`).
 * Header row: #header-left (LightTabs) and #header-right (ModeTabs). Labels sit under the colour.
 * `candidate` is already adapted to the preview illuminant by the solver — the UI never shifts hues itself.
 */
const props = withDefaults(defineProps<{
  target: Lab
  candidate: Lab | null
  mode?: 'split' | 'concentric' | 'hover'
  targetLabel?: string
  candidateLabel?: string
  illuminant: string
  joined?: boolean
  size?: 'mix' | 'run'
}>(), { mode: 'split', targetLabel: 'Target', candidateLabel: 'Mix', joined: true, size: 'mix' })

const t = computed(() => labToCss(props.target))
const c = computed(() => (props.candidate ? labToCss(props.candidate) : null))
const leftLabel = computed(() =>
  props.mode === 'split' ? props.targetLabel : props.mode === 'concentric' ? `Centre: ${props.targetLabel.toLowerCase()}` : `Hover to see ${props.targetLabel.toLowerCase()}`)
const aria = computed(() => {
  const m = props.candidateLabel, ill = props.illuminant
  return props.mode === 'split' ? `${props.targetLabel} on the left, ${m} on the right, seen under ${ill}`
    : props.mode === 'concentric' ? `${props.targetLabel} in the centre of ${m}, seen under ${ill}`
    : `${m} seen under ${ill}; hover or focus to show ${props.targetLabel.toLowerCase()}`
})
</script>

<template>
  <figure
    class="bg-surround m-0 flex flex-col flex-1 min-h-stage px-stage"
    :class="[
      size === 'run' ? 'pt-7 pb-4' : 'py-3.5',
      joined ? (size === 'run' ? 'rounded-t-stage-lg' : 'rounded-t-stage') : (size === 'run' ? 'rounded-stage-lg' : 'rounded-stage')
    ]"
  >
    <div v-if="$slots['header-left'] || $slots['header-right']" class="flex items-center justify-between gap-3 pb-3.5">
      <slot name="header-left" />
      <slot name="header-right" />
    </div>

    <div
      class="pm-ink group relative flex-1 overflow-hidden rounded-colour"
      role="img"
      :aria-label="aria"
      :tabindex="mode === 'hover' ? 0 : undefined"
    >
      <template v-if="c">
        <!-- the mix fills the stage; the target is laid over it (no border between them) -->
        <div class="pm-colour absolute inset-0" :style="{ background: c.css }" />
        <div
          class="pm-colour absolute"
          :class="{
            'inset-y-0 left-0 w-1/2': mode === 'split',
            'inset-[28%]': mode === 'concentric',
            'inset-0 hidden group-hover:block group-focus:block': mode === 'hover'
          }"
          :style="{ background: t.css }"
        />
      </template>
      <template v-else>
        <!-- empty / solving / error fill the right half -->
        <div class="pm-colour absolute inset-y-0 left-0 w-1/2" :style="{ background: t.css }" />
        <div class="absolute inset-y-0 right-0 w-1/2 flex flex-col items-center justify-center gap-3 shadow-[inset_1px_0_0_rgb(255_255_255/0.35)]">
          <slot name="empty" />
        </div>
      </template>
    </div>

    <figcaption class="on-surround flex justify-between pt-3">
      <span>{{ leftLabel }}<template v-if="t.clipped"> · shown as close as this screen allows</template></span>
      <span>{{ candidateLabel }}</span>
    </figcaption>
  </figure>
</template>
