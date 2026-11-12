<script setup lang="ts">
import { onMounted, ref } from 'vue'

const health = ref<string>('checking…')

onMounted(async () => {
  try {
    const res = await fetch('/api/v1/health')
    health.value = res.ok ? 'API online' : `API error ${res.status}`
  } catch {
    health.value = 'API unreachable'
  }
})
</script>

<template>
  <main class="min-h-screen bg-page p-stage text-fg">
    <h1 class="text-display font-semibold">PaintMixer</h1>
    <p class="mt-2 text-ui text-fg-2">
      Frontend scaffold, styled with the design handoff's tokens. The screens are built in M6.
    </p>
    <p class="mt-4 text-ui text-fg-3" data-testid="health">{{ health }}</p>
  </main>
</template>
