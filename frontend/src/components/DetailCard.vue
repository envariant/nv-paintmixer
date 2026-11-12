<script setup lang="ts">
/**
 * DetailCard — Library and Models share one structure: a swatch joined to a pale card with the
 * title + ColourMeta, one metric row (ΔE), two facts, and one visual on white (best-mix
 * composition / level). Actions go below, in the screen's footer.
 */
defineProps<{ label: string }>()
</script>

<template>
  <article class="flex flex-col min-h-0" :aria-label="label">
    <div class="p-3 bg-surround rounded-t-stage"><slot name="swatch" /></div>
    <div class="flex flex-col gap-4 px-5 pt-4 pb-5 bg-soft rounded-b-stage min-h-0 overflow-auto">
      <div class="flex flex-col min-w-0">
        <h2 class="m-0 text-display font-semibold truncate"><slot name="title" /></h2>
        <slot name="meta" />
      </div>
      <div v-if="$slots.metric" class="pt-3 border-t border-line"><slot name="metric" /></div>
      <dl v-if="$slots.facts" class="m-0 grid grid-cols-2 gap-x-4 pt-3 border-t border-line"><slot name="facts" /></dl>
      <div v-if="$slots.visual" class="p-3.5 bg-page rounded-field"><slot name="visual" /></div>
    </div>
  </article>
</template>
