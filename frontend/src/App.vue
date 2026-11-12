<script setup lang="ts">
import { onMounted } from 'vue'
import TopBar from './components/TopBar.vue'
import { useIlluminantsStore } from './stores/illuminants'
import { useMachineStore } from './stores/machine'

/** Kiosk layout: the app fills the viewport; only regions inside a screen scroll. */
const machine = useMachineStore()
const illuminants = useIlluminantsStore()
onMounted(() => {
  void machine.startPolling()
  void illuminants.load()
})
</script>

<template>
  <div class="h-screen flex flex-col overflow-hidden bg-page text-fg">
    <TopBar />
    <main class="flex-1 min-h-0 flex flex-col">
      <RouterView />
    </main>
  </div>
</template>
