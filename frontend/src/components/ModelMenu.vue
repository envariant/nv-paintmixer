<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { Schemas } from '../api/client'
import { formatDate } from '../lib/format'
import { ICON } from '../lib/icons'

type Model = Schemas['ModelSummary']
/** Model versions grouped by line ("CMYKW demo · @2"), like the palette menu. */
const props = defineProps<{ items: Model[]; modelValue: number | null }>()
const emit = defineEmits<{ 'update:modelValue': [version: number] }>()
const open = ref(false)
const root = ref<HTMLElement | null>(null)
const current = computed(() => props.items.find((m) => m.version === props.modelValue) ?? null)
const lines = computed(() => {
  const by = new Map<string, Model[]>()
  for (const m of props.items) by.set(m.line_name, [...(by.get(m.line_name) ?? []), m])
  return [...by.entries()]
})
const title = (m: Model) => `${m.line_name} · @${m.revision}`
function pick(v: number) {
  emit('update:modelValue', v)
  open.value = false
}
const close = (e: MouseEvent) => {
  if (root.value && !root.value.contains(e.target as Node)) open.value = false
}
onMounted(() => document.addEventListener('click', close))
onBeforeUnmount(() => document.removeEventListener('click', close))
</script>

<template>
  <div ref="root" class="relative">
    <button class="btn-ghost !h-touch focus-ring" aria-haspopup="listbox" :aria-expanded="open" @click="open = !open">
      <span class="truncate max-w-[340px]">{{ current ? title(current) : 'No model' }}</span>
      <span v-if="current?.active" class="text-caption font-semibold text-success">Active</span>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" :class="open && 'rotate-180'"><path :d="ICON.chevron" /></svg>
    </button>
    <div v-if="open" role="listbox" aria-label="Models" class="absolute z-20 top-[52px] left-0 w-popover flex flex-col py-1 bg-page border border-line rounded-option shadow-popover">
      <div v-for="([name, versions], i) in lines" :key="name" role="group" :aria-label="name" :class="i > 0 && 'border-t border-line'">
        <div class="px-4 pt-2.5 pb-1 text-caption text-fg-3">{{ name }}</div>
        <button
          v-for="m in versions"
          :key="m.version"
          role="option"
          :aria-selected="m.version === modelValue"
          class="w-full flex items-center justify-between gap-3 px-4 py-2 text-left hover:bg-soft focus-ring"
          @click="pick(m.version)"
        >
          <span class="flex flex-col min-w-0">
            <span class="text-ui truncate" :class="m.version === modelValue && 'font-semibold'">@{{ m.revision }}<template v-if="m.label"> · {{ m.label }}</template></span>
            <span class="text-caption text-fg-3">{{ m.source === 'swatches' ? 'From swatch colours' : 'Calibrated' }} · {{ formatDate(m.created_at) }}</span>
          </span>
          <span v-if="m.active" class="text-caption font-semibold text-success">Active</span>
        </button>
      </div>
    </div>
  </div>
</template>
