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
  <main class="min-h-screen bg-neutral-100 p-8 text-neutral-900">
    <h1 class="text-2xl font-semibold">PaintMixer</h1>
    <p class="mt-2 text-sm text-neutral-600">
      Frontend scaffold. The UI is built in M6 from the Claude Design handoff bundle.
    </p>
    <p class="mt-4 text-sm" data-testid="health">{{ health }}</p>
  </main>
</template>
