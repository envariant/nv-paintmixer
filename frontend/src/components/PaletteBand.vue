<script setup lang="ts">
import { labToCss, lab, fmt } from '../lib/colour'
import type { Colour, Palette, PaletteSummary } from '../stores/library'

/** The chosen palette: a joined strip of its colours, its reach summary and worst ΔE. */
defineProps<{ palette: Palette; colours: Colour[]; summary: PaletteSummary | null }>()
const emit = defineEmits<{ edit: []; export: [] }>()
</script>

<template>
  <section class="flex items-center gap-6 px-5 py-3 bg-soft rounded-card" :aria-label="`Palette ${palette.name}`">
    <div class="flex-1 min-w-0 flex flex-col gap-2">
      <div class="p-1.5 bg-surround rounded-field">
        <div class="pm-ink flex h-8 rounded-swatch overflow-hidden" role="img" :aria-label="`${palette.name}: ${colours.map((c) => c.name).join(', ')}`">
          <span v-for="c in colours" :key="c.id" class="pm-colour flex-1" :style="{ background: labToCss(lab(c.lab)).css }" :title="c.name" />
        </div>
      </div>
      <span class="n text-caption text-fg-3" data-testid="palette-summary">
        <template v-if="summary">
          {{ summary.n }} colours · {{ summary.within }} within reach<template v-if="summary.uncertain"> · {{ summary.uncertain }} uncertain</template><template v-if="summary.out"> · {{ summary.out }} out of reach</template><template v-if="summary.pending"> · {{ summary.pending }} being matched</template><template v-if="summary.worst_de != null"> · worst ΔE {{ fmt(summary.worst_de) }}</template>
        </template>
        <template v-else>{{ colours.length }} colours</template>
      </span>
    </div>
    <div class="flex gap-2">
      <button class="btn-ghost focus-ring" @click="emit('export')">Export</button>
      <button class="btn-ghost focus-ring" @click="emit('edit')">Edit</button>
    </div>
  </section>
</template>
