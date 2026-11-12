<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { labToCss, lab } from '../lib/colour'
import { ICON } from '../lib/icons'
import type { Colour, Palette } from '../stores/library'

/** Dropdown of palettes ("All colours" first, "New palette" last): a strip + meta per item. */
const props = defineProps<{ items: Palette[]; colours: Map<number, Colour>; modelValue: number | null }>()
const emit = defineEmits<{ 'update:modelValue': [id: number | null]; new: [] }>()
const open = ref(false)
const root = ref<HTMLElement | null>(null)
const current = computed(() => props.items.find((p) => p.id === props.modelValue) ?? null)
const strip = (p: Palette) =>
  p.color_ids
    .slice(0, 8)
    .map((id) => props.colours.get(id))
    .filter((c): c is Colour => !!c)
    .map((c) => labToCss(lab(c.lab)).css)
function pick(id: number | null) {
  emit('update:modelValue', id)
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
      {{ current ? current.name : 'All colours' }}
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" :class="open && 'rotate-180'"><path :d="ICON.chevron" /></svg>
    </button>
    <div v-if="open" role="listbox" aria-label="Palettes" class="absolute z-20 top-[52px] left-0 w-popover flex flex-col py-1.5 bg-page border border-line rounded-option shadow-popover">
      <button role="option" :aria-selected="modelValue === null" class="flex items-center justify-between px-4 h-touch text-ui text-left hover:bg-soft focus-ring" :class="modelValue === null && 'font-semibold'" @click="pick(null)">
        All colours <span class="n text-caption text-fg-3">{{ colours.size }}</span>
      </button>
      <button v-for="p in items" :key="p.id" role="option" :aria-selected="modelValue === p.id" class="flex flex-col gap-1.5 px-4 py-2.5 text-left hover:bg-soft focus-ring" @click="pick(p.id)">
        <span class="flex items-center justify-between w-full text-ui" :class="modelValue === p.id && 'font-semibold'">{{ p.name }}<span class="n text-caption text-fg-3 font-normal">{{ p.color_ids.length }} colours</span></span>
        <span class="flex gap-[2px] h-2.5 rounded-swatch overflow-hidden" aria-hidden="true">
          <span v-for="(css, i) in strip(p)" :key="i" class="pm-colour flex-1" :style="{ background: css }" />
        </span>
      </button>
      <button class="mx-4 mt-1 pt-2.5 pb-1.5 border-t border-line text-ui text-left font-medium text-accent-fg focus-ring" @click="emit('new'); open = false">+ New palette</button>
    </div>
  </div>
</template>
