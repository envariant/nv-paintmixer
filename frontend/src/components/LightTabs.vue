<script setup lang="ts">
import { computed, ref } from 'vue'
import { ILLUMINANT, cctTint } from '../lib/colour'
import { ICON } from '../lib/icons'
import IlluminantMenu from './IlluminantMenu.vue'

/**
 * LightTabs — preview illuminant, top-left of the stage.
 * A series button (opens IlluminantMenu variant="rows") followed by that series' members as tabs.
 * Each tab: sun icon whose centre is tinted with the light's colour + code (code hidden below 1180 px).
 */
const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [code: string] }>()

const open = ref(false)
const series = computed(() => ILLUMINANT[props.modelValue].series)
const seriesLabel = computed(() => series.value.id)
function pick(code: string) { emit('update:modelValue', code); open.value = false }
</script>

<template>
  <div class="relative z-10">
    <div role="tablist" aria-label="Preview light" class="seg-stage">
      <button
        aria-haspopup="listbox"
        :aria-expanded="open"
        :aria-label="`Illuminant series: ${seriesLabel}`"
        class="!pl-3 !pr-2 font-semibold focus-ring"
        :class="open && 'bg-white/20'"
        @click="open = !open"
      >
        {{ seriesLabel }}
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" :class="open && 'rotate-180'"><path :d="ICON.chevron" /></svg>
      </button>
      <span aria-hidden="true" class="w-px h-[18px] mx-1 bg-white/35" />
      <button
        v-for="m in series.members"
        :key="m.code"
        role="tab"
        :aria-selected="m.code === modelValue"
        :aria-label="m.code"
        :title="`${m.code} · ${m.cct} K · ${series.desc}`"
        class="focus-ring"
        @click="pick(m.code)"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true">
          <path :d="ICON.sunRays" />
          <circle cx="12" cy="12" r="4.2" :fill="cctTint(m.cct)" stroke="rgba(0,0,0,.35)" stroke-width="1" />
        </svg>
        <span class="max-[1179px]:hidden">{{ m.code }}</span>
      </button>
    </div>
    <IlluminantMenu
      v-if="open"
      variant="rows"
      label="Illuminant series"
      :model-value="modelValue"
      class="absolute top-[42px] left-0"
      @update:model-value="pick"
    />
  </div>
</template>
