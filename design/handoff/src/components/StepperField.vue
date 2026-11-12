<script setup lang="ts">
import { ICON } from '../icons'

/** Underlined stepper (e.g. Max paints: 1 … paints in the active model, default 4). − / + sit at the right end. */
const props = withDefaults(defineProps<{ modelValue: number; min?: number; max: number; label: string }>(), { min: 1 })
const emit = defineEmits<{ 'update:modelValue': [n: number] }>()
const set = (n: number) => emit('update:modelValue', Math.min(props.max, Math.max(props.min, n)))
</script>

<template>
  <div class="field" role="spinbutton" :aria-label="label" :aria-valuemin="min" :aria-valuemax="max" :aria-valuenow="modelValue">
    <span class="n flex-1">{{ modelValue }}</span>
    <button :aria-label="`Fewer (${label})`" :disabled="modelValue <= min" class="w-8 h-8 rounded-pill inline-flex items-center justify-center disabled:opacity-35 hover:bg-soft focus-ring" @click="set(modelValue - 1)">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path :d="ICON.minus" /></svg>
    </button>
    <button :aria-label="`More (${label})`" :disabled="modelValue >= max" class="w-8 h-8 rounded-pill inline-flex items-center justify-center disabled:opacity-35 hover:bg-soft focus-ring" @click="set(modelValue + 1)">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path :d="ICON.plus" /></svg>
    </button>
  </div>
</template>
