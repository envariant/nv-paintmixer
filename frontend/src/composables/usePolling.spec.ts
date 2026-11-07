import { describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { usePolling } from './usePolling'

describe('usePolling', () => {
  it('polls until done', async () => {
    vi.useFakeTimers()
    let n = 0
    const scope = effectScope()
    const p = scope.run(() => usePolling(async () => ++n, (v) => v >= 3, 100))!
    await p.start()
    expect(p.result.value).toBe(1)
    expect(p.running.value).toBe(true)
    await vi.advanceTimersByTimeAsync(100)
    await vi.advanceTimersByTimeAsync(100)
    expect(p.result.value).toBe(3)
    expect(p.running.value).toBe(false)
    scope.stop()
    vi.useRealTimers()
  })
  it('stops on error', async () => {
    const scope = effectScope()
    const p = scope.run(() => usePolling(async () => { throw new Error('x') }, () => false))!
    await p.start()
    expect(p.running.value).toBe(false)
    expect((p.error.value as Error).message).toBe('x')
    scope.stop()
  })
})
