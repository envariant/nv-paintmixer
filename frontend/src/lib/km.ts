/**
 * Browser forward model: Kubelka-Munk mixing, colorimetry, dE2000 and CSS Color 4 gamut-mapped
 * swatches, mirroring backend/src/paintmixer/colorsci. Inputs come from the API:
 * `GET /api/v1/models/{v}/spectra` (K, S, k1, k2) and `GET /api/v1/colorimetry` (weighting
 * tables), so predictions match the server. Parity is tested against km.parity.json, which the
 * backend generates (`uv run paintmixer parity-fixture`).
 *
 * Use it for instant previews while editing a recipe; solving stays on the server.
 */

export type Vec3 = [number, number, number]
export type Illuminant = 'D65' | 'A' | 'F11'

export interface ColorimetryTables {
  wavelengths: number[]
  illuminants: Record<string, { weights: number[][]; white: number[] }>
  srgb: { white: number[]; xyz_to_rgb: number[][] }
}

export interface ModelTables {
  paint_ids: string[]
  K: number[][]
  S: number[][]
  k1: number
  k2: number
}

const EPS = 216 / 24389
const KAPPA = 24389 / 27

// --- Kubelka-Munk ---------------------------------------------------------------------------

export const rInf = (ks: number): number => {
  const k = Math.max(ks, 0)
  return 1 + k - Math.sqrt(k * k + 2 * k)
}

export const saunderson = (r: number, k1: number, k2: number): number =>
  k1 + ((1 - k1) * (1 - k2) * r) / (1 - k2 * r)

// --- CIELAB ---------------------------------------------------------------------------------

const f = (t: number): number => (t > EPS ? Math.cbrt(t) : (KAPPA * t + 16) / 116)
const fInv = (v: number): number => (v ** 3 > EPS ? v ** 3 : (116 * v - 16) / KAPPA)

export function xyzToLab(xyz: number[], white: number[]): Vec3 {
  const fx = f(xyz[0]! / white[0]!)
  const fy = f(xyz[1]! / white[1]!)
  const fz = f(xyz[2]! / white[2]!)
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)]
}

export function labToXyz(lab: number[], white: number[]): Vec3 {
  const fy = (lab[0]! + 16) / 116
  const fx = fy + lab[1]! / 500
  const fz = fy - lab[2]! / 200
  const y = lab[0]! > KAPPA * EPS ? fy ** 3 : lab[0]! / KAPPA
  return [fInv(fx) * white[0]!, y * white[1]!, fInv(fz) * white[2]!]
}

// --- OKLab and CSS Color 4 gamut mapping ---------------------------------------------------

const M1 = [
  [0.4122214708, 0.5363325363, 0.0514459929],
  [0.2119034982, 0.6806995451, 0.1073969566],
  [0.0883024619, 0.2817188376, 0.6299787005],
]
const M2 = [
  [0.2104542553, 0.793617785, -0.0040720468],
  [1.9779984951, -2.428592205, 0.4505937099],
  [0.0259040371, 0.7827717662, -0.808675766],
]

function inv3(m: number[][]): number[][] {
  const [a, b, c] = m[0]!
  const [d, e, g] = m[1]!
  const [h, i, j] = m[2]!
  const A = e! * j! - g! * i!
  const B = -(d! * j! - g! * h!)
  const C = d! * i! - e! * h!
  const det = a! * A + b! * B + c! * C
  return [
    [A / det, -(b! * j! - c! * i!) / det, (b! * g! - c! * e!) / det],
    [B / det, (a! * j! - c! * h!) / det, -(a! * g! - c! * d!) / det],
    [C / det, -(a! * i! - b! * h!) / det, (a! * e! - b! * d!) / det],
  ]
}
const M1_INV = inv3(M1)
const M2_INV = inv3(M2)

const mul = (m: number[][], v: number[]): Vec3 => [
  m[0]![0]! * v[0]! + m[0]![1]! * v[1]! + m[0]![2]! * v[2]!,
  m[1]![0]! * v[0]! + m[1]![1]! * v[1]! + m[1]![2]! * v[2]!,
  m[2]![0]! * v[0]! + m[2]![1]! * v[1]! + m[2]![2]! * v[2]!,
]

export const lrgbToOklab = (rgb: number[]): Vec3 => mul(M2, mul(M1, rgb).map(Math.cbrt))
export const oklabToLrgb = (lab: number[]): Vec3 => mul(M1_INV, mul(M2_INV, lab).map((x) => x ** 3))

const inGamut = (rgb: number[], tol = 1e-6): boolean => rgb.every((x) => x >= -tol && x <= 1 + tol)
const clip01 = (rgb: number[]): Vec3 => rgb.map((x) => Math.min(1, Math.max(0, x))) as Vec3
const deltaEOK = (a: number[], b: number[]): number => Math.hypot(a[0]! - b[0]!, a[1]! - b[1]!, a[2]! - b[2]!)

/** CSS Color 4 binary-search gamut mapping (keep OKLab L and hue, reduce chroma). */
export function gamutMapLrgb(rgb: number[], jnd = 0.02, eps = 1e-4): Vec3 {
  const origin = lrgbToOklab(rgb)
  const L = origin[0]
  if (L >= 1) return [1, 1, 1]
  if (L <= 0) return [0, 0, 0]
  if (inGamut(rgb)) return [rgb[0]!, rgb[1]!, rgb[2]!]
  const h = Math.atan2(origin[2], origin[1])
  let clipped = clip01(rgb)
  if (deltaEOK(lrgbToOklab(clipped), origin) < jnd) return clipped
  let lo = 0
  let hi = Math.hypot(origin[1], origin[2])
  let loIn = true
  for (let n = 0; n < 40 && hi - lo > eps; n++) {
    const chroma = (lo + hi) / 2
    const candLab: Vec3 = [L, chroma * Math.cos(h), chroma * Math.sin(h)]
    const cand = oklabToLrgb(candLab)
    if (loIn && inGamut(cand)) {
      lo = chroma
      continue
    }
    clipped = clip01(cand)
    const e = deltaEOK(lrgbToOklab(clipped), candLab)
    if (e < jnd) {
      if (jnd - e < eps) break
      loIn = false
      lo = chroma
    } else {
      hi = chroma
    }
  }
  return clipped
}

const encode = (x: number): number => {
  const a = Math.abs(x)
  return Math.sign(x) * (a <= 0.0031308 ? 12.92 * a : 1.055 * a ** (1 / 2.4) - 0.055)
}

export function toHex(rgb: number[]): string {
  return (
    '#' +
    rgb
      .map((x) => Math.round(Math.min(1, Math.max(0, x)) * 255))
      .map((v) => v.toString(16).padStart(2, '0'))
      .join('')
  )
}

// --- dE2000 (Sharma et al. 2005; hue ties at 180 deg use a tolerance, like the backend) -------

const HUE_TOL = 1e-9
const rad = (d: number): number => (d * Math.PI) / 180
const deg = (r: number): number => (r * 180) / Math.PI

export function deltaE2000(lab1: number[], lab2: number[]): number {
  const [L1, a1, b1] = lab1 as Vec3
  const [L2, a2, b2] = lab2 as Vec3
  const c1 = Math.hypot(a1, b1)
  const c2 = Math.hypot(a2, b2)
  const cBar7 = ((c1 + c2) / 2) ** 7
  const g = 0.5 * (1 - Math.sqrt(cBar7 / (cBar7 + 25 ** 7)))
  const a1p = (1 + g) * a1
  const a2p = (1 + g) * a2
  const c1p = Math.hypot(a1p, b1)
  const c2p = Math.hypot(a2p, b2)
  const hue = (b: number, a: number): number => (a === 0 && b === 0 ? 0 : ((deg(Math.atan2(b, a)) % 360) + 360) % 360)
  const h1p = hue(b1, a1p)
  const h2p = hue(b2, a2p)
  const zero = c1p * c2p === 0
  let dh = h2p - h1p
  if (dh > 180 + HUE_TOL) dh -= 360
  else if (dh < -180 - HUE_TOL) dh += 360
  if (zero) dh = 0
  const dL = L2 - L1
  const dC = c2p - c1p
  const dH = 2 * Math.sqrt(c1p * c2p) * Math.sin(rad(dh / 2))
  const lBar = (L1 + L2) / 2
  const cBar = (c1p + c2p) / 2
  const hSum = h1p + h2p
  let hBar = Math.abs(h1p - h2p) <= 180 + HUE_TOL ? hSum / 2 : hSum < 360 ? (hSum + 360) / 2 : (hSum - 360) / 2
  if (zero) hBar = hSum
  const t =
    1 -
    0.17 * Math.cos(rad(hBar - 30)) +
    0.24 * Math.cos(rad(2 * hBar)) +
    0.32 * Math.cos(rad(3 * hBar + 6)) -
    0.2 * Math.cos(rad(4 * hBar - 63))
  const dTheta = 30 * Math.exp(-(((hBar - 275) / 25) ** 2))
  const cBar7p = cBar ** 7
  const rC = 2 * Math.sqrt(cBar7p / (cBar7p + 25 ** 7))
  const sL = 1 + (0.015 * (lBar - 50) ** 2) / Math.sqrt(20 + (lBar - 50) ** 2)
  const sC = 1 + 0.045 * cBar
  const sH = 1 + 0.015 * cBar * t
  const rT = -Math.sin(rad(2 * dTheta)) * rC
  const tl = dL / sL
  const tc = dC / sC
  const th = dH / sH
  return Math.sqrt(tl * tl + tc * tc + th * th + rT * tc * th)
}

// --- forward model --------------------------------------------------------------------------

export interface Prediction {
  reflectance: number[]
  lab: Vec3 // under the requested illuminant
  hex: string // always rendered under D65, gamut-mapped
  outOfGamut: boolean
}

export class ForwardModel {
  readonly ids: string[]
  private readonly index: Map<string, number>
  private readonly model: ModelTables
  private readonly tables: ColorimetryTables

  constructor(model: ModelTables, tables: ColorimetryTables) {
    this.model = model
    this.tables = tables
    this.ids = model.paint_ids
    this.index = new Map(model.paint_ids.map((p, i) => [p, i]))
    if (model.K[0]?.length !== tables.wavelengths.length) {
      throw new Error('model and colorimetry use different wavelength grids')
    }
  }

  /** Measured-like reflectance of an opaque film; fractions are normalised. */
  reflectance(fractions: Record<string, number>): number[] {
    const n = this.tables.wavelengths.length
    const kMix = new Array<number>(n).fill(0)
    const sMix = new Array<number>(n).fill(0)
    let total = 0
    for (const [pid, c] of Object.entries(fractions)) {
      const i = this.index.get(pid)
      if (i === undefined) throw new Error(`paint ${pid} is not in the model`)
      if (c < 0) throw new Error('fractions must be >= 0')
      total += c
      const K = this.model.K[i]!
      const S = this.model.S[i]!
      for (let b = 0; b < n; b++) {
        kMix[b]! += c * K[b]!
        sMix[b]! += c * S[b]!
      }
    }
    if (total <= 0) throw new Error('fractions must have a positive sum')
    return kMix.map((k, b) => saunderson(rInf(k / Math.max(sMix[b]!, 1e-12)), this.model.k1, this.model.k2))
  }

  lab(reflectance: number[], illuminant: Illuminant = 'D65'): Vec3 {
    const t = this.tables.illuminants[illuminant]
    if (!t) throw new Error(`no tables for illuminant ${illuminant}`)
    const xyz = t.weights.map((row) => row.reduce((acc, w, b) => acc + w * reflectance[b]!, 0))
    return xyzToLab(xyz, t.white)
  }

  /** sRGB swatch for a D65 Lab, gamut-mapped like the backend. */
  swatch(labD65: number[]): { hex: string; outOfGamut: boolean } {
    const xyz = labToXyz(labD65, this.tables.srgb.white).map((v) => v / 100)
    const lin = mul(this.tables.srgb.xyz_to_rgb, xyz)
    const oog = !inGamut(lin, 1e-4)
    const mapped = oog ? gamutMapLrgb(lin) : lin
    return { hex: toHex(mapped.map((x) => encode(Math.min(1, Math.max(0, x))))), outOfGamut: oog }
  }

  predict(fractions: Record<string, number>, illuminant: Illuminant = 'D65'): Prediction {
    const reflectance = this.reflectance(fractions)
    const d65 = this.lab(reflectance, 'D65')
    const { hex, outOfGamut } = this.swatch(d65)
    return { reflectance, lab: illuminant === 'D65' ? d65 : this.lab(reflectance, illuminant), hex, outOfGamut }
  }

  /** Swatches mixing paint A into paint B at the given fractions of A. */
  ramp(paintA: string, paintB: string, fractionsA: number[]): Prediction[] {
    return fractionsA.map((fa) => this.predict({ [paintA]: fa, [paintB]: 1 - fa }))
  }
}

export function rampFractions(steps: number, scale: 'linear' | 'log' = 'linear', minFraction = 0.01): number[] {
  if (steps < 2) throw new Error('a ramp needs at least 2 steps')
  if (scale === 'linear') return Array.from({ length: steps }, (_, i) => 1 - i / (steps - 1))
  return Array.from({ length: steps }, (_, i) => Math.exp((Math.log(minFraction) * i) / (steps - 1)))
}
