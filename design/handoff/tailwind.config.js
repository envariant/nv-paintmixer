// PaintMixer Tailwind theme (v3 config; in Tailwind v4 load it with `@config "./tailwind.config.js";`).
// Colours resolve to CSS variables in tokens.css, so light/dark is a class swap with no rebuild.

/** @type {import('tailwindcss').Config} */
const v = (name) => `rgb(var(--pm-${name}) / <alpha-value>)`

module.exports = {
  content: ['./index.html', './src/**/*.{vue,ts,js}'],
  darkMode: ['class', '.theme-dark'],
  theme: {
    borderRadius: {
      none: '0',
      swatch: '3px',      // colour inside a tile / rack swatch
      colour: '4px',      // colour inside the stage, MixBar
      sm: '6px',          // small swatch surround
      field: '8px',       // chart surfaces
      tile: '10px',       // colour tile, popover option rows
      card: '12px',       // job card, detail pane
      option: '14px',     // MixOption, popovers
      stage: '16px',      // stage + joined card
      'stage-lg': '20px', // run-screen stage
      pill: '9999px',     // buttons, tabs, chips
      full: '9999px'
    },
    fontFamily: {
      sans: ['Inter', 'system-ui', 'sans-serif'],
      mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace']
    },
    // Four sizes only.
    fontSize: {
      caption: ['12px', { lineHeight: '16px' }], // ColourMeta, labels, chart axes, legends
      ui: ['14px', { lineHeight: '20px' }],      // controls, rows, field labels
      body: ['16px', { lineHeight: '28px' }],    // field values, the occasional sentence
      display: ['30px', { lineHeight: '36px', letterSpacing: '-0.02em' }] // titles, ΔE on the run screen
    },
    extend: {
      colors: {
        page: v('page'),
        soft: v('soft'),
        line: { DEFAULT: v('line'), strong: v('line-strong') },
        fg: { DEFAULT: v('fg'), 2: v('fg2'), 3: v('fg3') },
        surround: v('surround'),
        accent: { DEFAULT: v('accent'), hover: v('accent-hover'), on: v('on-accent'), weak: v('accent-weak'), fg: v('accent-fg') },
        success: v('success'),
        warning: v('warning'),
        danger: v('danger'),
        focus: v('focus')
      },
      height: { tab: '30px', field: '40px', touch: '44px', bar: '20px', run: '60px', header: '64px', footer: '76px' },
      minHeight: { touch: '44px', stage: '180px' },
      width: { popover: '390px', machine: '380px', detail: '340px' },
      padding: { stage: '32px' },  // stage AND joined card share this side padding
      boxShadow: {
        ink: 'inset 0 1px 2px rgb(0 0 0 / 0.28), inset 0 0 0 0.5px rgb(0 0 0 / 0.12)', // prefer .pm-ink (overlay) on colour containers
        selected: '0 0 0 2px rgb(var(--pm-page)), 0 0 0 4px rgb(var(--pm-fg))',
        popover: '0 12px 32px rgb(0 0 0 / 0.22)'
      },
      borderWidth: { 1.5: '1.5px' },
      transitionDuration: { DEFAULT: '120ms' }
    }
  },
  plugins: [
    function ({ addUtilities, addComponents }) {
      addUtilities({
        '.n': { fontVariantNumeric: 'tabular-nums' },
        '.on-surround': { color: '#FFFFFF', fontSize: '12px', fontWeight: '500' } // 4.54:1 on #767676
      })
      addComponents({
        '.btn-primary': {
          height: '44px', padding: '0 22px', borderRadius: '9999px', fontWeight: '600', fontSize: '14px', whiteSpace: 'nowrap',
          backgroundColor: 'rgb(var(--pm-accent))', color: 'rgb(var(--pm-on-accent))',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
          '&:hover': { backgroundColor: 'rgb(var(--pm-accent-hover))' }
        },
        '.btn-ghost': {
          height: '36px', padding: '0 14px', borderRadius: '9999px', fontWeight: '500', fontSize: '14px',
          border: '1px solid rgb(var(--pm-line-strong))', color: 'rgb(var(--pm-fg))', display: 'inline-flex', alignItems: 'center', gap: '8px',
          '&:hover': { backgroundColor: 'rgb(var(--pm-soft))' }
        },
        '.btn-link': {
          color: 'rgb(var(--pm-fg2))', fontWeight: '500', fontSize: '14px', textDecoration: 'underline',
          textUnderlineOffset: '3px', textDecorationColor: 'rgb(var(--pm-line-strong))',
          '&:hover': { color: 'rgb(var(--pm-fg))' }
        },
        // Underlined field: full width, 40 px, value at 16 px semibold, unit / icon buttons at the right end.
        '.field': {
          display: 'flex', alignItems: 'center', gap: '10px', width: '100%', height: '40px', padding: '0 2px',
          borderBottom: '1.5px solid rgb(var(--pm-line-strong))', fontSize: '16px', fontWeight: '600'
        },
        // Segmented tabs (SortTabs, ModeTabs on light surfaces).
        '.seg': { display: 'inline-flex', gap: '4px', padding: '3px', borderRadius: '20px', backgroundColor: 'rgb(var(--pm-soft))' },
        '.seg > button': { height: '30px', padding: '0 14px', borderRadius: '15px', fontSize: '12px', fontWeight: '500', color: 'rgb(var(--pm-fg2))' },
        '.seg > button[aria-checked="true"], .seg > button[aria-selected="true"]': {
          backgroundColor: 'rgb(var(--pm-page))', color: 'rgb(var(--pm-fg))', boxShadow: '0 0 0 1px rgb(var(--pm-line))'
        },
        // Tabs that sit on the N5 stage (LightTabs, ModeTabs): white-on-grey.
        '.seg-stage': { display: 'inline-flex', alignItems: 'center', gap: '2px', padding: '3px', borderRadius: '20px', backgroundColor: 'rgb(0 0 0 / 0.24)' },
        '.seg-stage > button': { height: '30px', minWidth: '36px', padding: '0 10px', borderRadius: '15px', fontSize: '12px', fontWeight: '500', color: '#FFFFFF', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '6px' },
        '.seg-stage > button[aria-selected="true"]': { backgroundColor: '#FFFFFF', color: '#141414' },
        '.focus-ring': { '&:focus-visible': { outline: '2px solid rgb(var(--pm-focus))', outlineOffset: '3px' } }
      })
    }
  ]
}
