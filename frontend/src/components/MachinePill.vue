<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMachineStore } from '../stores/machine'
import MachinePopover from './MachinePopover.vue'

/** Machine status pill in the top bar ("Machine ready" / "Correcting · Plum Mist"); opens the popover. */
const machine = useMachineStore()
const router = useRouter()
const open = ref(false)
const root = ref<HTMLElement | null>(null)

const DOT: Record<string, string> = {
  ready: 'bg-success',
  pouring: 'bg-accent',
  measuring: 'bg-accent',
  correcting: 'bg-accent',
  attention: 'bg-warning',
}

function goToJob(id: number) {
  open.value = false
  void router.push({ name: 'mix', query: { job: String(id) } })
}
async function cancelJob(id: number) {
  await machine.cancelJob(id, 'cancelled from the machine popover')
}
function onDocClick(e: MouseEvent) {
  if (open.value && root.value && !root.value.contains(e.target as Node)) open.value = false
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') open.value = false
}
onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="root" class="relative">
    <button
      class="h-touch px-4 inline-flex items-center gap-2 rounded-pill border border-line text-ui font-medium hover:bg-soft focus-ring"
      aria-haspopup="dialog"
      :aria-expanded="open"
      data-testid="machine-pill"
      @click="open = !open"
    >
      <span
        class="w-2 h-2 rounded-full"
        :class="machine.status ? DOT[machine.status.state] : 'bg-line-strong'"
        aria-hidden="true"
      />
      <span v-if="machine.status">{{ machine.status.label }}</span>
      <span v-else-if="machine.error" class="text-fg-2">Machine offline</span>
      <span v-else class="text-fg-2">Machine…</span>
    </button>
    <MachinePopover
      v-if="open && machine.status"
      :machine="machine.status"
      class="absolute right-0 top-[52px] z-30"
      @go-to-job="goToJob"
      @cancel-job="cancelJob"
    />
  </div>
</template>
