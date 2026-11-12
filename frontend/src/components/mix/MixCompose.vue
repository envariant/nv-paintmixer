<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError, unwrap } from '../../api/client'
import { fmt, formatMoney, lab, type Lab } from '../../lib/colour'
import { ICON } from '../../lib/icons'
import { type Candidate, useMixerStore } from '../../stores/mixer'
import { useModelStore } from '../../stores/model'
import { usePaintsStore } from '../../stores/paints'
import { useRunStore } from '../../stores/run'
import { useSettingsStore } from '../../stores/settings'
import ColourMeta from '../ColourMeta.vue'
import DeltaReadout from '../DeltaReadout.vue'
import DetailsPane from '../DetailsPane.vue'
import InkWell from '../InkWell.vue'
import LightTabs from '../LightTabs.vue'
import MixBar from '../MixBar.vue'
import MixOption, { type Mix } from '../MixOption.vue'
import ModeTabs from '../ModeTabs.vue'
import SolveSettings from '../SolveSettings.vue'
import SortTabs from '../SortTabs.vue'
import StageCompare from '../StageCompare.vue'
import TargetEntry from './TargetEntry.vue'

/** Mix: the stage joined to a pale card (target + solve settings | ways to mix it), footer with Dispense. */
const route = useRoute()
const router = useRouter()
const mixer = useMixerStore()
const settingsStore = useSettingsStore()
const model = useModelStore()
const paints = usePaintsStore()
const run = useRunStore()

const SURROUND: Lab = { L: 49.4, a: 0, b: 0 } // N5: the stage before there is a target
const WAVELENGTHS = Array.from({ length: 36 }, (_, i) => 380 + 10 * i)

const targetName = ref('')
const targetLab = ref<Lab | null>(null)
const mode = ref<'split' | 'concentric' | 'hover'>('split')
const sort = ref<'closest' | 'fewest' | 'cost'>('closest')
const details = ref(false)
const gamut = ref<[number, number][]>([])
const dispensing = ref(false)
const dispenseError = ref<string | null>(null)

// solve settings (Match under also moves the preview; the preview can then change on its own)
const matchUnder = ref('D65')
const maxPaints = ref(4)
const volume = ref(100)
const paintsInModel = computed(() => model.active?.paint_ids.length ?? 1)
const machineMax = computed(() => settingsStore.settings?.machine_max_batch_ml ?? 250)
const currency = computed(() => settingsStore.settings?.currency ?? 'SGD')

onMounted(async () => {
  const [s] = await Promise.all([settingsStore.load(), model.loadActive(), paints.fetchAll()])
  if (s) {
    matchUnder.value = s.illuminant ?? 'D65'
    mixer.preview = matchUnder.value
    volume.value = Math.min(s.batch_volume_ml ?? 100, s.machine_max_batch_ml ?? 250)
  }
  maxPaints.value = Math.min(s?.max_paints ?? 4, paintsInModel.value)
  await loadTargetFromRoute()
})

watch(() => route.query.color, () => void loadTargetFromRoute())

async function loadTargetFromRoute() {
  const id = Number(route.query.color)
  if (!id) {
    if (mixer.mode === 'library' || !targetLab.value) restoreTyped()
    return
  }
  try {
    const c = unwrap(await api.GET('/api/v1/colors/{color_id}', { params: { path: { color_id: id } } }))
    mixer.mode = 'library'
    mixer.libraryId = c.id
    targetName.value = c.name
    targetLab.value = lab(c.lab)
  } catch {
    targetLab.value = null
  }
}

/** Keep a typed target across visits (the store holds it). */
function restoreTyped() {
  if (mixer.result && mixer.mode !== 'library') {
    targetName.value = mixer.result.target_name || 'Custom colour'
    targetLab.value = lab(mixer.result.target_lab)
  }
}

function setTyped(kind: 'hex' | 'lab', value: string) {
  mixer.mode = kind
  mixer.value = value
  mixer.libraryId = null
  targetName.value = 'Custom colour'
  targetLab.value = null // known after the solve
  if (route.query.color) void router.replace({ query: {} })
  queueSolve()
}

function changeTarget() {
  mixer.clear()
  targetLab.value = null
  targetName.value = ''
  if (route.query.color) void router.replace({ query: {} })
}

// --- solving ----------------------------------------------------------------------------------

let timer: ReturnType<typeof setTimeout> | null = null
function queueSolve() {
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => void solveNow(), 300)
}
async function solveNow() {
  if (!mixer.target) return
  mixer.constraints = {
    illuminant: matchUnder.value as never,
    max_paints: maxPaints.value,
    batch_volume_ml: volume.value,
    top_n: 3,
  }
  await mixer.solve()
  if (mixer.result) {
    targetLab.value = lab(mixer.result.target_lab)
    if (!targetName.value) targetName.value = mixer.result.target_name || 'Custom colour'
  }
}
watch(
  () => [mixer.target ? JSON.stringify(mixer.target) : null, maxPaints.value, volume.value, matchUnder.value],
  () => queueSolve(),
)
watch(matchUnder, (code) => {
  mixer.preview = code
})
watch(
  () => mixer.preview,
  () => void mixer.loadAppearance(),
)

// --- what the screen shows ----------------------------------------------------------------------

const paintLab = (id: string): Lab => {
  const p = paints.items.find((x) => x.id === id)
  return p?.model_lab ? lab(p.model_lab) : SURROUND
}

const mixes = computed<(Mix & { rank: number; candidate: Candidate; uncertainty?: number })[]>(() => {
  const r = mixer.result
  if (!r) return []
  const app = mixer.appearance
  return r.candidates.map((c, i) => ({
    id: String(c.rank),
    rank: c.rank,
    candidate: c,
    name: `Mix ${String.fromCharCode(65 + i)}`,
    tag: c.tags?.[0] ?? '',
    lab: lab(app?.spectra[i]?.display_lab ?? c.predicted_lab),
    dE: app?.de2000[i] ?? c.de2000,
    uncertainty: c.uncertainty_de ?? undefined,
    paints: c.components.map((x) => ({ name: x.name, lab: paintLab(x.paint_id), fraction: x.fraction })),
    cost: c.cost,
  }))
})
const sorted = computed(() => {
  const m = [...mixes.value]
  if (sort.value === 'closest') m.sort((a, b) => a.dE - b.dE)
  if (sort.value === 'fewest') m.sort((a, b) => a.paints.length - b.paints.length || a.dE - b.dE)
  if (sort.value === 'cost') m.sort((a, b) => a.cost - b.cost)
  return m
})
const selected = computed(() => mixes.value.find((m) => m.rank === mixer.selectedRank) ?? mixes.value[0] ?? null)
const cheapest = computed(() => Math.min(...mixes.value.map((m) => m.cost)))
const stageTarget = computed<Lab>(() =>
  mixer.appearance ? lab(mixer.appearance.reference.display_lab) : (targetLab.value ?? SURROUND),
)
const outOfReach = computed(() => mixer.result?.in_gamut === false)
const margin = computed(() => mixer.result?.gamut_margin_de ?? null)

watch(
  () => [details.value, model.active?.version, targetLab.value?.L],
  async () => {
    if (details.value && model.active && targetLab.value)
      gamut.value = await model.outlineAt(model.active.version, targetLab.value.L)
  },
)

const curve = (r: number[]) =>
  r.map((v, i) => ({ nm: WAVELENGTHS[i]!, r: v })).filter((p) => p.nm >= 400 && p.nm <= 700)
const detailMix = computed(() => {
  const m = selected.value
  if (!m) return null
  return {
    name: m.name,
    lab: m.lab,
    dE: m.dE,
    volumeMl: mixer.result?.batch_volume_ml ?? volume.value,
    paints: m.candidate.components.map((c) => ({
      name: c.name,
      lab: paintLab(c.paint_id),
      fraction: c.fraction,
      ml: c.volume_ml,
      sgd: c.cost,
    })),
  }
})

const errorText = computed(() => {
  const e = mixer.error
  if (!e) return ''
  if (e.code === 'no_active_model') return 'There is no calibrated model yet.'
  if (e.code === 'empty_pool') return 'No paints are loaded on the machine.'
  return e.message
})

// --- dispense ---------------------------------------------------------------------------------

async function dispense() {
  const m = selected.value
  if (!m) return
  dispensing.value = true
  dispenseError.value = null
  try {
    const job = await mixer.createJob(m.candidate, targetName.value)
    run.job = job
    await run.dispense()
    await router.push({ query: { ...route.query, job: String(job.id) } })
  } catch (e) {
    dispenseError.value = e instanceof ApiError || e instanceof Error ? e.message : String(e)
  } finally {
    dispensing.value = false
  }
}
</script>

<template>
  <section class="flex-1 min-h-0 flex flex-col" aria-label="Mix">
    <div class="flex-1 min-h-0 flex flex-col px-6 pt-5 pb-5">
      <StageCompare
        :target="stageTarget"
        :candidate="selected?.lab ?? null"
        :mode="mode"
        :illuminant="mixer.preview"
        :target-label="targetLab ? 'Target' : 'No target yet'"
        :candidate-label="selected?.name ?? 'Mix'"
      >
        <template #header-left><LightTabs v-model="mixer.preview" /></template>
        <template #header-right><ModeTabs v-model="mode" /></template>
        <template #empty>
          <TargetEntry v-if="!mixer.target" @target="setTyped" />
          <span v-else-if="mixer.status === 'solving' || mixer.status === 'idle'" class="on-surround text-ui" role="status">
            Finding a mix…
          </span>
          <span v-else-if="mixer.status === 'error'" class="flex flex-col items-center gap-3" role="alert">
            <span class="on-surround text-ui text-center">{{ errorText }}</span>
            <RouterLink v-if="mixer.error?.code === 'no_active_model'" to="/models" class="btn-primary focus-ring">Go to Models</RouterLink>
            <button v-else class="btn-primary focus-ring" @click="solveNow">Try again</button>
          </span>
        </template>
      </StageCompare>

      <div class="relative flex-none bg-soft rounded-b-stage px-stage">
        <div class="relative grid grid-cols-[minmax(0,5fr)_minmax(0,7fr)] gap-10 pt-5 pb-4">
          <!-- target + solve settings -->
          <div class="flex flex-col gap-4 min-w-0">
            <div class="flex flex-col gap-2 min-w-0">
              <span class="flex justify-between text-caption text-fg-3">
                Target
                <button v-if="targetLab" class="btn-link !text-caption focus-ring" @click="changeTarget">Change</button>
              </span>
              <div class="flex items-center gap-3 min-w-0">
                <InkWell v-if="targetLab" :a="stageTarget" :size="48" :label="`Target ${targetName}`" />
                <div class="flex flex-col min-w-0">
                  <span class="text-display font-semibold truncate">{{ targetLab ? targetName : 'No target' }}</span>
                  <ColourMeta v-if="targetLab" :lab="targetLab" />
                </div>
              </div>
            </div>
            <SolveSettings
              v-model:illuminant="matchUnder"
              v-model:max-paints="maxPaints"
              v-model:volume="volume"
              :paints-in-model="paintsInModel"
              :machine-max-ml="machineMax"
            />
          </div>

          <!-- ways to mix it -->
          <div class="flex flex-col gap-2 min-w-0">
            <div class="flex items-center justify-between gap-3">
              <span class="text-ui font-semibold">Ways to mix it</span>
              <SortTabs
                v-model="sort"
                label="Sort ways to mix it"
                :options="[
                  { id: 'closest', label: 'Closest' },
                  { id: 'fewest', label: 'Fewest paints' },
                  { id: 'cost', label: 'Cost' },
                ]"
              />
            </div>
            <div v-if="sorted.length" class="flex flex-col gap-1 -mx-4" role="list" aria-label="Ways to mix it">
              <MixOption
                v-for="m in sorted"
                :key="m.id"
                role="listitem"
                :mix="m"
                :target="stageTarget"
                :selected="m.rank === selected?.rank"
                :well-mode="mode"
                :cheapest="cheapest"
                :currency="currency"
                @select="mixer.selectedRank = m.rank"
              />
            </div>
            <p v-else class="m-0 py-6 text-ui text-fg-3">
              {{ mixer.status === 'solving' ? 'Finding a mix…' : mixer.target ? '' : 'Mixes appear here once there is a target.' }}
            </p>
          </div>

          <DetailsPane
            v-if="details && detailMix && targetLab"
            :mix="detailMix"
            :target="targetLab"
            :target-curve="curve(mixer.result!.reference_spectrum)"
            :mix-curve="curve(selected!.candidate.predicted_spectrum)"
            :gamut="gamut"
            :margin="margin ?? 0"
          />
        </div>

        <div class="flex items-center justify-between gap-4 h-14 border-t border-line">
          <button
            class="btn-link inline-flex items-center gap-1 focus-ring"
            :disabled="!selected"
            :aria-expanded="details"
            @click="details = !details"
          >
            Formula, spectrum and reach
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" :class="details && 'rotate-180'"><path :d="ICON.chevron" /></svg>
          </button>
          <span v-if="selected" class="flex items-center gap-4 text-ui" data-testid="verdict">
            <span v-if="outOfReach" class="text-warning font-semibold">Out of reach · this is the nearest mix</span>
            <span v-else-if="margin != null" class="n text-fg-3">Margin to the edge ΔE {{ fmt(margin, 1) }}</span>
            <DeltaReadout :value="selected.dE" :uncertainty="selected.uncertainty" />
          </span>
        </div>
      </div>
    </div>

    <footer class="h-footer flex-none flex items-center gap-6 px-6 border-t border-line">
      <MixBar v-if="selected" :lines="selected.paints" :label="`${selected.name} composition`" />
      <span v-else class="flex-1" />
      <span v-if="dispenseError" class="text-ui text-danger" role="alert">{{ dispenseError }}</span>
      <button
        class="btn-primary focus-ring"
        :disabled="!selected || dispensing"
        :class="(!selected || dispensing) && 'opacity-60'"
        data-testid="dispense"
        @click="dispense"
      >
        <template v-if="selected">Dispense {{ selected.name }} · {{ formatMoney(selected.cost, currency) }}</template>
        <template v-else>Dispense</template>
      </button>
    </footer>
  </section>
</template>
