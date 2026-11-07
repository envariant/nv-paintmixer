/**
 * Typed API client generated from the backend OpenAPI schema (`make gen-api`).
 * `schema.d.ts` is generated; do not edit it by hand.
 */
import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export type Schemas = components['schemas']

export interface ApiErrorBody {
  code: string
  message: string
  details?: unknown
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.status = status
    this.code = body.code
    this.details = body.details
  }
}

export function createApi(baseUrl = globalThis.location?.origin ?? '', fetchImpl?: typeof fetch) {
  // Resolve fetch lazily so tests (and polyfills) can replace globalThis.fetch after import.
  return createClient<paths>({ baseUrl, fetch: fetchImpl ?? ((req: Request) => globalThis.fetch(req)) })
}

export const api = createApi()

/** Unwrap an openapi-fetch result, throwing ApiError on the backend's error envelope. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    const env = result.error as { error?: ApiErrorBody } | undefined
    throw new ApiError(
      result.response.status,
      env?.error ?? { code: 'http_error', message: `HTTP ${result.response.status}` },
    )
  }
  return result.data as T
}
