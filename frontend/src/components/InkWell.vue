<script setup lang="ts">
import { computed } from 'vue'
import { labToCss, type Lab } from '../lib/colour'

/**
 * InkWell — the single circular colour component.
 * single: one colour · split: a | b · concentric: a in the centre of b · hover: b, a revealed on hover/focus.
 * By convention a = target, b = mix. Always on a 3 px N5 surround ring; never faded or blended.
 */
const props = withDefaults(defineProps<{
  a: Lab
  b?: Lab
  mode?: 'single' | 'split' | 'concentric' | 'hover'
  size?: 24 | 36 | 48
  label?: string
}>(), { mode: 'single', size: 36 })

const ca = computed(() => labToCss(props.a).css)
const cb = computed(() => (props.b ? labToCss(props.b).css : ca.value))
const effective = computed(() => (props.b ? props.mode : 'single'))
</script>

<template>
  <span
    class="well pm-ink-well group relative inline-block flex-none box-content p-[3px] rounded-full bg-surround align-middle"
    :style="{ width: `${size}px`, height: `${size}px` }"
    role="img"
    :aria-label="label"
    :tabindex="effective === 'hover' ? 0 : undefined"
  >
    <!-- a: target / single colour -->
    <span
      class="pm-colour absolute rounded-full z-[1]"
      :class="{
        'inset-[3px]': effective !== 'concentric',
        'inset-[30%]': effective === 'concentric',
        '[clip-path:inset(0_50%_0_0)]': effective === 'split',
        'hidden group-hover:block group-focus:block': effective === 'hover'
      }"
      :style="{ background: ca }"
    />
    <!-- b: mix -->
    <span
      v-if="effective !== 'single'"
      class="pm-colour absolute inset-[3px] rounded-full"
      :class="{ '[clip-path:inset(0_0_0_50%)]': effective === 'split' }"
      :style="{ background: cb }"
    />
  </span>
</template>
