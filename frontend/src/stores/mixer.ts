import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, ApiError, type Schemas, unwrap } from '../api/client'
import { isHex, normaliseHex, parseLab } from '../lib/colour'

export type TargetMode = 'library' | 'picker' | 'hex' | 'lab'
export type SolveResponse = Schemas['SolveResponse']
export type Candidate = Schemas['CandidateOut']

/** Build the API target from the Mixer's target picker state; null if incomplete/invalid. */
export function buildTarget(mode: TargetMode, value: string, libraryId: number | null): Schemas['TargetIn'] | null {
  switch (mode) {
    case 'library':
      return libraryId == null ? null : { library_id: libraryId }
    case 'picker':
    case 'hex':
      return isHex(value) ? { hex: normaliseHex(value) } : null
    case 'lab': {
      const lab = parseLab(value)
      return lab ? { lab } : null
    }
  }
}

export const useMixerStore = defineStore('mixer', () => {
  const mode = ref<TargetMode>('hex')
  const value = ref('#7a9e9f')
  const libraryId = ref<number | null>(null)
  const constraints = ref<Omit<Schemas['SolveRequest'], 'target'>>({ search: 'auto' })
  const result = ref<SolveResponse | null>(null)
  const status = ref<'idle' | 'solving' | 'done' | 'error'>('idle')
  const error = ref<{ code: string; message: string } | null>(null)

  const target = computed(() => buildTarget(mode.value, value.value, libraryId.value))
  const canSolve = computed(() => target.value !== null && status.value !== 'solving')
  const best = computed<Candidate | null>(() => result.value?.candidates[0] ?? null)

  async function solve(): Promise<void> {
    if (!target.value) return
    status.value = 'solving'
    error.value = null
    try {
      result.value = unwrap(
        await api.POST('/api/v1/solve', { body: { ...constraints.value, target: target.value } }),
      )
      status.value = 'done'
    } catch (e) {
      status.value = 'error'
      error.value =
        e instanceof ApiError ? { code: e.code, message: e.message } : { code: 'network', message: String(e) }
    }
  }

  async function createJob(candidate: Candidate, name = ''): Promise<Schemas['JobRead']> {
    if (!target.value || !result.value) throw new Error('solve first')
    const components = Object.fromEntries(candidate.components.map((c) => [c.paint_id, c.fraction]))
    return unwrap(
      await api.POST('/api/v1/jobs', {
        body: {
          name,
          target: target.value,
          components,
          batch_volume_ml: result.value.batch_volume_ml,
          constraints: { ...constraints.value },
        },
      }),
    )
  }

  return { mode, value, libraryId, constraints, result, status, error, target, canSolve, best, solve, createJob }
})
