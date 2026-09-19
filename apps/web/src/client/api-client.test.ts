import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import type { ErrorEnvelope } from '@vision-app/contracts'

// ---------------------------------------------------------------------------
// RED tests for the typed API client
// ---------------------------------------------------------------------------
// These tests import the client module and exercise:
// 1. Unauthenticated request rejection (no token -> 401 handling)
// 2. Typed response parsing and malformed JSON handling
// 3. Bearer token attachment
// 4. Error envelope parsing for known API errors
// 5. Idempotency key generation
// 6. Request abort does not send server cancellation
// ---------------------------------------------------------------------------

import {
  createApiClient,
  ApiError,
  type ApiClient,
} from './api-client'

// Minimal fetch mock setup — no MSW needed for unit-level client tests
function mockFetch(response: Partial<Response> & { bodyJson?: unknown; bodyText?: string }) {
  const { bodyJson, bodyText, ...rest } = response
  const resp = {
    ok: rest.status ? rest.status >= 200 && rest.status < 300 : true,
    status: rest.status ?? 200,
    statusText: rest.statusText ?? 'OK',
    headers: new Headers(rest.headers as HeadersInit ?? { 'content-type': 'application/json' }),
    json: () => Promise.resolve(bodyJson),
    text: () => Promise.resolve(bodyText ?? JSON.stringify(bodyJson)),
    clone: () => resp,
  } as unknown as Response
  return vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>().mockResolvedValue(resp)
}

describe('ApiClient', () => {
  let originalFetch: typeof globalThis.fetch

  beforeEach(() => {
    originalFetch = globalThis.fetch
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  // --- 1. Unauthenticated request rejection ---
  describe('unauthenticated requests', () => {
    it('rejects with ApiError when server returns 401', async () => {
      const errorBody: ErrorEnvelope = {
        code: 'unauthenticated',
        message: 'Invalid or missing token',
        field_errors: {},
        request_id: 'req-001',
        retryable: false,
      }
      globalThis.fetch = mockFetch({ status: 401, bodyJson: errorBody })

      const client = createApiClient({ getToken: async () => null })

      await expect(client.get<unknown>('/v1/apps')).rejects.toThrow(ApiError)
      try {
        await client.get<unknown>('/v1/apps')
        expect.unreachable('should have thrown')
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError)
        expect((e as ApiError).code).toBe('unauthenticated')
        expect((e as ApiError).status).toBe(401)
      }
    })

    it('attaches bearer token from getToken', async () => {
      const fetchSpy = mockFetch({ status: 200, bodyJson: { items: [] } })
      globalThis.fetch = fetchSpy

      const client = createApiClient({ getToken: async () => 'test-token-abc' })
      await client.get<{ items: unknown[] }>('/v1/apps')

      const [, init] = fetchSpy.mock.calls[0]
      expect(init?.headers).toBeDefined()
      const headers = new Headers(init!.headers as HeadersInit)
      expect(headers.get('Authorization')).toBe('Bearer test-token-abc')
    })

    it('sends request without Authorization header when token is null', async () => {
      const fetchSpy = mockFetch({ status: 401, bodyJson: { code: 'unauthenticated', message: 'No token', field_errors: {}, request_id: 'r1', retryable: false } })
      globalThis.fetch = fetchSpy

      const client = createApiClient({ getToken: async () => null })
      try { await client.get<unknown>('/v1/apps') } catch { /* expected */ }

      const [, init] = fetchSpy.mock.calls[0]
      const headers = new Headers(init!.headers as HeadersInit)
      expect(headers.has('Authorization')).toBe(false)
    })
  })

  // --- 2. Typed response parsing ---
  describe('response parsing', () => {
    it('parses valid JSON response with correct type', async () => {
      const payload = { id: 'app-1', title: 'My App' }
      globalThis.fetch = mockFetch({ status: 200, bodyJson: payload })

      const client = createApiClient({ getToken: async () => 'tok' })
      const result = await client.get<{ id: string; title: string }>('/v1/apps/app-1')

      expect(result).toEqual(payload)
    })

    it('throws ApiError on malformed JSON response', async () => {
      const fetchFn = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: () => Promise.reject(new SyntaxError('Unexpected token')),
        text: () => Promise.resolve('not json {{'),
        clone: function () { return this },
      } as unknown as Response)
      globalThis.fetch = fetchFn

      const client = createApiClient({ getToken: async () => 'tok' })
      await expect(client.get<unknown>('/v1/apps')).rejects.toThrow(ApiError)
      try {
        await client.get<unknown>('/v1/apps')
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError)
        expect((e as ApiError).code).toBe('parse_error')
      }
    })
  })

  // --- 3. Error envelope parsing ---
  describe('error envelope', () => {
    it('parses server error envelope into ApiError with all fields', async () => {
      const envelope: ErrorEnvelope = {
        code: 'invalid_media',
        message: 'Unsupported codec',
        field_errors: { codec: 'Must be H.264' },
        request_id: 'req-42',
        retryable: false,
      }
      globalThis.fetch = mockFetch({ status: 422, bodyJson: envelope })

      const client = createApiClient({ getToken: async () => 'tok' })
      try {
        await client.post<unknown>('/v1/uploads', { file: 'test.avi' })
        expect.unreachable('should have thrown')
      } catch (e) {
        expect(e).toBeInstanceOf(ApiError)
        const err = e as ApiError
        expect(err.code).toBe('invalid_media')
        expect(err.message).toBe('Unsupported codec')
        expect(err.status).toBe(422)
        expect(err.fieldErrors).toEqual({ codec: 'Must be H.264' })
        expect(err.requestId).toBe('req-42')
        expect(err.retryable).toBe(false)
      }
    })

    it('handles 409 conflict error', async () => {
      const envelope: ErrorEnvelope = {
        code: 'stale_revision',
        message: 'Version conflict',
        field_errors: {},
        request_id: 'req-99',
        retryable: true,
      }
      globalThis.fetch = mockFetch({ status: 409, bodyJson: envelope })

      const client = createApiClient({ getToken: async () => 'tok' })
      await expect(client.post<unknown>('/v1/apps/a1/messages', {})).rejects.toThrow(ApiError)
    })
  })

  // --- 4. POST with body ---
  describe('POST requests', () => {
    it('sends JSON body and correct Content-Type', async () => {
      const fetchSpy = mockFetch({ status: 202, bodyJson: { id: 'turn-1' } })
      globalThis.fetch = fetchSpy

      const client = createApiClient({ getToken: async () => 'tok' })
      const body = { message: 'Build me a red-light app' }
      await client.post<{ id: string }>('/v1/apps/a1/messages', body)

      const [, init] = fetchSpy.mock.calls[0]
      const headers = new Headers(init!.headers as HeadersInit)
      expect(headers.get('Content-Type')).toBe('application/json')
      expect(JSON.parse(init!.body as string)).toEqual(body)
    })
  })

  // --- 5. Idempotency key ---
  describe('idempotency key', () => {
    it('attaches Idempotency-Key header on POST requests', async () => {
      const fetchSpy = mockFetch({ status: 202, bodyJson: {} })
      globalThis.fetch = fetchSpy

      const client = createApiClient({ getToken: async () => 'tok' })
      await client.post<unknown>('/v1/runs', {}, { idempotencyKey: 'idem-123' })

      const [, init] = fetchSpy.mock.calls[0]
      const headers = new Headers(init!.headers as HeadersInit)
      expect(headers.get('Idempotency-Key')).toBe('idem-123')
    })
  })

  // --- 6. Abort does not send server cancellation ---
  describe('abort handling', () => {
    it('aborting a fetch does not trigger a server cancellation request', async () => {
      const controller = new AbortController()
      const fetchSpy = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>().mockImplementation(
        (_input, init) => new Promise((_resolve, reject) => {
          // Check if already aborted
          if (init?.signal?.aborted) {
            reject(new DOMException('Aborted', 'AbortError'))
            return
          }
          init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        })
      )
      globalThis.fetch = fetchSpy

      const client = createApiClient({ getToken: async () => 'tok' })
      // Start request and then abort immediately
      const promise = client.get<unknown>('/v1/runs/r1', { signal: controller.signal })
      // Abort after a microtask to ensure the fetch was started
      await Promise.resolve()
      controller.abort()

      await expect(promise).rejects.toThrow()
      // Only one fetch call was made (the original GET), no cancellation POST
      expect(fetchSpy).toHaveBeenCalledTimes(1)
      // Verify the signal was passed through to fetch
      const [, init] = fetchSpy.mock.calls[0]
      expect(init?.signal).toBe(controller.signal)
    })
  })

  // --- 7. Base URL configuration ---
  describe('base URL', () => {
    it('prepends configured base URL to all requests', async () => {
      const fetchSpy = mockFetch({ status: 200, bodyJson: {} })
      globalThis.fetch = fetchSpy

      const client = createApiClient({ getToken: async () => 'tok', baseUrl: 'https://api.example.com' })
      await client.get<unknown>('/v1/apps')

      const [url] = fetchSpy.mock.calls[0]
      expect(url).toBe('https://api.example.com/v1/apps')
    })
  })
})
