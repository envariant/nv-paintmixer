<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { hexToLab, lab, type Lab } from '../../lib/colour'
import { stepText } from '../../lib/format'
import { useMachineStore } from '../../stores/machine'
import { useRunStore } from '../../stores/run'
import DeltaReadout from '../DeltaReadout.vue'
import ProgressSteps from '../ProgressSteps.vue'
import RoundsTrail from '../RoundsTrail.vue'
import StageCompare from '../StageCompare.vue'

/**
 * Mix while a job runs: progress steps, the planned colour vs what was measured, a band with the
 * round's ΔE and the rounds trail; footer Pause / Correct again · Accept (60 px).
 */
const route = useRoute()
const router = useRouter()
const run = useRunStore()
const machine = useMachineStore()
const viewed = ref<number | null>(null)

const jobId = computed(() => Number(route.query.job))
watch(
  jobId,
  (id) => {
    viewed.value = null
    if (id) void run.follow(id)
  },
  { immediate: true },
)
onBeforeUnmount(() => run.stop())
// the machine pill follows along
watch(() => run.job?.status, () => void machine.refresh().catch(() => undefined))

const job = computed(() => (run.job?.id === jobId.value ? run.job : null))
const STEPS = ['Pour', 'Measure', 'Decide']
const current = computed(() => {
  const s = job.value?.status
  if (s === 'queued' || s === 'pouring' || s === 'draft') return 0
  if (s === 'measuring' || s === 'dispensed') return 1
  if (s === 'correcting' && job.value?.running) return 0
  return 2
})
const rounds = computed(() => run.rounds)
const shown = computed(() => {
  const all = rounds.value
  return all.find((r) => r.iteration === viewed.value) ?? all[all.length - 1] ?? null
})
const planned = computed<Lab>(() => lab((job.value?.target['lab'] as number[]) ?? [49.4, 0, 0]))
const measured = computed<Lab | null>(() => (shown.value ? hexToLab(shown.value.hex) : null))
const waiting = computed(() => !!job.value && !job.value.running && ['measured', 'needs_attention'].includes(job.value.status))
const finished = computed(() => !!job.value && ['done', 'accepted', 'cancelled'].includes(job.value.status))
const name = computed(() => job.value?.name || 'Job')
const DONE: Record<string, string> = { done: 'Within tolerance: done', accepted: 'Accepted', cancelled: 'Cancelled' }

function newMix() {
  run.stop()
  void router.push({ name: 'mix', query: {} })
}
</script>

<template>
  <section class="flex-1 min-h-0 flex flex-col" aria-label="Mix: running job">
    <div class="flex-1 min-h-0 flex flex-col px-6 pt-4 pb-5">
      <div class="flex items-center justify-between gap-4 pb-3">
        <ProgressSteps :steps="STEPS" :current="current" />
        <span class="text-ui text-fg-2 truncate" role="status">
          <template v-if="job?.paused">Paused</template>
          <template v-else>{{ stepText(job?.step) }}</template>
        </span>
      </div>

      <StageCompare
        :target="planned"
        :candidate="measured"
        :illuminant="'D65'"
        target-label="Planned"
        :candidate-label="shown ? `Measured · ${shown.label}` : 'Measured'"
        size="run"
      >
        <template #empty>
          <span class="on-surround text-ui" role="status">
            {{ job?.status === 'dispensed' ? 'Poured. Measure the cup to continue.' : job?.paused ? 'Paused' : 'Pouring…' }}
          </span>
          <div v-if="job?.running" class="w-1/2 h-1 rounded-pill bg-white/30 overflow-hidden" role="progressbar" :aria-valuenow="Math.round((job.progress ?? 0) * 100)" aria-valuemin="0" aria-valuemax="100" aria-label="Round progress">
            <div class="h-full bg-white" :style="{ width: `${Math.round((job.progress ?? 0) * 100)}%` }" />
          </div>
        </template>
      </StageCompare>

      <div class="flex-none flex items-center gap-8 min-h-[96px] px-stage py-3 bg-soft rounded-b-stage-lg">
        <div class="flex flex-col min-w-[170px]">
          <span class="text-caption text-fg-3">{{ name }}</span>
          <DeltaReadout v-if="shown" :value="shown.de" size="display" />
          <span v-else class="text-body text-fg-3">No reading yet</span>
        </div>
        <RoundsTrail v-if="rounds.length" v-model="viewed" :rounds="rounds" class="flex-1 min-w-0" />
      </div>
    </div>

    <footer class="h-footer flex-none flex items-center justify-end gap-4 px-6 border-t border-line">
      <span v-if="run.error" class="mr-auto text-ui text-danger" role="alert">{{ run.error }}</span>
      <span v-else-if="finished" class="mr-auto text-ui text-fg-2">{{ DONE[job!.status] }}</span>
      <template v-if="job?.running">
        <button v-if="!job.paused" class="btn-ghost !h-run !px-6 focus-ring" :disabled="run.busy" @click="run.pause">Pause</button>
        <button v-else class="btn-primary !h-run !px-8 focus-ring" :disabled="run.busy" @click="run.resume">Resume</button>
      </template>
      <template v-else-if="waiting">
        <button class="btn-ghost !h-run !px-6 focus-ring" :disabled="run.busy" @click="run.correctAgain">Correct again</button>
        <button class="btn-primary !h-run !px-8 focus-ring" :disabled="run.busy" data-testid="accept" @click="run.accept">Accept</button>
      </template>
      <button v-else-if="finished" class="btn-primary !h-run !px-8 focus-ring" @click="newMix">New mix</button>
    </footer>
  </section>
</template>
