<script setup lang="ts">
import { computed, ref } from 'vue'
import { isHex, parseLab } from '../../lib/colour'

/** The empty stage's next step: type a colour (hex or L a b), or pick one in the Library. */
const emit = defineEmits<{ target: [kind: 'hex' | 'lab', value: string] }>()
const text = ref('')
const kind = computed(() => (isHex(text.value) ? 'hex' : parseLab(text.value) ? 'lab' : null))
function submit() {
  if (kind.value) emit('target', kind.value, text.value.trim())
}
</script>

<template>
  <form class="w-[280px] max-w-[80%] flex flex-col items-stretch gap-3 text-center" @submit.prevent="submit">
    <span class="on-surround text-ui">Choose a colour to match</span>
    <label class="flex items-center h-field rounded-field bg-page px-3">
      <input
        v-model="text"
        aria-label="Colour as hex (#859072) or L a b (58.2 -9.6 14.8)"
        placeholder="#859072 or 58.2 −9.6 14.8"
        class="n flex-1 min-w-0 bg-transparent text-body text-fg outline-none"
      />
    </label>
    <button type="submit" class="btn-primary focus-ring" :disabled="!kind" :class="!kind && 'opacity-60'">Find a mix</button>
    <RouterLink to="/library" class="on-surround underline underline-offset-4 focus-ring rounded-pill">
      or pick one in the Library
    </RouterLink>
  </form>
</template>
