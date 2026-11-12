<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, unwrap } from '../api/client'
import ColourMeta from '../components/ColourMeta.vue'
import DetailCard from '../components/DetailCard.vue'
import LevelBar from '../components/LevelBar.vue'
import ModelMenu from '../components/ModelMenu.vue'
import RackRow from '../components/RackRow.vue'
import { calibrationGrade, fmt, formatMoney, hexToLab, lab, type Lab } from '../lib/colour'
import { formatDate, stepText } from '../lib/format'
import { useCalibrationStore } from '../stores/calibration'
import { useModelStore } from '../stores/model'
import { usePaintsStore } from '../stores/paints'
import { useRackStore } from '../stores/rack'
import { useSettingsStore } from '../stores/settings'

/** Models: model menu, readings strip, the rack of paints, the paint detail card. */
const calibration = useCalibrationStore()
const model = useModelStore()
const paints = usePaintsStore()
const rack = useRackStore()
const settingsStore = useSettingsStore()

const version = ref<number | null>(null)
const selectedId = ref<string | null>(null)
const refill = ref<{ capacity: number | null; level: number | null; batch: string } | null>(null)
const busy = ref(false)
const message = ref<string | null>(null)
const showProblems = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
let fitTimer: ReturnType<typeof setTimeout> | null = null

onMounted(async () => {
  await Promise.all([calibration.fetchModels(), paints.fetchAll(), settingsStore.load(), rack.loadReadings().catch(() => undefined)])
  version.value = calibration.models.find((m) => m.active)?.version ?? calibration.models[0]?.version ?? null
})
onBeforeUnmount(() => {
  if (fitTimer) clearTimeout(fitTimer)
})

const current = computed(() => calibration.models.find((m) => m.version === version.value) ?? null)
watch(version, (v) => {
  if (v != null) {
    void rack.loadAccuracy(String(v))
    void rack.loadMasstones(String(v))
  }
})

const rows = computed(() =>
  (current.value?.paint_ids ?? [])
    .map((id) => paints.items.find((p) => p.id === id))
    .filter((p): p is NonNullable<typeof p> => !!p),
)
const accuracyOf = (id: string) => rack.accuracy.find((a) => a.paint_id === id) ?? null
const selected = computed(() => rows.value.find((p) => p.id === selectedId.value) ?? rows.value[0] ?? null)
const selectedAccuracy = computed(() => (selected.value ? accuracyOf(selected.value.id) : null))
const selectedHex = computed(() => (selected.value ? (rack.masstones[selected.value.id] ?? selected.value.model_hex ?? '#767676') : '#767676'))
const selectedLab = computed<Lab>(() =>
  selected.value && rack.masstones[selected.value.id] ? hexToLab(selectedHex.value) : selected.value?.model_lab ? lab(selected.value.model_lab) : { L: 50, a: 0, b: 0 },
)
const currency = computed(() => settingsStore.settings?.currency ?? 'SGD')
const problems = computed(() => current.value?.warnings ?? [])
const run = computed(() => calibration.run ?? rack.lastRun)
const fitting = computed(() => run.value && (run.value.status === 'queued' || run.value.status === 'running'))

// --- readings + fit ---------------------------------------------------------------------------

async function importReadings(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  const res = await calibration.uploadFile(file, 'append')
  message.value = res
    ? res.report.ok
      ? `Imported ${res.stored} readings`
      : `${file.name} has problems: ${res.report.issues.length}`
    : calibration.error
  await rack.loadReadings()
  if (fileInput.value) fileInput.value.value = ''
}

async function fitNewVersion() {
  if (!current.value) return
  message.value = null
  try {
    await calibration.startFit({ line: current.value.line, activate: false } as never)
    void followFit()
  } catch (e) {
    message.value = e instanceof Error ? e.message : String(e)
  }
}
async function followFit() {
  const r = await calibration.refreshRun()
  if (r.status === 'queued' || r.status === 'running') {
    fitTimer = setTimeout(() => void followFit(), 700)
    return
  }
  await calibration.fetchModels()
  if (r.status === 'succeeded' && r.model_version) version.value = r.model_version
  message.value = r.status === 'succeeded' ? stepText(r.message) : `Fit failed: ${r.error ?? ''}`
}

async function activate() {
  if (!current.value) return
  await calibration.activate(current.value.version)
  await model.loadActive()
  message.value = `${current.value.line_name} @${current.value.revision} is now the active model`
}

// --- refill -----------------------------------------------------------------------------------

function startRefill() {
  const p = selected.value!
  refill.value = { capacity: p.capacity_ml ?? null, level: null, batch: p.batch_code ?? '' }
}
async function saveRefill() {
  const p = selected.value!
  const r = refill.value!
  busy.value = true
  try {
    if (r.capacity != null && r.capacity !== p.capacity_ml) await paints.update(p.id, { capacity_ml: r.capacity })
    unwrap(
      await api.POST('/api/v1/paints/{paint_id}/refill', {
        params: { path: { paint_id: p.id } },
        body: { level_ml: r.level, batch_code: r.batch && r.batch !== p.batch_code ? r.batch : null },
      }),
    )
    await paints.fetchAll()
    if (version.value != null) await rack.loadAccuracy(String(version.value))
    refill.value = null
    message.value = `${p.name} refilled`
  } catch (e) {
    message.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="flex-1 min-h-0 flex flex-col" aria-label="Models">
    <div class="flex-1 min-h-0 flex gap-6 px-6 pt-5 pb-5">
      <div class="flex-1 min-w-0 flex flex-col gap-4 min-h-0">
        <div class="flex items-center gap-3">
          <ModelMenu v-model="version" :items="calibration.models" />
        </div>

        <!-- readings strip: import, problems, fit progress -->
        <section class="flex items-center gap-5 px-5 py-3 bg-soft rounded-card" aria-label="Readings">
          <span class="flex flex-col">
            <span class="text-caption text-fg-3">Readings</span>
            <span class="n text-ui font-semibold">{{ rack.readings ?? '–' }}</span>
          </span>
          <button class="flex flex-col text-left rounded-tile focus-ring" :disabled="!problems.length" :aria-expanded="showProblems" @click="showProblems = !showProblems">
            <span class="text-caption text-fg-3">Problems</span>
            <span class="n text-ui font-semibold" :class="problems.length > 0 && 'text-warning'">{{ problems.length }}</span>
          </button>
          <span class="flex-1 min-w-0 flex flex-col gap-1">
            <span class="text-caption text-fg-3">Fit</span>
            <span v-if="fitting" class="flex items-center gap-3">
              <span class="flex-1 h-1 rounded-pill bg-line overflow-hidden" role="progressbar" :aria-valuenow="Math.round((run!.progress ?? 0) * 100)" aria-valuemin="0" aria-valuemax="100" aria-label="Fit progress"><span class="block h-full bg-accent" :style="{ width: `${Math.round((run!.progress ?? 0) * 100)}%` }" /></span>
              <span class="text-caption text-fg-2 truncate">{{ run!.message }}</span>
            </span>
            <span v-else-if="run" class="text-ui truncate" :title="stepText(run.message)">{{ stepText(run.message) }} · {{ formatDate(run.created_at) }}</span>
            <span v-else class="text-ui text-fg-3">Not fitted yet</span>
          </span>
          <input ref="fileInput" type="file" accept=".csv,text/csv" class="hidden" @change="importReadings" />
          <button class="btn-ghost focus-ring" :disabled="calibration.busy" @click="fileInput?.click()">Import readings</button>
          <button class="btn-ghost focus-ring" :disabled="!!fitting || !current" @click="fitNewVersion">Fit new version</button>
        </section>
        <ul v-if="showProblems && problems.length" class="m-0 -mt-2 px-5 py-2 list-none bg-soft rounded-card text-caption text-fg-2" aria-label="Problems">
          <li v-for="(p, i) in problems" :key="i" class="py-1">{{ p }}</li>
        </ul>

        <!-- rack -->
        <div class="flex-1 min-h-0 overflow-auto">
          <div class="grid grid-cols-[minmax(0,1.6fr)_110px_minmax(0,1fr)_minmax(0,1.3fr)_150px] gap-5 px-4 pb-2 border-b border-line text-caption text-fg-3" aria-hidden="true">
            <span>Paint</span><span>Channel</span><span>Level</span><span>Calibration accuracy</span><span>Status</span>
          </div>
          <div role="list" aria-label="Paints in this model">
            <RackRow v-for="p in rows" :key="p.id" role="listitem" :paint="p" :accuracy="accuracyOf(p.id)" :masstone-hex="rack.masstones[p.id]" :selected="p.id === selected?.id" @select="selectedId = p.id; refill = null" />
          </div>
        </div>
      </div>

      <aside class="w-detail flex-none flex flex-col min-h-0">
        <DetailCard v-if="selected" :label="selected.name">
          <template #swatch>
            <span class="pm-colour pm-ink block h-32 rounded-swatch" :style="{ background: selectedHex }" role="img" :aria-label="selected.name" />
          </template>
          <template #title>{{ selected.name }}</template>
          <template #meta>
            <ColourMeta :lab="selectedLab" :hex="selectedHex.toUpperCase()" :pigment="selected.pigment_code || undefined" :pigment-name="selected.name" />
          </template>
          <template #metric>
            <div v-if="selectedAccuracy?.median_de != null" class="flex items-end justify-between gap-3">
              <span class="flex flex-col gap-0.5">
                <span class="text-caption text-fg-3">Calibration accuracy · calibrated {{ formatDate(selectedAccuracy.calibrated_at) }}</span>
                <span class="n text-ui font-medium">Median ΔE {{ fmt(selectedAccuracy.median_de) }}</span>
              </span>
              <span class="text-ui font-semibold">{{ calibrationGrade(selectedAccuracy.median_de) }}</span>
            </div>
            <span v-else class="text-ui text-fg-3">Not calibrated in this model</span>
          </template>
          <template #facts>
            <div class="flex flex-col min-w-0"><dt class="text-caption text-fg-3">Mfr / batch</dt><dd class="m-0 text-ui font-semibold truncate">{{ selected.brand || '–' }}<template v-if="selected.batch_code"> · {{ selected.batch_code }}</template></dd></div>
            <div class="flex flex-col"><dt class="text-caption text-fg-3">Cost</dt><dd class="m-0 n text-ui font-semibold">{{ formatMoney((selected.cost_per_ml ?? 0) * 250, currency) }} / 250 ml</dd></div>
          </template>
          <template #visual>
            <div v-if="!refill" class="flex flex-col gap-2">
              <span class="text-caption text-fg-3">Level</span>
              <LevelBar :pct="selected.level_pct ?? null" :lab="selectedLab" :low="selected.low" size="card" :label="`${selected.name} level`" />
              <span class="flex justify-between text-caption">
                <span class="n" :class="selected.low ? 'text-warning font-semibold' : 'text-fg-2'">
                  <template v-if="selected.level_pct != null">{{ Math.round(selected.level_pct) }}% · {{ Math.round(selected.level_ml ?? 0) }} ml</template>
                  <template v-else>Not tracked</template>
                </span>
                <span v-if="selected.last_refill_at" class="text-fg-3">Refilled {{ formatDate(selected.last_refill_at) }}</span>
              </span>
            </div>
            <form v-else class="flex flex-col gap-2.5" aria-label="Refill" @submit.prevent="saveRefill">
              <label class="flex flex-col gap-1"><span class="text-caption text-fg-3">Reservoir size</span>
                <span class="field pm-field"><input v-model.number="refill.capacity" type="number" min="1" required aria-label="Reservoir size in ml" class="n flex-1 min-w-0 bg-transparent text-body outline-none" /><span class="text-fg-3 font-normal">ml</span></span></label>
              <label class="flex flex-col gap-1"><span class="text-caption text-fg-3">Level after refilling (empty: full)</span>
                <span class="field pm-field"><input v-model.number="refill.level" type="number" min="0" aria-label="Level after refilling in ml" class="n flex-1 min-w-0 bg-transparent text-body outline-none" /><span class="text-fg-3 font-normal">ml</span></span></label>
              <label class="flex flex-col gap-1"><span class="text-caption text-fg-3">Batch</span>
                <span class="field pm-field"><input v-model="refill.batch" aria-label="Batch code" class="flex-1 min-w-0 bg-transparent text-body outline-none" /></span></label>
              <button type="submit" class="hidden" />
            </form>
          </template>
        </DetailCard>
      </aside>
    </div>

    <footer class="h-footer flex-none flex items-center justify-end gap-3 px-6 border-t border-line">
      <span class="mr-auto text-ui text-fg-3 truncate" role="status">
        <template v-if="message">{{ message }}</template>
        <template v-else-if="current">{{ rows.length }} paints · {{ current.source === 'swatches' ? 'from swatch colours' : `${current.n_samples} samples` }}</template>
      </span>
      <button v-if="current && !current.active" class="btn-ghost !h-touch focus-ring" @click="activate">Make active</button>
      <template v-if="refill">
        <button class="btn-ghost !h-touch focus-ring" @click="refill = null">Cancel</button>
        <button class="btn-primary focus-ring" :disabled="busy || refill.capacity == null" @click="saveRefill">Save refill</button>
      </template>
      <button v-else-if="selected" class="btn-primary focus-ring" data-testid="refill" @click="startRefill">Refill {{ selected.name }}</button>
    </footer>
  </section>
</template>
