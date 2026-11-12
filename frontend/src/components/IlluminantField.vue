<script setup lang="ts">
import { computed, ref } from 'vue'
import { ILLUMINANT } from '../lib/colour'
import { ICON } from '../lib/icons'
import IlluminantMenu from './IlluminantMenu.vue'

/** Underlined select for the illuminant the match is solved for. Trigger shows "D65 (6504 K)"; menu opens upward. */
const props = defineProps<{ modelValue: string; label?: string }>()
const emit = defineEmits<{ 'update:modelValue': [code: string] }>()

const open = ref(false)
const cct = computed(() => ILLUMINANT[props.modelValue]?.cct)
function pick(code: string) { emit('update:modelValue', code); open.value = false }
</script>

<template>
  <div class="relative min-w-0">
    <button
      aria-haspopup="listbox"
      :aria-expanded="open"
      :aria-label="`${label ?? 'Match under'} ${modelValue}`"
      class="field text-left focus-ring"
      @click="open = !open"
    >
      <span class="flex-1">{{ modelValue }} <span class="n text-fg-3 font-normal">({{ cct }} K)</span></span>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" class="mr-2 text-fg-3" :class="open && 'rotate-180'"><path :d="ICON.chevron" /></svg>
    </button>
    <IlluminantMenu
      v-if="open"
      variant="pills"
      label="Illuminant to solve for"
      :model-value="modelValue"
      class="absolute z-20 left-0 bottom-[46px]"
      @update:model-value="pick"
    />
  </div>
</template>
