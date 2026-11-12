// From the design handoff (design/handoff/src/icons.ts).
// Icon paths (24×24 viewBox, 1.6–2.4 stroke). The comparison-mode icons mirror the swatch: solid = target.
export const ICON = {
  sunRays: 'M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8',
  chevron: 'M6 9l6 6 6-6',
  minus: 'M5 12h14',
  plus: 'M12 5v14M5 12h14',
  mode: {
    split: { outline: 'M6 5h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM12 5v14', solid: 'M12 5H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h6z' },
    concentric: { outline: 'M6 5h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z', solid: 'M10 9.5h4a.5.5 0 0 1 .5.5v4a.5.5 0 0 1-.5.5h-4a.5.5 0 0 1-.5-.5v-4a.5.5 0 0 1 .5-.5z' },
    hover: { outline: 'M5 4h11a2 2 0 0 1 2 2v5M10 18H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2', solid: 'M12 11l9 3.4-3.8 1.4-1.4 3.8z' }
  },
  tier: {
    1: 'M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18zM8 12.5l2.5 2.5L16 9.5',
    2: 'M5 12.5l4.5 4.5L19 7.5',
    3: 'M12 4l9 16H3zM12 10v4M12 17v.5',
    4: 'M8.5 3h7L21 8.5v7L15.5 21h-7L3 15.5v-7zM9 9l6 6M15 9l-6 6'
  }
} as const

// Added for the app shell (not in the handoff): settings gear, close.
export const APP_ICON = {
  gear: 'M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM19.4 13.5a7.6 7.6 0 0 0 0-3l2-1.6-2-3.4-2.4 1a7.7 7.7 0 0 0-2.6-1.5L14 2.5h-4l-.4 2.5A7.7 7.7 0 0 0 7 6.5l-2.4-1-2 3.4 2 1.6a7.6 7.6 0 0 0 0 3l-2 1.6 2 3.4 2.4-1a7.7 7.7 0 0 0 2.6 1.5l.4 2.5h4l.4-2.5a7.7 7.7 0 0 0 2.6-1.5l2.4 1 2-3.4z',
  close: 'M6 6l12 12M18 6L6 18',
} as const

