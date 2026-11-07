/** Format a dE2000 value for display. */
export function formatDeltaE(de: number): string {
  return de.toFixed(de < 10 ? 2 : 1)
}
