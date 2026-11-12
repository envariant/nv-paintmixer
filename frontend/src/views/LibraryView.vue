<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ColourMeta from '../components/ColourMeta.vue'
import ColourTile from '../components/ColourTile.vue'
import DeltaReadout from '../components/DeltaReadout.vue'
import DetailCard from '../components/DetailCard.vue'
import MixBar from '../components/MixBar.vue'
import PaletteBand from '../components/PaletteBand.vue'
import PaletteMenu from '../components/PaletteMenu.vue'
import { formatMoney, lab, labToCss, type Lab } from '../lib/colour'
import { APP_ICON } from '../lib/icons'
import { type Colour, type PaletteSummary, useLibraryStore } from '../stores/library'
import { usePaintsStore } from '../stores/paints'
import { useSettingsStore } from '../stores/settings'

/** Library: palette menu + search, palette band, colour tiles, detail card; palette builder. */
const router = useRouter()
const library = useLibraryStore()
const paints = usePaintsStore()
const settingsStore = useSettingsStore()

const paletteId = ref<number | null>(null)
const search = ref('')
const selectedId = ref<number | null>(null)
const summary = ref<PaletteSummary | null>(null)
const builder = ref<{ id: number | null; name: string; ids: number[] } | null>(null)
const addOpen = ref(false)
const saving = ref(false)
const message = ref<string | null>(null)

onMounted(async () => {
  await Promise.all([library.follow(), library.loadPalettes(), paints.fetchAll(), settingsStore.load()])
})
onBeforeUnmount(() => library.stop())

const palette = computed(() => library.palettes.find((p) => p.id === paletteId.value) ?? null)
const paletteColours = computed<Colour[]>(() =>
  (palette.value?.color_ids ?? []).map((id) => library.byId.get(id)).filter((c): c is Colour => !!c),
)
const shown = computed<Colour[]>(() => {
  const base = palette.value && !builder.value ? paletteColours.value : library.colours
  const q = search.value.trim().toLowerCase()
  return q ? base.filter((c) => c.name.toLowerCase().includes(q)) : base
})
const selected = computed<Colour | null>(
  () => library.byId.get(selectedId.value ?? -1) ?? shown.value[0] ?? null,
)
const currency = computed(() => settingsStore.settings?.currency ?? 'SGD')

watch(
  () => [paletteId.value, library.pending],
  async () => {
    summary.value = paletteId.value ? await library.summary(paletteId.value) : null
  },
)

const STATUS = { uncertain: 'uncertain', out: 'out-of-reach' } as const
const status = (c: Colour) => (c.match && c.match.reach !== 'within' ? STATUS[c.match.reach] : undefined)
const paint = (id: string) => paints.items.find((p) => p.id === id)
const bestLines = (c: Colour) =>
  (c.match?.best_components ?? []).map((x) => {
    const p = paint(x.paint_id)
    return { name: p?.name ?? x.paint_id, lab: (p?.model_lab ? lab(p.model_lab) : { L: 50, a: 0, b: 0 }) as Lab, fraction: x.fraction }
  })

// --- palette builder ------------------------------------------------------------------------

function startBuilder(fromPalette = false) {
  const p = fromPalette ? palette.value : null
  builder.value = { id: p?.id ?? null, name: p?.name ?? 'New palette', ids: [...(p?.color_ids ?? [])] }
}
function toggle(id: number) {
  const b = builder.value!
  b.ids = b.ids.includes(id) ? b.ids.filter((x) => x !== id) : [...b.ids, id]
}
const builderReach = computed(() => {
  const ms = (builder.value?.ids ?? []).map((id) => library.byId.get(id)?.match)
  return {
    within: ms.filter((m) => m?.reach === 'within').length,
    uncertain: ms.filter((m) => m?.reach === 'uncertain').length,
    out: ms.filter((m) => m?.reach === 'out').length,
    pending: ms.filter((m) => !m).length,
  }
})
async function saveBuilder() {
  const b = builder.value!
  saving.value = true
  try {
    const p = await library.savePalette(b.id, b.name.trim() || 'Palette', b.ids)
    builder.value = null
    paletteId.value = p.id
  } catch (e) {
    message.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

async function addTo(pid: number | null) {
  addOpen.value = false
  const c = selected.value
  if (!c) return
  if (pid === null) {
    builder.value = { id: null, name: 'New palette', ids: [c.id] }
    return
  }
  const p = library.palettes.find((x) => x.id === pid)!
  if (!p.color_ids.includes(c.id)) await library.savePalette(p.id, p.name, [...p.color_ids, c.id])
  message.value = `Added ${c.name} to ${p.name}`
}

function exportPalette() {
  const rows = [['name', 'hex', 'L', 'a', 'b', 'best_de', 'reach']]
  for (const c of paletteColours.value)
    rows.push([c.name, c.hex, ...c.lab.map((v) => v.toFixed(2)), c.match ? c.match.de.toFixed(2) : '', c.match?.reach ?? ''])
  const csv = rows.map((r) => r.map((v) => (/[",]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v)).join(',')).join('\n')
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([csv + '\n'], { type: 'text/csv' }))
  a.download = `${palette.value?.name ?? 'palette'}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}
</script>

<template>
  <section class="flex-1 min-h-0 flex flex-col" aria-label="Library">
    <div class="flex-1 min-h-0 flex gap-6 px-6 pt-5 pb-5">
      <!-- tiles -->
      <div class="flex-1 min-w-0 flex flex-col gap-4 min-h-0">
        <div class="flex items-center gap-3">
          <PaletteMenu
            v-if="!builder"
            v-model="paletteId"
            :items="library.palettes"
            :colours="library.byId"
            @new="startBuilder(false)"
          />
          <span v-else class="text-ui font-semibold">Choose colours for the palette</span>
          <label class="flex-1 max-w-[320px] field pm-field">
            <input v-model="search" type="search" aria-label="Search colours" placeholder="Search" class="flex-1 min-w-0 bg-transparent text-body font-normal outline-none" />
          </label>
          <span v-if="library.pending" class="ml-auto text-caption text-fg-3" role="status">
            Matching {{ library.pending }} colours…
          </span>
        </div>

        <PaletteBand
          v-if="palette && !builder"
          :palette="palette"
          :colours="paletteColours"
          :summary="summary"
          @edit="startBuilder(true)"
          @export="exportPalette"
        />

        <div class="flex-1 min-h-0 overflow-auto -mx-2 px-2 pt-2 pb-2">
          <div class="grid grid-cols-[repeat(auto-fill,minmax(156px,1fr))] gap-4" role="list" aria-label="Colours">
            <ColourTile
              v-for="c in shown"
              :key="c.id"
              role="listitem"
              :name="c.name"
              :lab="lab(c.lab)"
              :hex="c.hex.toUpperCase()"
              :status="status(c)"
              :selected="!builder && c.id === selected?.id"
              :badge="builder ? (builder.ids.includes(c.id) ? 'added' : 'add') : undefined"
              @select="builder ? toggle(c.id) : (selectedId = c.id)"
            />
          </div>
          <p v-if="!shown.length" class="m-0 py-8 text-ui text-fg-3">No colours match “{{ search }}”.</p>
        </div>
      </div>

      <!-- detail card / builder panel -->
      <aside class="w-detail flex-none flex flex-col min-h-0">
        <div v-if="builder" class="flex flex-col gap-4 min-h-0 px-5 py-4 bg-soft rounded-stage" aria-label="Palette builder">
          <label class="flex flex-col gap-1">
            <span class="text-caption text-fg-3">Palette name</span>
            <span class="field pm-field"><input v-model="builder.name" aria-label="Palette name" class="flex-1 min-w-0 bg-transparent text-body font-semibold outline-none" /></span>
          </label>
          <span class="n text-caption text-fg-3">
            {{ builder.ids.length }} colours · {{ builderReach.within }} within reach<template v-if="builderReach.uncertain"> · {{ builderReach.uncertain }} uncertain</template><template v-if="builderReach.out"> · {{ builderReach.out }} out of reach</template>
          </span>
          <ol class="m-0 p-0 list-none flex-1 min-h-0 overflow-auto flex flex-col">
            <li v-for="id in builder.ids" :key="id" class="flex items-center gap-2.5 py-1.5 border-b border-line">
              <span class="pm-colour pm-ink w-5 h-5 rounded-swatch flex-none" :style="{ background: labToCss(lab(library.byId.get(id)!.lab)).css }" />
              <span class="flex-1 min-w-0 truncate text-ui">{{ library.byId.get(id)!.name }}</span>
              <button class="w-8 h-8 inline-flex items-center justify-center rounded-pill hover:bg-page focus-ring" :aria-label="`Remove ${library.byId.get(id)!.name}`" @click="toggle(id)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path :d="APP_ICON.close" /></svg>
              </button>
            </li>
            <li v-if="!builder.ids.length" class="py-3 text-ui text-fg-3">Tap colours to add them.</li>
          </ol>
        </div>

        <DetailCard v-else-if="selected" :label="selected.name">
          <template #swatch>
            <span class="pm-colour pm-ink block h-40 rounded-swatch" :style="{ background: labToCss(lab(selected.lab)).css }" role="img" :aria-label="selected.name" />
          </template>
          <template #title>{{ selected.name }}</template>
          <template #meta><ColourMeta :lab="lab(selected.lab)" :hex="selected.hex.toUpperCase()" /></template>
          <template #metric>
            <div v-if="selected.match" class="flex items-end justify-between gap-3">
              <span class="flex flex-col gap-0.5">
                <span class="text-caption text-fg-3">Best match</span>
                <DeltaReadout :value="selected.match.de" :uncertainty="selected.match.uncertainty_de ?? undefined" />
              </span>
              <span class="text-caption font-semibold" :class="{ 'text-warning': selected.match.reach === 'uncertain', 'text-danger': selected.match.reach === 'out', 'text-fg-3': selected.match.reach === 'within' }">
                {{ { within: 'Within reach', uncertain: 'Near the edge', out: 'Out of reach' }[selected.match.reach] }}
              </span>
            </div>
            <span v-else class="text-ui text-fg-3">Finding the best match…</span>
          </template>
          <template v-if="selected.match" #facts>
            <div class="flex flex-col"><dt class="text-caption text-fg-3">Paints</dt><dd class="m-0 n text-body font-semibold">{{ selected.match.n_paints }}</dd></div>
            <div class="flex flex-col"><dt class="text-caption text-fg-3">Cost · 250 ml</dt><dd class="m-0 n text-body font-semibold">{{ formatMoney(selected.match.cost_per_250ml, currency) }}</dd></div>
          </template>
          <template v-if="selected.match" #visual>
            <MixBar :lines="bestLines(selected)" label="Best mix" />
          </template>
        </DetailCard>
      </aside>
    </div>

    <footer class="h-footer flex-none flex items-center justify-end gap-3 px-6 border-t border-line">
      <span class="mr-auto text-ui text-fg-3" role="status">
        <template v-if="message">{{ message }}</template>
        <template v-else-if="!builder">{{ shown.length }} colours<template v-if="palette"> in {{ palette.name }}</template></template>
      </span>
      <template v-if="builder">
        <button class="btn-ghost !h-touch focus-ring" @click="builder = null">Cancel</button>
        <button class="btn-primary focus-ring" :disabled="saving" data-testid="save-palette" @click="saveBuilder">Save palette</button>
      </template>
      <template v-else-if="selected">
        <div class="relative">
          <button class="btn-ghost !h-touch focus-ring" aria-haspopup="listbox" :aria-expanded="addOpen" @click="addOpen = !addOpen">Add to palette</button>
          <div v-if="addOpen" role="listbox" aria-label="Add to palette" class="absolute z-20 bottom-[52px] right-0 w-[260px] flex flex-col py-1.5 bg-page border border-line rounded-option shadow-popover">
            <button v-for="p in library.palettes" :key="p.id" role="option" class="px-4 h-touch text-ui text-left hover:bg-soft focus-ring" @click="addTo(p.id)">{{ p.name }}</button>
            <button role="option" class="px-4 h-touch text-ui text-left font-medium text-accent-fg hover:bg-soft focus-ring" @click="addTo(null)">+ New palette</button>
          </div>
        </div>
        <button class="btn-primary focus-ring" data-testid="mix-this" @click="router.push({ name: 'mix', query: { color: String(selected.id) } })">
          Mix this colour
        </button>
      </template>
    </footer>
  </section>
</template>
