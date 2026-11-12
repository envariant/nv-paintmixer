# PaintMixer — Vue 3 + Tailwind handoff

This is the single handoff for the chosen design (formerly "Option B · Minimal"). The earlier "Instrument" option is retired.

Stack assumed: Vue 3 (`<script setup lang="ts">`), Vue Router, Pinia, Tailwind 3.4+ (`tailwind.config.js` + `tokens.css`). The design canvas page holds every screen in light and dark, the component library board and a handoff board.

```
paintmixer/
  handoff.md            this file
  tokens.css            CSS variables (light, dark, system) + .pm-colour + .pm-field
  tailwind.config.js    theme + .btn-* .field .seg .seg-stage .focus-ring
  src/colour.ts         Lab→sRGB/hex, ΔE tiers, ColourMeta text, illuminant catalogue, impression
  src/icons.ts          shared icon paths (sun, mode icons, tier icons)
  src/components/*.vue  starter SFCs (type-checked with vue-tsc, classes compiled with Tailwind 3.4)
```

## 1. Principles

1. **The stage is the hero.** `StageCompare` is the largest element on Mix and the run screen and flexes to fill the height left over.
2. **Joined cards.** Anything shown under a swatch sits on a pale (`soft`) card joined to it: one outline, radius 16 outside, square where they meet, and the same side padding (32) in the stage and the card. Actions go below the card.
3. **Primary action bottom right.** Every screen has a bottom-anchored footer with a hairline above it; the primary button is its right-most element.
4. **Kiosk layout.** Screens fill the device viewport at full width; only inner regions scroll. No page titles — the nav says where you are.
5. **Four type sizes.** Display 30/36, body 16/28, UI 14/20, caption 12/16.
6. **No boxes inside boxes, no unneeded prose.** Hairlines and spacing group things; captions carry data, not explanations.
7. **Plain words first, number beside.** Tier labels for matches; Excellent / Good / Fair / Poor for calibration.

## 2. Colour-accuracy rules

1. Lab (D65/10°) is the source of truth. Convert in exactly one place: `labToCss()` / `labToHex()` in `src/colour.ts` (`labToCss` also reports sRGB clipping).
2. Anything that shows a measured colour gets `.pm-colour`: no opacity, filter, blend, gradient or hover tint. Disabled or stale states dim the label, never the colour.
3. Swatches sit on `bg-surround` (N5 #767676, identical in both themes).
4. Candidate colours under a non-D65 preview illuminant come from the solver already adapted; the UI never shifts hues itself. Illuminant tints (`cctTint`) are for icons and chips only.
5. Status is never colour-only: every tier has an icon shape and words; chart series differ by dash (target solid `fg`, mix dashed `accent`).
6. Concentric comparisons have **no border** between the inner and outer colour.
7. Every swatch and ink well has the same very small inner shadow (`--pm-ink`: 1 px down, 2 px blur, 28 % black + a 0.5 px 12 % edge). It is an overlay on the colour container (`.pm-ink`, `.pm-ink-well`), never on each half, so split and concentric views get no seam.

## 3. Formatting

| What | Format | Helper |
|---|---|---|
| Colour caption (`ColourMeta`) | `#859072 · 58.2 −9.6 14.8` — hex (D65) then L\* a\* b\* to 1 dp | `colourMeta(lab)` |
| Paint caption | same + pigment code: `#135A4B · 34.2 −27.0 3.8 · PG7`; pigment name only in the tooltip | `colourMeta(lab, 'PG7')` |
| ΔE | `0.63` (2 dp); rows read `ΔE 0.63` | `fmt(v)` |
| Minus | always U+2212 `−` | `fmt` |
| Money | `SGD 12.77` (currency from Settings); premium `+13% premium`, cheapest = `Baseline` | — |
| Illuminant | code + temperature: `D65 (6504 K)` | `ILLUMINANT[code].cct` |
| Volume | `250 ml` (machine maximum 250) | — |
| Dates | always with the year: `Calibrated 2 Nov 2026`, `Refilled 18 Oct 2026` | — |

## 4. Illuminants

`SERIES` in `src/colour.ts`: D (D50 D55 **D65** D75 D93), A, F (F2 F7 **F11** F12), LED (B1–B5, default B3), ID (ID50 **ID65**). Two separate choices:

- **Preview light** — `LightTabs` at the stage's top left: a series button + that series' members as sun-icon tabs. The series button opens `IlluminantMenu variant="rows"`; switching series keeps the member closest in colour temperature (`nearestInSeries`).
- **Match under** — `IlluminantField` in the solve settings: the illuminant the solver optimises for. Opens `IlluminantMenu variant="pills"`. Choosing one also moves the preview to it (the preview can then be changed on its own).

## 5. Screens

**Top bar** (64 px): logo · Mix · Library · Models · machine-status pill · settings. No page titles.

**Mix** — stage (`LightTabs` left, `ModeTabs` right, target / mix labels under the colour) joined to a pale card:
- Left column: Target label, InkWell + 30 px name + `ColourMeta`, then `SolveSettings` (Match under · Max paints 1…paints in the active model, default 4 · Volume ≤ 250 ml).
- Right column: "Ways to mix it" header with `SortTabs` (Closest · Fewest paints · Cost), then `MixOption` rows.
- Card footer: "Formula, spectrum and reach" toggle on the left, reach / verdict line on the right. The toggle opens `DetailsPane` over the card's top row (above the footer divider, not above the card).
- Page footer: `MixBar` (legend then 20 px bar) and **Dispense Mix A · SGD 12.77** bottom right.

**Mix while a job runs** (tablet 1194×834) — Dispense switches Mix into its running mode: progress steps, planned vs measured stage joined to a band with the round's ΔE and `RoundsTrail`; footer Correct again · **Accept**. There is no Jobs tab: the machine-status pill ("Machine ready" / "Correcting · Plum Mist") opens `MachinePopover` (running job card with Cancel job → inline confirm, Go to job; recent jobs; export log).

**Library** — palette dropdown (All colours or a palette; "New palette") + search; `PaletteBand` for the chosen palette; `ColourTile` grid; `DetailCard` (swatch joined to card: name, `ColourMeta`, best-match ΔE, facts Paints · Cost, best-mix composition on white), actions below (Add to palette · **Mix this colour**). Palette builder: tiles get +/✓ badges; side panel with name, ordered list and live reach.

**Models** — a model is a named, versioned set of paints with fitted calibration (e.g. *Studio acrylics v3.2*), chosen from a dropdown like palettes. Readings strip (import, problems, fit progress). Rack table with two-line columns: paint (name / `ColourMeta` with pigment) · channel / type · level bar / `% · ml` · `ResidualStrip` / status + calibrated date. `DetailCard`: name, `ColourMeta` with pigment, "Calibration accuracy · calibrated 2 Nov 2026" with grade, facts Mfr / batch · Cost, then a Level block on white — level bar in the paint colour with "18% · 45 ml" and "Refilled 18 Oct 2026" (the analogue of the colour card's best-mix composition); footer actions.

**Settings** — two-column sections: Judging colour (match in, tolerance, also check under), Machine, Cost & display, Advanced colour science (collapsed). Footer: unsaved count · Discard · **Save**.

**Mix states** — empty, finding a mix, error, uncertain prediction, out of reach — all keep the stage and offer the next step.

## 6. Components

| Component | File | Props → emits | Notes |
|---|---|---|---|
| `StageCompare` | ✔ | `target, candidate, mode, illuminant, targetLabel, candidateLabel, joined, size` · slots `header-left/right`, `empty` | Mix fills the stage; target laid over (half / centre 44 % / on hover) |
| `LightTabs` | ✔ | `v-model` illuminant code | Series button + member tabs; labels hidden < 1180 px |
| `ModeTabs` | ✔ | `v-model` `'split'\|'concentric'\|'hover'` | Rounded-rect icons, solid = target; labels hidden < 1180 px |
| `IlluminantMenu` | ✔ | `variant: 'rows'\|'pills', v-model, label` | Shared popover: section = header (name · desc · range) + options; dividers |
| `IlluminantField` / `StepperField` / `NumberField` | ✔ | `v-model` + limits | Underlined, full width, 40 px; no focus ring on text entry |
| `SolveSettings` | ✔ | `v-model:illuminant, v-model:maxPaints, v-model:volume, paintsInModel` | 88 px label column |
| `SortTabs` | ✔ | `v-model, options, label` | `.seg` segmented control |
| `MixOption` | ✔ | `mix, target, selected, wellMode, cheapest` → `select` | Two lines per column |
| `InkWell` | ✔ | `a, b?, mode, size 24\|36\|48` | 3 px N5 ring + `.pm-ink-well` inner shadow |
| `ColourMeta` | ✔ | `lab, hex?, pigment?, pigmentName?` | The caption under every colour name |
| `DeltaReadout` | ✔ | `value, uncertainty?, size: 'row'\|'display'` | Tier icon + words |
| `MixBar` | ✔ | `lines, label` | Legend (dot · % · name) above a 20 px bar |
| `DetailsPane` | ✔ | `mix, target, targetCurve, mixCurve, gamut, margin` | Formula → Spectrum → Reach, equal columns, graphs share a row |
| `SpectrumChart` | ✔ | `target, mix, mixName, mixLab` | Full-width, HTML axis labels, visual legend, Peak row, impression line |
| `ReachChart` | ✔ | `target, mix, mixName, dE, margin, gamut` | Square plot, full-surface axes, L\*a\*b\* row, ΔE + margin note |
| `ColourTile` | ✔ | `name, lab, hex?, selected, status?, badge?` → `select` | Status as a dot after the name |
| `ResidualStrip` | ✔ | `samples, max, marks, label` → `select(id)` | Density strip on its own pale surface |
| `DetailCard` | — | `#swatch #title #meta #metric #facts #visual #actions` | Library + Models share one structure: title + `ColourMeta` · ΔE row · two facts · one visual on white (best-mix composition / level bar + level · refill date) |
| `RackRow` | — | `paint` | Uses `ColourMeta`, `ResidualStrip` |
| `PaletteMenu` / `ModelMenu` | — | `items, v-model` → `new` | Dropdown next to the search / actions; strip + meta per item |
| `PaletteBand` | — | `palette, colours` → `mix-all, edit, export` | Joined strip + reach summary + worst ΔE |
| `MachineStatus` + `MachinePopover` | — | `machine, job?, recent` → `go-to-job, cancel-job` | 380 px; cancel needs an inline confirm |
| `RoundsTrail` + `ProgressSteps` | — | `rounds, v-model` / `steps, current` | Run screen |
| `PmButton` | via classes | `.btn-primary .btn-ghost .btn-link` | 44 px; 60 px on the run tablet |

✔ = starter SFC in `src/components`.

## 7. Tokens

See `tokens.css`. Surfaces: `page` (page, popovers, chart surfaces), `soft` (joined cards, panes, strips), `surround` (N5). Lines: `line` (hairlines), `line-strong` (field underlines, ghost outlines). Text: `fg`, `fg-2`, `fg-3` (captions, `ColourMeta`). Accent for the one primary action. `success / warning / danger` for tiers and status.

Radius: swatch 3 · colour 4 · field 8 · tile 10 · card 12 · option / popover 14 · stage 16 (run 20) · pill. Heights: tab 30 · field 40 · touch 44 · run 60 · header 64 · footer 76 · MixBar 20.

## 8. Theming, touch, accessibility

- `.theme-light` / `.theme-dark` on `<html>`; "System" follows `prefers-color-scheme` (handled in `tokens.css`).
- Touch targets ≥ 44 px; run-screen actions 60 px.
- Focus: 2 px `focus` ring, offset 3, on every control except text entry inside underlined fields (the caret is the indicator).
- Stage and wells carry `role="img"` with labels naming both colours and the light; popovers are `role="listbox"` with `role="option"` items; tabs use `role="tab"` / `aria-selected`; `SortTabs` uses `role="radio"`.
- All text ≥ 4.5 : 1 on its surface; white on N5 is 4.54 : 1.
