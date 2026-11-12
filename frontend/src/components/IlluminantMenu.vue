<script setup lang="ts">
import { cctTint, seriesRange, nearestInSeries } from '../lib/colour'
import { useIlluminantsStore } from '../stores/illuminants'

/**
 * IlluminantMenu — one popover, two behaviours.
 *   variant="rows":  each series section is one option; picking it switches series and keeps the
 *                    closest colour temperature (used by the series button in LightTabs).
 *   variant="pills": each illuminant is a pill you pick directly (used by the Match under field).
 * Each section: header row (name · description · range) followed by its options; dividers between sections.
 */
const props = defineProps<{ variant: 'rows' | 'pills'; modelValue: string; label: string }>()
const emit = defineEmits<{ 'update:modelValue': [code: string] }>()

const illuminants = useIlluminantsStore() // GET /illuminants (built-in catalogue until loaded)
const currentSeries = () => illuminants.byCode[props.modelValue]?.series.id
</script>

<template>
  <div
    role="listbox"
    :aria-label="label"
    class="w-popover flex flex-col px-3.5 py-1 bg-page text-fg border border-line rounded-option shadow-popover text-left"
  >
    <div
      v-for="(s, i) in illuminants.series"
      :key="s.id"
      :class="[i > 0 && 'border-t border-line', variant === 'pills' ? 'py-3' : 'py-1']"
      role="group"
      :aria-label="s.name"
    >
      <!-- rows: the whole section is the option -->
      <button
        v-if="variant === 'rows'"
        role="option"
        :aria-selected="currentSeries() === s.id"
        class="block w-[calc(100%+16px)] -mx-2 p-2 rounded-tile text-left focus-ring"
        :class="currentSeries() === s.id ? 'bg-soft' : 'hover:bg-soft'"
        @click="emit('update:modelValue', nearestInSeries(s, modelValue, illuminants.byCode))"
      >
        <span class="flex justify-between items-baseline gap-3 mb-2">
          <span class="text-ui font-semibold">{{ s.name }} <span class="text-caption text-fg-3 font-normal">{{ s.desc }}</span></span>
          <span class="n text-caption text-fg-3">{{ seriesRange(s) }}</span>
        </span>
        <span class="flex flex-wrap gap-x-3.5 gap-y-1.5 text-caption font-medium">
          <span v-for="m in s.members" :key="m.code" class="inline-flex items-center gap-1.5 h-5">
            <span class="w-3 h-3 rounded-full shadow-[inset_0_0_0_1px_rgb(0_0_0/0.25)]" :style="{ background: cctTint(m.cct) }" />{{ m.code }}
          </span>
        </span>
      </button>

      <!-- pills: each illuminant is an option -->
      <template v-else>
        <div class="flex justify-between items-baseline gap-3 mb-2">
          <span class="text-ui font-semibold">{{ s.name }} <span class="text-caption text-fg-3 font-normal">{{ s.desc }}</span></span>
          <span class="n text-caption text-fg-3">{{ seriesRange(s) }}</span>
        </div>
        <div class="flex flex-wrap gap-1">
          <button
            v-for="m in s.members"
            :key="m.code"
            role="option"
            :aria-selected="m.code === modelValue"
            :title="`${m.code} · ${m.cct} K · ${s.desc}`"
            class="h-tab pl-1.5 pr-2.5 rounded-pill inline-flex items-center gap-1.5 text-caption font-medium focus-ring"
            :class="m.code === modelValue ? 'bg-fg text-page' : 'border border-line hover:bg-soft'"
            @click="emit('update:modelValue', m.code)"
          >
            <span class="w-3 h-3 rounded-full shadow-[inset_0_0_0_1px_rgb(0_0_0/0.25)]" :style="{ background: cctTint(m.cct) }" />{{ m.code }}
          </button>
        </div>
      </template>
    </div>

    <p v-if="variant === 'rows'" class="m-0 pt-2 pb-2.5 border-t border-line text-caption text-fg-3">
      Switching series picks its closest colour temperature to {{ modelValue }}.
    </p>
  </div>
</template>
