// PaintMixer colour helpers — the only place the UI turns numbers into colour or colour words.
// Merged from the design handoff (design/handoff/src/colour.ts) with the app's helpers.
// One deliberate difference from the handoff: Lab → screen uses the backend's conversion
// (CIE 1931 2° Lab, sRGB D65, CSS Color 4 gamut mapping via lib/km.ts) so a colour shows the same
// hex here as in every API response; `clipped` means "outside sRGB, gamut-mapped".

import { gamutMapLrgb, labToXyz } from './km'

export type Lab = { L: number; a: number; b: number }
export type Tier = 1 | 2 | 3 | 4

export const lab = (v: readonly number[]): Lab => ({ L: v[0]!, a: v[1]!, b: v[2]! })

/* ───────────── Difference tiers (ΔE00) for matches ───────────── */

export const TIER_LABEL: Record<Tier, string> = {
  1: 'Indistinguishable',
  2: 'Barely visible',
  3: 'Visible difference',
  4: 'Mismatch',
}

export function tierOf(dE: number, thresholds: [number, number, number] = [1, 2, 5]): Tier {
  return dE < thresholds[0] ? 1 : dE < thresholds[1] ? 2 : dE < thresholds[2] ? 3 : 4
}

/** Calibration accuracy uses grades, not perceptual tiers (same bounds as the backend). */
export function calibrationGrade(dE: number): 'Excellent' | 'Good' | 'Fair' | 'Poor' {
  return dE < 0.4 ? 'Excellent' : dE < 1 ? 'Good' : dE < 2 ? 'Fair' : 'Poor'
}

/* ───────────── Number formatting ───────────── */

/** U+2212 minus, fixed decimals, tabular-friendly. */
export function fmt(v: number, dp = 2, signed = false): string {
  const s = Math.abs(v).toFixed(dp)
  if (v < 0 && Number(s) !== 0) return '−' + s
  return signed ? '+' + s : s
}

export function formatMoney(amount: number, currency = 'SGD'): string {
  return `${currency} ${amount.toFixed(2)}`
}

/* ───────────── Lab → screen ───────────── */

// sRGB (IEC 61966-2-1): the backend's constants (colorsci.convert, GET /colorimetry)
const SRGB_WHITE = [95.047, 100.00001, 108.883]
const XYZ_TO_RGB = [
  [3.240454836021, -1.537138850103, -0.498531546868],
  [-0.969266389876, 1.876010928842, 0.041556082347],
  [0.055643419604, -0.204025854268, 1.057225162458],
]

const encode = (x: number): number => (x <= 0.0031308 ? 12.92 * x : 1.055 * x ** (1 / 2.4) - 0.055)

function labToSrgb({ L, a, b }: Lab): { rgb: [number, number, number]; clipped: boolean } {
  const xyz = labToXyz([L, a, b], SRGB_WHITE).map((v) => v / 100)
  const lin = XYZ_TO_RGB.map((r) => r[0]! * xyz[0]! + r[1]! * xyz[1]! + r[2]! * xyz[2]!)
  const tol = 1e-4
  const clipped = lin.some((c) => c < -tol || c > 1 + tol)
  const mapped = clipped ? gamutMapLrgb(lin) : lin
  const rgb = mapped.map((c) => Math.round(Math.min(1, Math.max(0, encode(Math.min(1, Math.max(0, c))))) * 255))
  return { rgb: rgb as [number, number, number], clipped }
}

/** The single Lab → sRGB conversion used everywhere (D65). Reports colours outside sRGB. */
export function labToCss(lab: Lab): { css: string; clipped: boolean } {
  const { rgb, clipped } = labToSrgb(lab)
  return { css: `rgb(${rgb[0]} ${rgb[1]} ${rgb[2]})`, clipped }
}

export function labToHex(lab: Lab): string {
  return '#' + labToSrgb(lab).rgb.map((c) => c.toString(16).padStart(2, '0')).join('').toUpperCase()
}

const decode = (v: number): number => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
const RGB_TO_XYZ = [
  [0.4124564, 0.3575761, 0.1804375],
  [0.2126729, 0.7151522, 0.072175],
  [0.0193339, 0.119192, 0.9503041],
]

/** sRGB hex → Lab (D65), for colours the API sends only as hex (e.g. a job's last reading). */
export function hexToLab(hex: string): Lab {
  const h = hex.replace(/^#/, '')
  const lin = [0, 2, 4].map((i) => decode(parseInt(h.slice(i, i + 2), 16) / 255))
  const xyz = RGB_TO_XYZ.map((r) => 100 * (r[0]! * lin[0]! + r[1]! * lin[1]! + r[2]! * lin[2]!))
  const f = (t: number) => (t > 216 / 24389 ? Math.cbrt(t) : ((24389 / 27) * t + 16) / 116)
  const [fx, fy, fz] = xyz.map((v, i) => f(v / SRGB_WHITE[i]!)) as [number, number, number]
  return { L: 116 * fy - 16, a: 500 * (fx - fy), b: 200 * (fy - fz) }
}

/* ───────────── ColourMeta caption ───────────── */

/**
 * The caption under every colour name: "#859072 · 58.2 −9.6 14.8", plus " · PG7" for paints.
 * `hex` is the D65 value so it always agrees with the Lab numbers.
 */
export function colourMeta(lab: Lab, pigment?: string, hex = labToHex(lab)): { text: string; title: string } {
  const n = (v: number) => fmt(v, 1)
  const h = hex.toUpperCase()
  const text = `${h} · ${n(lab.L)} ${n(lab.a)} ${n(lab.b)}` + (pigment ? ` · ${pigment}` : '')
  const title = `Hex ${h} · L* ${n(lab.L)}, a* ${n(lab.a)}, b* ${n(lab.b)}` + (pigment ? ` · ${pigment}` : '')
  return { text, title }
}

/* ───────────── Illuminants ───────────── */

export interface Illuminant {
  code: string
  cct: number
}
export interface IlluminantSeries {
  id: string
  name: string
  desc: string
  default: string
  members: Illuminant[]
}

/**
 * The catalogue as shipped (GET /illuminants returns the same; the illuminants store loads it and
 * falls back to this). Kept in sync with the backend by the parity fixture (km.parity.json).
 */
export const SERIES: IlluminantSeries[] = [
  {
    id: 'D',
    name: 'D series',
    desc: 'Daylight',
    default: 'D65',
    members: [
      { code: 'D50', cct: 5003 },
      { code: 'D55', cct: 5503 },
      { code: 'D65', cct: 6504 },
      { code: 'D75', cct: 7504 },
      { code: 'D93', cct: 9300 },
    ],
  },
  { id: 'A', name: 'A', desc: 'Incandescent / tungsten', default: 'A', members: [{ code: 'A', cct: 2856 }] },
  {
    id: 'F',
    name: 'F series',
    desc: 'Fluorescent',
    default: 'F11',
    members: [
      { code: 'F2', cct: 4230 },
      { code: 'F7', cct: 6500 },
      { code: 'F11', cct: 4000 },
      { code: 'F12', cct: 3000 },
    ],
  },
  {
    id: 'LED',
    name: 'LED series',
    desc: 'White LEDs',
    default: 'LED-B3',
    members: [
      { code: 'LED-B1', cct: 2733 },
      { code: 'LED-B2', cct: 2998 },
      { code: 'LED-B3', cct: 4103 },
      { code: 'LED-B4', cct: 5109 },
      { code: 'LED-B5', cct: 6598 },
    ],
  },
  {
    id: 'ID',
    name: 'ID series',
    desc: 'Indoor daylight',
    default: 'ID65',
    members: [
      { code: 'ID50', cct: 5003 },
      { code: 'ID65', cct: 6504 },
    ],
  },
]

export type IlluminantIndex = Record<string, Illuminant & { series: IlluminantSeries }>

export function indexIlluminants(series: IlluminantSeries[]): IlluminantIndex {
  return Object.fromEntries(series.flatMap((s) => s.members.map((m) => [m.code, { ...m, series: s }])))
}

export const ILLUMINANT: IlluminantIndex = indexIlluminants(SERIES)

export function seriesRange(s: IlluminantSeries): string {
  const k = s.members.map((m) => m.cct)
  return k.length > 1 ? `${Math.min(...k)}–${Math.max(...k)} K` : `${k[0]} K`
}

/** Switching series keeps the member closest in colour temperature to the current illuminant. */
export function nearestInSeries(series: IlluminantSeries, currentCode: string, index = ILLUMINANT): string {
  const cur = index[currentCode]?.cct ?? 6504
  return series.members.reduce((best, m) => (Math.abs(m.cct - cur) < Math.abs(best.cct - cur) ? m : best)).code
}

/** Approximate white-point tint for a colour temperature (icon / chip dots only — never a measured colour). */
export function cctTint(kelvin: number): string {
  const t = kelvin / 100
  const r = t <= 66 ? 255 : 329.7 * (t - 60) ** -0.1332
  const g = t <= 66 ? 99.47 * Math.log(t) - 161.12 : 288.12 * (t - 60) ** -0.0755
  const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.52 * Math.log(t - 10) - 305.04
  const c = (v: number) =>
    Math.round(Math.min(255, Math.max(0, v)))
      .toString(16)
      .padStart(2, '0')
  return '#' + [r, g, b].map(c).join('').toUpperCase()
}

/* ───────────── Spectrum + impression ───────────── */

/** Peak of a reflectance curve: [{nm, r (0–1)}] → wavelength rounded to 5 nm and percentage. */
export function reflectancePeak(curve: { nm: number; r: number }[]): { nm: number; pct: number } {
  const top = Math.max(...curve.map((p) => p.r))
  const near = curve.filter((p) => top - p.r < 0.004)
  const nm = near.reduce((s, p) => s + p.nm, 0) / near.length
  return { nm: Math.round(nm / 5) * 5, pct: Math.round(top * 100) }
}

const HUES: [number, string][] = [
  [20, 'pink-red'],
  [50, 'red-orange'],
  [75, 'orange'],
  [100, 'yellow'],
  [135, 'yellow-green'],
  [170, 'green'],
  [215, 'blue-green'],
  [260, 'blue'],
  [300, 'violet'],
  [345, 'magenta'],
  [361, 'pink-red'],
]

/**
 * One subjective line about the colour itself (not the match, not the light):
 * "Mid-light, muted yellow-green: a soft sage that reads calm and earthy, closer to grey than to leaf green."
 * The mood phrase is a placeholder vocabulary; extend per hue band.
 */
export function colourImpression({ L, a, b }: Lab): string {
  const C = Math.hypot(a, b)
  const h = ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360
  const light = L < 35 ? 'Deep' : L < 50 ? 'Mid-dark' : L < 65 ? 'Mid-light' : 'Pale'
  const chroma = C < 8 ? 'greyed' : C < 22 ? 'muted' : C < 40 ? 'clear' : 'vivid'
  const hue = HUES.find(([d]) => h < d)![1]
  const mood =
    C < 22 && h >= 100 && h < 170
      ? 'a soft sage that reads calm and earthy, closer to grey than to leaf green'
      : C < 22
        ? 'a quiet, grounded colour that sits easily with neutrals'
        : 'a lively colour that draws the eye'
  return `${light}, ${chroma} ${hue}: ${mood}.`
}

/* ───────────── Input helpers ───────────── */

export function isHex(s: string): boolean {
  return /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.test(s.trim())
}

export function normaliseHex(s: string): string {
  let h = s.trim().replace(/^#/, '').toLowerCase()
  if (h.length === 3) h = [...h].map((c) => c + c).join('')
  if (!/^[0-9a-f]{6}$/.test(h)) throw new Error(`invalid hex colour: ${s}`)
  return `#${h}`
}

export function parseLab(s: string): [number, number, number] | null {
  const parts = s.split(/[\s,;]+/).filter(Boolean).map(Number)
  if (parts.length !== 3 || parts.some((x) => !Number.isFinite(x))) return null
  const [L, a, b] = parts as [number, number, number]
  if (L < 0 || L > 100) return null
  return [L, a, b]
}
