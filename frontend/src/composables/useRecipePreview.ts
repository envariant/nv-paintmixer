import { computed, type Ref } from 'vue'
import { api, type Schemas, unwrap } from '../api/client'
import { deltaE2000, ForwardModel, type Illuminant, type ModelTables, type Prediction } from '../lib/km'

/** Build a browser forward model for a fitted model version (two small API calls). */
export async function loadForwardModel(version: number): Promise<ForwardModel> {
  const [spectra, tables] = await Promise.all([
    api.GET('/api/v1/models/{version}/spectra', { params: { path: { version } } }).then(unwrap),
    api.GET('/api/v1/colorimetry').then(unwrap),
  ])
  return new ForwardModel(modelTables(spectra), tables)
}

export function modelTables(s: Schemas['ModelSpectra']): ModelTables {
  return {
    paint_ids: s.paints.map((p) => p.paint_id),
    K: s.paints.map((p) => p.K),
    S: s.paints.map((p) => p.S),
    k1: s.k1,
    k2: s.k2,
  }
}

/**
 * Live preview of a recipe while it is edited (keep the model in a `shallowRef`): recomputes the predicted colour (and the dE2000
 * to an optional target) on every change, locally, without calling the server.
 */
export function useRecipePreview(
  model: Ref<ForwardModel | null>,
  fractions: Ref<Record<string, number>>,
  target?: Ref<number[] | null>,
  illuminant: Ref<Illuminant> | Illuminant = 'D65',
) {
  const result = computed<{ prediction: Prediction | null; error: string | null }>(() => {
    if (!model.value) return { prediction: null, error: null }
    const active = Object.fromEntries(Object.entries(fractions.value).filter(([, v]) => v > 0))
    if (Object.keys(active).length === 0) return { prediction: null, error: 'add at least one paint' }
    try {
      const ill = typeof illuminant === 'string' ? illuminant : illuminant.value
      return { prediction: model.value.predict(active, ill), error: null }
    } catch (e) {
      return { prediction: null, error: (e as Error).message }
    }
  })
  const prediction = computed(() => result.value.prediction)
  const error = computed(() => result.value.error)
  const deltaE = computed(() =>
    prediction.value && target?.value ? deltaE2000(prediction.value.lab, target.value) : null,
  )
  return { prediction, deltaE, error }
}
