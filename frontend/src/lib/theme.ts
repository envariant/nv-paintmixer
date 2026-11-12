/** Light / dark / system theme: a class on <html> (tokens.css), remembered on this device. */
export type Theme = 'system' | 'light' | 'dark'
const KEY = 'pm-theme'

export function savedTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(t: Theme): void {
  const el = document.documentElement
  el.classList.remove('theme-light', 'theme-dark')
  if (t !== 'system') el.classList.add(`theme-${t}`)
  try {
    localStorage.setItem(KEY, t)
  } catch {
    // private mode: the theme still applies for this visit
  }
}
