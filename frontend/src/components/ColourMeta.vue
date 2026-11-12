<script setup lang="ts">
import { computed } from 'vue'
import { colourMeta, type Lab } from '../lib/colour'

/**
 * The one caption under every colour name: "#859072 · 58.2 −9.6 14.8".
 * Paints add their pigment code as a suffix: "#135A4B · 34.2 −27.0 3.8 · PG7".
 * `pigmentName` goes into the tooltip only.
 */
const props = defineProps<{ lab: Lab; hex?: string; pigment?: string; pigmentName?: string }>()

const m = computed(() => colourMeta(props.lab, props.pigment, props.hex))
const title = computed(() => m.value.title + (props.pigmentName ? ` · ${props.pigmentName}` : ''))
</script>

<template>
  <span class="n block truncate text-caption text-fg-3" :title="title">{{ m.text }}</span>
</template>
