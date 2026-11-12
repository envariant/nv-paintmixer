<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import MixCompose from '../components/mix/MixCompose.vue'
import MixRun from '../components/mix/MixRun.vue'

/** Mix composes a recipe; with ?job=<id> it shows that job running on the machine. */
const route = useRoute()
const running = computed(() => !!route.query.job)
</script>

<template>
  <MixRun v-if="running" />
  <MixCompose v-else />
</template>
