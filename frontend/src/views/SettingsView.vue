<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, type Schemas } from '../api/client'
import DecimalField from '../components/DecimalField.vue'
import IlluminantField from '../components/IlluminantField.vue'
import StepperField from '../components/StepperField.vue'
import { cctTint } from '../lib/colour'
import { ICON } from '../lib/icons'
import { applyTheme, savedTheme, type Theme } from '../lib/theme'
import { useIlluminantsStore } from '../stores/illuminants'
import { useModelStore } from '../stores/model'
import { useSettingsStore } from '../stores/settings'

/** Settings: two-column sections; footer with the unsaved count · Discard · Save. */
type Draft = Required<Pick<Schemas['AppSettingsRead'],
  | 'illuminant' | 'accept_tolerance_de' | 'check_illuminants'
  | 'dispenser_channels' | 'machine_max_batch_ml' | 'batch_volume_ml' | 'dispenser_resolution_ml'
  | 'dispenser_transport' | 'dispenser_address' | 'low_level_warn_pct'
  | 'currency' | 'max_paints'
  | 'saunderson_k1' | 'saunderson_k2' | 'min_fraction' | 'out_of_gamut_de'>> & {
  weights: Required<Schemas['SolverWeights']>
}

const store = useSettingsStore()
const illuminants = useIlluminantsStore()
const model = useModelStore()
// the stepper runs 1…N over the active model's paints (8 until a model is loaded)
const paintsInModel = computed(() => model.active?.paint_ids.length ?? 8)
const saved = ref<Draft | null>(null)
const draft = ref<Draft | null>(null)
const theme = ref<Theme>(savedTheme())
const savedThemeValue = ref<Theme>(savedTheme())
const advanced = ref(false)
const saving = ref(false)
const message = ref<string | null>(null)
const error = ref<string | null>(null)

const KEYS = [
  'illuminant', 'accept_tolerance_de', 'check_illuminants',
  'dispenser_channels', 'machine_max_batch_ml', 'batch_volume_ml', 'dispenser_resolution_ml',
  'dispenser_transport', 'dispenser_address', 'low_level_warn_pct',
  'currency', 'max_paints',
  'saunderson_k1', 'saunderson_k2', 'min_fraction', 'out_of_gamut_de', 'weights',
] as const

function pick(s: Schemas['AppSettingsRead']): Draft {
  return JSON.parse(JSON.stringify(Object.fromEntries(KEYS.map((k) => [k, s[k]])))) as Draft
}
onMounted(async () => {
  void model.loadActive()
  const s = await store.load()
  if (s) {
    saved.value = pick(s)
    draft.value = pick(s)
  }
})

const changed = computed<string[]>(() => {
  if (!draft.value || !saved.value) return []
  const keys = KEYS.filter((k) => JSON.stringify(draft.value![k]) !== JSON.stringify(saved.value![k])) as string[]
  return theme.value !== savedThemeValue.value ? [...keys, 'theme'] : keys
})

function discard() {
  draft.value = saved.value ? (JSON.parse(JSON.stringify(saved.value)) as Draft) : null
  theme.value = savedThemeValue.value
  error.value = null
}

async function save() {
  if (!draft.value) return
  saving.value = true
  error.value = null
  try {
    const patch = Object.fromEntries(changed.value.filter((k) => k !== 'theme').map((k) => [k, draft.value![k as keyof Draft]]))
    if (Object.keys(patch).length) {
      const s = await store.save(patch as Schemas['AppSettingsUpdate'])
      saved.value = pick(s)
      draft.value = pick(s)
    }
    applyTheme(theme.value)
    savedThemeValue.value = theme.value
    message.value = 'Saved'
  } catch (e) {
    error.value = e instanceof ApiError || e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

function toggleCheck(code: string) {
  const d = draft.value!
  const cur = d.check_illuminants as string[]
  d.check_illuminants = (cur.includes(code) ? cur.filter((c) => c !== code) : [...cur, code].slice(-6)) as Draft['check_illuminants']
}
const TRANSPORTS = [
  { id: 'none', label: 'Simulator' },
  { id: 'tcp', label: 'Wi-Fi' },
  { id: 'serial', label: 'USB / Bluetooth' },
] as const
const THEMES = [
  { id: 'system', label: 'System' },
  { id: 'light', label: 'Light' },
  { id: 'dark', label: 'Dark' },
] as const
</script>

<template>
  <section class="flex-1 min-h-0 flex flex-col" aria-label="Settings">
    <div v-if="draft" class="flex-1 min-h-0 overflow-auto px-6 py-5">
      <div class="max-w-[900px] flex flex-col">
        <!-- Judging colour -->
        <section class="grid grid-cols-[220px_minmax(0,1fr)] gap-8 py-6 border-b border-line" aria-labelledby="s-judging">
          <h2 id="s-judging" class="m-0 text-body font-semibold">Judging colour</h2>
          <div class="grid grid-cols-[160px_minmax(0,1fr)] items-center gap-x-4 gap-y-3 text-ui">
            <span class="text-fg-2">Match in</span>
            <IlluminantField v-model="draft.illuminant" label="Match in" />
            <span class="text-fg-2">Accept within</span>
            <DecimalField v-model="draft.accept_tolerance_de" :min="0.1" :max="5" unit="ΔE" label="Accept tolerance (ΔE)" />
            <span class="self-start pt-2 text-fg-2">Also check under</span>
            <div class="flex flex-col gap-2" role="group" aria-label="Also check under">
              <div v-for="s in illuminants.series" :key="s.id" class="flex flex-wrap items-center gap-1">
                <span class="w-12 text-caption text-fg-3">{{ s.id }}</span>
                <button
                  v-for="m in s.members"
                  :key="m.code"
                  :aria-pressed="(draft.check_illuminants as string[]).includes(m.code)"
                  class="h-tab pl-1.5 pr-2.5 rounded-pill inline-flex items-center gap-1.5 text-caption font-medium focus-ring"
                  :class="(draft.check_illuminants as string[]).includes(m.code) ? 'bg-fg text-page' : 'border border-line hover:bg-soft'"
                  @click="toggleCheck(m.code)"
                >
                  <span class="w-3 h-3 rounded-full shadow-[inset_0_0_0_1px_rgb(0_0_0/0.25)]" :style="{ background: cctTint(m.cct) }" />{{ m.code }}
                </button>
              </div>
            </div>
          </div>
        </section>

        <!-- Machine -->
        <section class="grid grid-cols-[220px_minmax(0,1fr)] gap-8 py-6 border-b border-line" aria-labelledby="s-machine">
          <h2 id="s-machine" class="m-0 text-body font-semibold">Machine</h2>
          <div class="grid grid-cols-[160px_minmax(0,1fr)] items-center gap-x-4 gap-y-3 text-ui">
            <span class="text-fg-2">Connection</span>
            <div class="seg justify-self-start" role="radiogroup" aria-label="Dispenser connection">
              <button v-for="t in TRANSPORTS" :key="t.id" role="radio" :aria-checked="draft.dispenser_transport === t.id" class="focus-ring" @click="draft.dispenser_transport = t.id">{{ t.label }}</button>
            </div>
            <template v-if="draft.dispenser_transport !== 'none'">
              <span class="text-fg-2">{{ draft.dispenser_transport === 'tcp' ? 'Address' : 'Port' }}</span>
              <label class="field pm-field">
                <input v-model="draft.dispenser_address" :aria-label="draft.dispenser_transport === 'tcp' ? 'Dispenser address (host:port)' : 'Serial port (port@baud)'" :placeholder="draft.dispenser_transport === 'tcp' ? '192.168.1.40:3333' : '/dev/ttyUSB0@115200'" class="n flex-1 min-w-0 bg-transparent text-body font-semibold outline-none" />
              </label>
            </template>
            <span class="text-fg-2">Channels</span>
            <StepperField v-model="draft.dispenser_channels" :min="1" :max="64" label="Dispenser channels" />
            <span class="text-fg-2">Maximum volume</span>
            <DecimalField v-model="draft.machine_max_batch_ml" :min="1" :step="5" unit="ml" label="Largest volume the cup holds" />
            <span class="text-fg-2">Default volume</span>
            <DecimalField v-model="draft.batch_volume_ml" :min="1" :max="draft.machine_max_batch_ml" :step="5" unit="ml" label="Default batch volume" />
            <span class="text-fg-2">Dispense step</span>
            <DecimalField v-model="draft.dispenser_resolution_ml" :min="0.001" :step="0.01" unit="ml" label="Smallest dispensable step" />
            <span class="text-fg-2">Warn below</span>
            <DecimalField v-model="draft.low_level_warn_pct" :min="0" :max="100" :step="5" unit="% level" label="Low level warning" />
          </div>
        </section>

        <!-- Cost & display -->
        <section class="grid grid-cols-[220px_minmax(0,1fr)] gap-8 py-6 border-b border-line" aria-labelledby="s-display">
          <h2 id="s-display" class="m-0 text-body font-semibold">Cost &amp; display</h2>
          <div class="grid grid-cols-[160px_minmax(0,1fr)] items-center gap-x-4 gap-y-3 text-ui">
            <span class="text-fg-2">Currency</span>
            <label class="field pm-field">
              <input v-model="draft.currency" maxlength="3" aria-label="Currency code" class="n flex-1 min-w-0 bg-transparent text-body font-semibold uppercase outline-none" />
            </label>
            <span class="text-fg-2">Max paints</span>
            <StepperField v-model="draft.max_paints" :min="1" :max="Math.max(paintsInModel, draft.max_paints)" label="Default maximum number of paints" />
            <span class="text-fg-2">Theme</span>
            <div class="seg justify-self-start" role="radiogroup" aria-label="Theme">
              <button v-for="t in THEMES" :key="t.id" role="radio" :aria-checked="theme === t.id" class="focus-ring" @click="theme = t.id">{{ t.label }}</button>
            </div>
          </div>
        </section>

        <!-- Advanced colour science (collapsed) -->
        <section class="grid grid-cols-[220px_minmax(0,1fr)] gap-8 py-6" aria-labelledby="s-advanced">
          <h2 id="s-advanced" class="m-0">
            <button class="inline-flex items-center gap-1.5 text-body font-semibold rounded-pill focus-ring" :aria-expanded="advanced" @click="advanced = !advanced">
              Advanced colour science
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" :class="advanced && 'rotate-180'"><path :d="ICON.chevron" /></svg>
            </button>
          </h2>
          <div v-if="advanced" class="grid grid-cols-[160px_minmax(0,1fr)] items-center gap-x-4 gap-y-3 text-ui">
            <span class="text-fg-2">Observer</span>
            <span class="n text-body font-semibold" data-testid="observer">{{ store.settings?.observer }} <span class="text-caption font-normal text-fg-3">· fixed</span></span>
            <span class="text-fg-2">Geometry</span>
            <span class="n text-body font-semibold" data-testid="geometry">{{ store.settings?.geometry }} <span class="text-caption font-normal text-fg-3">· fixed</span></span>
            <span class="text-fg-2">Saunderson k1</span>
            <DecimalField v-model="draft.saunderson_k1" :min="0" :max="0.99" :step="0.01" label="Saunderson k1" />
            <span class="text-fg-2">Saunderson k2</span>
            <DecimalField v-model="draft.saunderson_k2" :min="0" :max="0.99" :step="0.01" label="Saunderson k2" />
            <span class="text-fg-2">Smallest share</span>
            <DecimalField v-model="draft.min_fraction" :min="0" :max="0.49" :step="0.01" label="Smallest share of a paint in a mix" />
            <span class="text-fg-2">Out of reach above</span>
            <DecimalField v-model="draft.out_of_gamut_de" :min="0.1" :max="20" unit="ΔE" label="Out of reach above (ΔE)" />
            <span class="text-fg-2">Weights</span>
            <div class="grid grid-cols-4 gap-3">
              <DecimalField v-model="draft.weights.de" :min="0" label="Weight of ΔE" unit="ΔE" />
              <DecimalField v-model="draft.weights.n_paints" :min="0" :step="0.01" label="Weight of the number of paints" unit="paints" />
              <DecimalField v-model="draft.weights.cost" :min="0" label="Weight of cost" unit="cost" />
              <DecimalField v-model="draft.weights.metamerism" :min="0" :step="0.01" label="Weight of metamerism" unit="meta" />
            </div>
          </div>
        </section>
      </div>
    </div>
    <div v-else class="flex-1 p-6 text-ui text-fg-3">{{ store.error ?? 'Loading…' }}</div>

    <footer class="h-footer flex-none flex items-center justify-end gap-3 px-6 border-t border-line">
      <span class="mr-auto text-ui" role="status" :class="error ? 'text-danger' : 'text-fg-3'">
        <template v-if="error">{{ error }}</template>
        <template v-else-if="changed.length">{{ changed.length }} unsaved {{ changed.length === 1 ? 'change' : 'changes' }}</template>
        <template v-else-if="message">{{ message }}</template>
      </span>
      <button class="btn-ghost !h-touch focus-ring" :disabled="!changed.length" @click="discard">Discard</button>
      <button class="btn-primary focus-ring" :disabled="!changed.length || saving" :class="!changed.length && 'opacity-60'" data-testid="save-settings" @click="save">Save</button>
    </footer>
  </section>
</template>
