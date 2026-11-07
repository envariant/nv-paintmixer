/** Small colour helpers for the UI (no colour maths beyond display formatting). */

export type DeltaETier = 'excellent' | 'good' | 'fair' | 'poor'

export interface DeltaEBadge {
  tier: DeltaETier
  /** Human-readable label: tiers must be conveyed by text (and icon), not by colour alone. */
  label: string
  /** Icon name hint for the design system's icon set. */
  icon: 'check-double' | 'check' | 'alert' | 'cross'
}

/** dE2000 tiers: <1 not perceptible to most, <2 close, <3.5 noticeable, otherwise poor. */
export function deltaEBadge(de: number): DeltaEBadge {
  if (de < 1) return { tier: 'excellent', label: 'Excellent match', icon: 'check-double' }
  if (de < 2) return { tier: 'good', label: 'Good match', icon: 'check' }
  if (de < 3.5) return { tier: 'fair', label: 'Noticeable difference', icon: 'alert' }
  return { tier: 'poor', label: 'Poor match', icon: 'cross' }
}

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

export function formatMoney(amount: number, currency = 'SGD'): string {
  return new Intl.NumberFormat('en-SG', { style: 'currency', currency }).format(amount)
}
