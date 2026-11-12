import { createPinia } from 'pinia'
import { createApp } from 'vue'
// Typefaces named by the design (tokens.css / tailwind.config.js): Inter for UI, JetBrains Mono for
// code-like values. Each weight file holds every script subset behind a unicode-range, so the
// browser fetches only what a page uses (e.g. the Greek subset for ΔE).
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import './style.css'
import App from './App.vue'
import { makeRouter } from './router'
import { applyTheme, savedTheme } from './lib/theme'

applyTheme(savedTheme())

createApp(App).use(createPinia()).use(makeRouter()).mount('#app')
