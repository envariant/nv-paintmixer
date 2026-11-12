<script setup lang="ts">
/** Underlined number entry with a unit at the right (e.g. Volume, max 250 ml — the machine limit). No focus ring: the caret is enough. */
const props = withDefaults(defineProps<{ modelValue: number; min?: number; max: number; step?: number; unit: string; label: string }>(), { min: 1, step: 5 })
const emit = defineEmits<{ 'update:modelValue': [n: number] }>()

function onInput(e: Event) {
  const v = Math.round(Number((e.target as HTMLInputElement).value))
  if (v > 0) emit('update:modelValue', Math.min(props.max, Math.max(props.min, v)))
}
</script>

<template>
  <label class="field pm-field">
    <input
      type="number"
      :min="min" :max="max" :step="step"
      :value="modelValue"
      :aria-label="`${label} (up to ${max} ${unit})`"
      class="n flex-1 min-w-0 border-0 p-0 bg-transparent text-fg font-semibold text-body"
      @input="onInput"
    >
    <span class="mr-2 text-fg-3 font-normal">{{ unit }}</span>
  </label>
</template>
