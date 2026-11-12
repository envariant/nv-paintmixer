<script setup lang="ts">
import { computed, ref } from 'vue'
import { hexToLab } from '../lib/colour'
import { formatDate } from '../lib/format'
import type { JobBrief, MachineStatus } from '../stores/machine'
import DeltaReadout from './DeltaReadout.vue'
import InkWell from './InkWell.vue'

/**
 * MachinePopover (380 px) under the machine pill: the running job (Cancel job → inline confirm,
 * Go to job) and the recent jobs.
 */
const props = defineProps<{ machine: MachineStatus }>()
const emit = defineEmits<{ 'go-to-job': [id: number]; 'cancel-job': [id: number] }>()

const confirming = ref(false)
const job = computed(() => props.machine.current_job ?? null)

const STATUS: Record<string, string> = {
  queued: 'Queued',
  pouring: 'Pouring',
  measuring: 'Measuring',
  dispensed: 'Waiting for a measurement',
  measured: 'Waiting for you',
  correcting: 'Correcting',
  needs_attention: 'Needs attention',
  done: 'Done',
  accepted: 'Accepted',
  cancelled: 'Cancelled',
}
const statusText = (j: JobBrief) => STATUS[j.status] ?? j.status
const wells = (j: JobBrief) => ({
  a: j.target_hex ? hexToLab(j.target_hex) : null,
  b: j.last_hex ? hexToLab(j.last_hex) : undefined,
})
</script>

<template>
  <div
    class="w-machine flex flex-col bg-page text-fg border border-line rounded-option shadow-popover text-left"
    role="dialog"
    aria-label="Machine"
  >
    <div class="flex items-baseline justify-between gap-3 px-4 pt-3.5 pb-3">
      <span class="text-ui font-semibold truncate">{{ machine.name }}</span>
      <span class="n text-caption text-fg-3 whitespace-nowrap">
        {{ machine.channels_loaded }} of {{ machine.channels }} channels loaded
      </span>
    </div>

    <div v-if="job" class="mx-3 mb-3 p-3.5 bg-soft rounded-card" data-testid="running-job">
      <div class="flex items-center gap-3">
        <InkWell v-if="wells(job).a" :a="wells(job).a!" :b="wells(job).b" mode="split" :size="36" :label="`${job.name}: target and latest mix`" />
        <span class="flex flex-col min-w-0 flex-1">
          <span class="text-ui font-semibold truncate">{{ job.name }}</span>
          <span class="text-caption text-accent-fg truncate">
            {{ job.paused ? 'Paused' : statusText(job) }}<template v-if="job.step"> · {{ job.step }}</template>
          </span>
        </span>
        <DeltaReadout v-if="job.last_de != null" :value="job.last_de" />
      </div>
      <div
        v-if="job.running"
        class="mt-3 h-1 rounded-pill bg-line overflow-hidden"
        role="progressbar"
        :aria-valuenow="Math.round((job.progress ?? 0) * 100)"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-label="`${job.name} progress`"
      >
        <div class="h-full bg-accent" :style="{ width: `${Math.round((job.progress ?? 0) * 100)}%` }" />
      </div>
      <div class="n mt-2 text-caption text-fg-3">
        {{ job.round === 0 ? 'First pour' : `Fix ${job.round}` }} · {{ job.poured_ml.toFixed(1) }} of {{ job.batch_volume_ml }} ml poured
      </div>

      <div v-if="!confirming" class="flex justify-between items-center gap-2 mt-3">
        <button class="btn-link focus-ring" @click="confirming = true">Cancel job</button>
        <button class="btn-ghost focus-ring" @click="emit('go-to-job', job.id)">Go to job</button>
      </div>
      <div v-else class="mt-3 pt-3 border-t border-line" role="alert">
        <p class="m-0 text-ui">Cancel {{ job.name }}? What is poured stays in the cup.</p>
        <div class="flex justify-end gap-2 mt-2.5">
          <button class="btn-ghost focus-ring" @click="confirming = false">Keep going</button>
          <button
            class="btn-ghost focus-ring !border-danger text-danger"
            @click="emit('cancel-job', job.id); confirming = false"
          >
            Cancel job
          </button>
        </div>
      </div>
    </div>

    <div class="px-4 pb-1 text-caption text-fg-3">Recent jobs</div>
    <ul class="m-0 p-0 list-none pb-2" aria-label="Recent jobs">
      <li v-if="!machine.recent.length" class="px-4 py-2 text-ui text-fg-3">None yet</li>
      <li v-for="j in machine.recent" :key="j.id">
        <button
          class="w-full flex items-center gap-3 px-4 py-2 text-left hover:bg-soft focus-ring"
          @click="emit('go-to-job', j.id)"
        >
          <InkWell v-if="wells(j).a" :a="wells(j).a!" :b="wells(j).b" mode="split" :size="24" :label="`${j.name}: target and mix`" />
          <span class="flex flex-col min-w-0 flex-1">
            <span class="text-ui truncate">{{ j.name }}</span>
            <span class="text-caption text-fg-3">{{ statusText(j) }} · {{ formatDate(j.updated_at) }}</span>
          </span>
          <span v-if="j.last_de != null" class="n text-caption text-fg-2">ΔE {{ j.last_de.toFixed(2) }}</span>
        </button>
      </li>
    </ul>
  </div>
</template>
