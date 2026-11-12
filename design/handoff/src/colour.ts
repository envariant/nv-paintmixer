// PaintMixer colour helpers — the only place the UI turns numbers into colour or colour words.

export type Lab = { L: number; a: number; b: number }
export type Tier = 1 | 2 | 3 | 4

/* ───────────── Difference tiers (ΔE00) ───────────── */

export const TIER_LABEL: Record<Tier, string> = {
  1: 'Indistinguishable',
  2: 'Barely visible',
  3: 'Visible difference',
  4: 'Mismatch'
}

export function tierOf(dE: number, thresholds: [number, number, number] = [1, 2, 5]): Tier {
  return dE < thresholds[0] ? 1 : dE < thresholds[1] ? 2 : dE < thresholds[2] ? 3 : 4
}

/** Calibration accuracy uses grades, not perceptual tiers. */
export function calibrationGrade(dE: number): 'Excellent' | 'Good' | 'Fair' | 'Poor' {
  return dE < 0.4 ? 'Excellent' : dE < 1 ? 'Good' : dE < 2 ? 'Fair' : 'Poor'
}

/* ───────────── Number formatting ───────────── */

/** U+2212 minus, fixed decimals, tabular-friendly. */
export function fmt(v: number, dp = 2, signed = false): string {
  const s = Math.abs(v).toFixed(dp)
  if (v < 0) return '−' + s
  return signed ? '+' + s : s
}

/* ───────────── Lab → screen ───────────── */

function labToSrgb({ L, a, b }: Lab): { rgb: [number, number, number]; clipped: boolean } {
  const fy = (L + 16) / 116, fx = fy + a / 500, fz = fy - b / 200
  const e = 216 / 24389, k = 24389 / 27
  const finv = (t: number) => (t ** 3 > e ? t ** 3 : (116 * t - 16) / k)
  const X = 0.95047 * finv(fx), Y = L > k * e ? fy ** 3 : L / k, Z = 1.08883 * finv(fz)
  const lin = [
    3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z,
    -0.969266 * X + 1.8760108 * Y + 0.041556 * Z,
    0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z
  ]
  let clipped = false
  const rgb = lin.map((c) => {
    const g = c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055
    if (g < 0 || g > 1) clipped = true
    return Math.round(Math.min(1, Math.max(0, g)) * 255)
  }) as [number, number, number]
  return { rgb, clipped }
}

/** The single Lab → sRGB conversion used everywhere (D65, CIE 1976). Reports clipping. */
export function labToCss(lab: Lab): { css: string; clipped: boolean } {
  const { rgb, clipped } = labToSrgb(lab)
  return { css: `rgb(${rgb[0]} ${rgb[1]} ${rgb[2]})`, clipped }
}

export function labToHex(lab: Lab): string {
  return '#' + labToSrgb(lab).rgb.map((c) => c.toString(16).padStart(2, '0')).join('').toUpperCase()
}

/* ───────────── ColourMeta caption ───────────── */

/**
 * The caption under every colour name: "#859072 · 58.2 −9.6 14.8", plus " · PG7" for paints.
 * `hex` is the D65 value so it always agrees with the Lab numbers.
 */
export function colourMeta(lab: Lab, pigment?: string, hex = labToHex(lab)): { text: string; title: string } {
  const n = (v: number) => fmt(v, 1)
  const text = `${hex} · ${n(lab.L)} ${n(lab.a)} ${n(lab.b)}` + (pigment ? ` · ${pigment}` : '')
  const title = `Hex ${hex} · L* ${n(lab.L)}, a* ${n(lab.a)}, b* ${n(lab.b)}` + (pigment ? ` · ${pigment}` : '')
  return { text, title }
}

/* ───────────── Illuminants ───────────── */

export interface Illuminant { code: string; cct: number }
export interface IlluminantSeries { id: string; name: string; desc: string; default: string; members: Illuminant[] }

export const SERIES: IlluminantSeries[] = [
  { id: 'D', name: 'D series', desc: 'Daylight', default: 'D65',
    members: [{ code: 'D50', cct: 5003 }, { code: 'D55', cct: 5503 }, { code: 'D65', cct: 6504 }, { code: 'D75', cct: 7504 }, { code: 'D93', cct: 9300 }] },
  { id: 'A', name: 'A', desc: 'Incandescent / tungsten', default: 'A', members: [{ code: 'A', cct: 2856 }] },
  { id: 'F', name: 'F series', desc: 'Fluorescent', default: 'F11',
    members: [{ code: 'F2', cct: 4230 }, { code: 'F7', cct: 6500 }, { code: 'F11', cct: 4000 }, { code: 'F12', cct: 3000 }] },
  { id: 'LED', name: 'LED series', desc: 'White LEDs', default: 'LED-B3',
    members: [{ code: 'LED-B1', cct: 2733 }, { code: 'LED-B2', cct: 2998 }, { code: 'LED-B3', cct: 4103 }, { code: 'LED-B4', cct: 5109 }, { code: 'LED-B5', cct: 6598 }] },
  { id: 'ID', name: 'ID series', desc: 'Indoor daylight', default: 'ID65',
    members: [{ code: 'ID50', cct: 5003 }, { code: 'ID65', cct: 6504 }] }
]

export const ILLUMINANT: Record<string, Illuminant & { series: IlluminantSeries }> = Object.fromEntries(
  SERIES.flatMap((s) => s.members.map((m) => [m.code, { ...m, series: s }]))
)

export function seriesRange(s: IlluminantSeries): string {
  const k = s.members.map((m) => m.cct)
  return k.length > 1 ? `${Math.min(...k)}–${Math.max(...k)} K` : `${k[0]} K`
}

/** Switching series keeps the member closest in colour temperature to the current illuminant. */
export function nearestInSeries(series: IlluminantSeries, currentCode: string): string {
  const cur = ILLUMINANT[currentCode]?.cct ?? 6504
  return series.members.reduce((best, m) => (Math.abs(m.cct - cur) < Math.abs(best.cct - cur) ? m : best)).code
}

/** Approximate white-point tint for a colour temperature (icon / chip dots only — never a measured colour). */
export function cctTint(kelvin: number): string {
  const t = kelvin / 100
  const r = t <= 66 ? 255 : 329.7 * (t - 60) ** -0.1332
  const g = t <= 66 ? 99.47 * Math.log(t) - 161.12 : 288.12 * (t - 60) ** -0.0755
  const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.52 * Math.log(t - 10) - 305.04
  const c = (v: number) => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, '0')
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
  [20, 'pink-red'], [50, 'red-orange'], [75, 'orange'], [100, 'yellow'], [135, 'yellow-green'], [170, 'green'],
  [215, 'blue-green'], [260, 'blue'], [300, 'violet'], [345, 'magenta'], [361, 'pink-red']
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
  const mood = C < 22 && h >= 100 && h < 170
    ? 'a soft sage that reads calm and earthy, closer to grey than to leaf green'
    : C < 22 ? 'a quiet, grounded colour that sits easily with neutrals' : 'a lively colour that draws the eye'
  return `${light}, ${chroma} ${hue}: ${mood}.`
}
