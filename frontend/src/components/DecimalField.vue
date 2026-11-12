<script setup lang="ts">
import { ref, watch } from 'vue'

/** Underlined decimal entry (tolerances, constants): commits on change, clamps to its limits. */
const props = withDefaults(
  defineProps<{ modelValue: number; min?: number; max?: number; step?: number; unit?: string; label: string }>(),
  { min: 0, max: Number.POSITIVE_INFINITY, step: 0.1, unit: '' },
)
const emit = defineEmits<{ 'update:modelValue': [n: number] }>()
const text = ref(String(props.modelValue))
watch(() => props.modelValue, (v) => (text.value = String(v)))
function commit() {
  const v = Number(text.value.replace('−', '-'))
  if (!Number.isFinite(v)) {
    text.value = String(props.modelValue)
    return
  }
  const clamped = Math.min(props.max, Math.max(props.min, v))
  text.value = String(clamped)
  if (clamped !== props.modelValue) emit('update:modelValue', clamped)
}
</script>

<template>
  <label class="field pm-field">
    <input
      v-model="text"
      inputmode="decimal"
      :aria-label="label"
      class="n flex-1 min-w-0 border-0 p-0 bg-transparent text-fg font-semibold text-body"
      @change="commit"
      @keydown.enter="commit"
    />
    <span v-if="unit" class="mr-2 text-fg-3 font-normal">{{ unit }}</span>
  </label>
</template>
