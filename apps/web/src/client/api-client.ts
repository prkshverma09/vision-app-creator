/**
 * Typed fetch-based API client for Vision App Creator.
 *
 * Uses contracts types from @vision-app/contracts for typed request/response
 * wrappers. Handles bearer token attachment, error envelope parsing,
 * idempotency keys, and abort propagation.
 *
 * Design decisions (per DESIGN.md section 10):
 * - Fetch-based (browser native), no heavy query library required at this layer.
 * - Aborting a UI fetch does NOT send a server cancellation request.
 * - Idempotency-Key on mutation requests.
 * - Server errors parsed into typed ApiError with ErrorEnvelope fields.
 */

import type { ErrorEnvelope } from '@vision-app/contracts'

// ---------------------------------------------------------------------------
// ApiError
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  public readonly code: string
  public readonly status: number
  public readonly fieldErrors: Record<string, string>
  public readonly requestId: string
  public readonly retryable: boolean

  constructor(opts: {
    code: string
    message: string
    status: number
    fieldErrors?: Record<string, string>
    requestId?: string
    retryable?: boolean
  }) {
    super(opts.message)
    this.name = 'ApiError'
    this.code = opts.code
    this.status = opts.status
    this.fieldErrors = opts.fieldErrors ?? {}
    this.requestId = opts.requestId ?? ''
    this.retryable = opts.retryable ?? false
  }
}

// ---------------------------------------------------------------------------
// Client options & types
// ---------------------------------------------------------------------------

export interface ApiClientOptions {
  /** Async function returning the current bearer token, or null if unauthenticated. */
  getToken: () => Promise<string | null>
  /** Base URL prefix for all requests (default: empty string for same-origin). */
  baseUrl?: string
}

export interface RequestOptions {
  /** AbortSignal for cancelling the fetch (does NOT trigger server cancellation). */
  signal?: AbortSignal
  /** Idempotency key for mutation requests. */
  idempotencyKey?: string
}

export interface ApiClient {
  get<T>(path: string, opts?: RequestOptions): Promise<T>
  post<T>(path: string, body: unknown, opts?: RequestOptions): Promise<T>
  put<T>(path: string, body: unknown, opts?: RequestOptions): Promise<T>
  delete<T>(path: string, opts?: RequestOptions): Promise<T>
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

export function createApiClient(options: ApiClientOptions): ApiClient {
  const { getToken, baseUrl = '' } = options

  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
    opts?: RequestOptions,
  ): Promise<T> {
    const headers: Record<string, string> = {}

    // Attach bearer token if available
    const token = await getToken()
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    // JSON body for mutations
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json'
    }

    // Idempotency key
    if (opts?.idempotencyKey) {
      headers['Idempotency-Key'] = opts.idempotencyKey
    }

    const url = `${baseUrl}${path}`

    const response = await globalThis.fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: opts?.signal,
    })

    // Handle error responses
    if (!response.ok) {
      let errorData: Partial<ErrorEnvelope> = {}
      try {
        errorData = (await response.json()) as Partial<ErrorEnvelope>
      } catch {
        // If we can't parse the error body, use status-based defaults
      }
      throw new ApiError({
        code: errorData.code ?? `http_${response.status}`,
        message: errorData.message ?? response.statusText,
        status: response.status,
        fieldErrors: errorData.field_errors ?? {},
        requestId: errorData.request_id ?? '',
        retryable: errorData.retryable ?? false,
      })
    }

    // Parse successful JSON response
    try {
      const data = (await response.json()) as T
      return data
    } catch {
      throw new ApiError({
        code: 'parse_error',
        message: 'Failed to parse response as JSON',
        status: response.status,
      })
    }
  }

  return {
    get<T>(path: string, opts?: RequestOptions): Promise<T> {
      return request<T>('GET', path, undefined, opts)
    },
    post<T>(path: string, body: unknown, opts?: RequestOptions): Promise<T> {
      return request<T>('POST', path, body, opts)
    },
    put<T>(path: string, body: unknown, opts?: RequestOptions): Promise<T> {
      return request<T>('PUT', path, body, opts)
    },
    delete<T>(path: string, opts?: RequestOptions): Promise<T> {
      return request<T>('DELETE', path, undefined, opts)
    },
  }
}
