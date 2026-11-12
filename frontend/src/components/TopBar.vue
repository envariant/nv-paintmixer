<script setup lang="ts">
import { APP_ICON } from '../lib/icons'
import MachinePill from './MachinePill.vue'

/** Top bar (64 px): logo · Mix · Library · Models · machine-status pill · settings. No page titles. */
const NAV = [
  { to: '/mix', label: 'Mix' },
  { to: '/library', label: 'Library' },
  { to: '/models', label: 'Models' },
]
</script>

<template>
  <header class="h-header flex-none flex items-center gap-6 px-6 border-b border-line bg-page">
    <RouterLink to="/mix" class="inline-flex items-center gap-2.5 rounded-pill focus-ring" aria-label="PaintMixer home">
      <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
        <circle cx="9" cy="10" r="6.5" fill="#33A6C8" />
        <circle cx="17" cy="10" r="6.5" fill="#D0417E" />
        <circle cx="13" cy="17" r="6.5" fill="#E8C12E" />
      </svg>
      <span class="text-body font-semibold">PaintMixer</span>
    </RouterLink>
    <nav class="flex gap-1" aria-label="Main">
      <RouterLink
        v-for="n in NAV"
        :key="n.to"
        :to="n.to"
        class="h-touch px-4 inline-flex items-center rounded-pill text-ui font-medium focus-ring"
        active-class="bg-soft text-fg"
        exact-active-class="bg-soft text-fg"
        :class="$route.path.startsWith(n.to) ? '' : 'text-fg-2 hover:text-fg'"
      >
        {{ n.label }}
      </RouterLink>
    </nav>
    <div class="flex-1" />
    <MachinePill />
    <RouterLink
      to="/settings"
      class="w-touch h-touch inline-flex items-center justify-center rounded-pill hover:bg-soft focus-ring"
      active-class="bg-soft"
      aria-label="Settings"
    >
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" aria-hidden="true"><path :d="APP_ICON.gear" /></svg>
    </RouterLink>
  </header>
</template>
