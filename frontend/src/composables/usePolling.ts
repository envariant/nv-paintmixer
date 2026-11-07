import { onScopeDispose, ref } from 'vue'

/**
 * Poll `fn` every `intervalMs` until `done(result)` is true or `stop()` is called.
 * Used for background calibration fits.
 */
export function usePolling<T>(fn: () => Promise<T>, done: (v: T) => boolean, intervalMs = 500) {
  const result = ref<T | null>(null)
  const error = ref<unknown>(null)
  const running = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null

  async function tick(): Promise<void> {
    try {
      const v = await fn()
      result.value = v as never
      if (done(v)) {
        running.value = false
        return
      }
    } catch (e) {
      error.value = e
      running.value = false
      return
    }
    if (running.value) timer = setTimeout(tick, intervalMs)
  }

  function start(): Promise<void> {
    stop()
    error.value = null
    running.value = true
    return tick()
  }

  function stop(): void {
    running.value = false
    if (timer) clearTimeout(timer)
    timer = null
  }

  onScopeDispose(stop)
  return { result, error, running, start, stop }
}
