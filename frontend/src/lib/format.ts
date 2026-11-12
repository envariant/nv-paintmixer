/** Format a dE2000 value for display. */
export function formatDeltaE(de: number): string {
  return de.toFixed(de < 10 ? 2 : 1)
}

/** Dates always carry the year (design): "2 Nov 2026". */
export function formatDate(iso: string | Date): string {
  const d = typeof iso === 'string' ? new Date(iso) : iso
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }).replace('Sept', 'Sep')
}

/** A backend step / status line for display: "dE" is written ΔE in the UI. */
export function stepText(s: string | null | undefined): string {
  return (s ?? '').replace(/\bdE\b/g, 'ΔE')
}
