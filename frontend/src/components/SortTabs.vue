<script setup lang="ts" generic="T extends string">
/** Segmented control on a light surface. Used in the "Ways to mix it" header: Closest · Fewest paints · Cost. */
defineProps<{ modelValue: T; options: { id: T; label: string }[]; label: string }>()
const emit = defineEmits<{ 'update:modelValue': [id: T] }>()
</script>

<template>
  <div class="seg" role="radiogroup" :aria-label="label">
    <button
      v-for="o in options"
      :key="o.id"
      role="radio"
      :aria-checked="o.id === modelValue"
      class="focus-ring"
      @click="emit('update:modelValue', o.id)"
    >{{ o.label }}</button>
  </div>
</template>
