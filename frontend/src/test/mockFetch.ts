import { vi } from 'vitest'

export type Route = (req: Request, body: unknown) => { status?: number; json: unknown } | undefined

/** Install a fetch mock that answers by "METHOD /path" and records requests. */
export function mockFetch(routes: Record<string, Route | { status?: number; json: unknown }>) {
  const calls: { method: string; path: string; body: unknown; query: string }[] = []
  const fn = vi.fn(async (req: Request) => {
    const url = new URL(req.url)
    let body: unknown = undefined
    const ct = req.headers.get('content-type') ?? ''
    if (req.method !== 'GET' && ct.includes('application/json')) body = await req.json()
    calls.push({ method: req.method, path: url.pathname, body, query: url.search })
    const key = `${req.method} ${url.pathname}`
    const route = routes[key]
    const res = typeof route === 'function' ? route(req, body) : route
    if (!res) return new Response(JSON.stringify({ error: { code: 'not_found', message: key } }), { status: 404, headers: { 'content-type': 'application/json' } })
    const status = res.status ?? 200
    return new Response(status === 204 ? null : JSON.stringify(res.json), { status, headers: { 'content-type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fn)
  return { fn, calls }
}
