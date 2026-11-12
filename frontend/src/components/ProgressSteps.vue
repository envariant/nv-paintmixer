<script setup lang="ts">
/** Run screen steps: done steps get a check, the current one is emphasised. */
defineProps<{ steps: string[]; current: number }>()
</script>

<template>
  <ol class="m-0 p-0 list-none flex items-center gap-2 text-ui" aria-label="Progress">
    <li v-for="(s, i) in steps" :key="s" class="inline-flex items-center gap-2" :aria-current="i === current ? 'step' : undefined">
      <span
        class="n w-6 h-6 rounded-full inline-flex items-center justify-center text-caption font-semibold"
        :class="i < current ? 'bg-fg text-page' : i === current ? 'bg-accent text-accent-on' : 'border border-line-strong text-fg-3'"
        aria-hidden="true"
      >
        <svg v-if="i < current" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
        <template v-else>{{ i + 1 }}</template>
      </span>
      <span :class="i === current ? 'font-semibold' : 'text-fg-3'">{{ s }}</span>
      <span v-if="i < steps.length - 1" class="w-6 h-px bg-line-strong" aria-hidden="true" />
    </li>
  </ol>
</template>
