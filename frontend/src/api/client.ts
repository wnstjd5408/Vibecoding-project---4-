// 화면이 /api를 부르는 유일한 길이다. 브라우저는 FastAPI(/api)만 부르고, 응답은 개발 서버 프록시를 거쳐 같은 출처로 온다.
// 쿠키 세션을 쓰므로 요청에 쿠키를 싣는다(credentials: 'include').
import { handleMock } from './mocks/handlers.ts'
import { getApiSource } from './source.ts'
import type { ApiSource } from './source.ts'
import type { ApiErrorBody, FieldError } from './types.ts'

// 서버 응답이 아니라 클라이언트가 만든 code다. 서버 code(login_required 등)와 겹치지 않는다.
export const CLIENT_ERROR_CODES = {
  networkError: 'network_error',
  unexpectedResponse: 'unexpected_response',
} as const

export class ApiError extends Error {
  status: number
  code: string
  detail: string | undefined
  fields: FieldError[]
  requestId: string | undefined
  retryAfterSeconds: number | undefined

  // message는 영어 고정 문구라 화면에 띄우거나 분기에 쓰지 않는다. 화면 문구는 code·detail·fields[].reason으로 고른다.
  constructor(status: number, error: ApiErrorBody['error']) {
    super(error.message)
    this.name = 'ApiError'
    this.status = status
    this.code = error.code
    this.detail = error.detail
    this.fields = error.fields ?? []
    this.requestId = error.request_id
    this.retryAfterSeconds = error.retry_after_seconds
  }
}

// code(와 detail)로 오류를 구분한다. 예: isApiError(error, 'login_required')
export function isApiError(error: unknown, code?: string, detail?: string): error is ApiError {
  if (!(error instanceof ApiError)) return false
  if (code !== undefined && error.code !== code) return false
  if (detail !== undefined && error.detail !== detail) return false
  return true
}

export type ApiRequestInit = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  // 있으면 JSON으로 보낸다.
  body?: unknown
  query?: Record<string, string | number | undefined>
  // Idempotency-Key 같은 추가 헤더
  headers?: Record<string, string>
  // 지정하지 않으면 getApiSource()를 따른다. 한 호출만 가짜 응답이나 실제 백엔드로 보낼 때 쓴다.
  source?: ApiSource
  signal?: AbortSignal
}

type Transported = { status: number; body: unknown }

function buildUrl(path: string, query: ApiRequestInit['query']): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) params.set(key, String(value))
  }
  const search = params.toString()
  return search ? `${path}?${search}` : path
}

async function realTransport(url: string, init: ApiRequestInit): Promise<Transported> {
  let response: Response
  try {
    response = await fetch(url, {
      method: init.method ?? 'GET',
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        ...(init.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
      signal: init.signal,
    })
  } catch (cause) {
    if (init.signal?.aborted) throw cause
    throw new ApiError(0, { code: CLIENT_ERROR_CODES.networkError, message: 'Network request failed', request_id: '' })
  }
  const text = await response.text()
  let body: unknown
  try {
    body = text ? JSON.parse(text) : undefined
  } catch {
    body = undefined
  }
  return { status: response.status, body }
}

function mockTransport(url: string, init: ApiRequestInit): Transported {
  const parsed = new URL(url, 'http://mock.invalid')
  return handleMock({
    method: init.method ?? 'GET',
    path: parsed.pathname,
    query: parsed.searchParams,
    body: init.body,
  }) as Transported
}

function isErrorBody(body: unknown): body is ApiErrorBody {
  const error = (body as { error?: { code?: unknown } } | null | undefined)?.error
  return typeof error?.code === 'string'
}

// path는 '/api/me'처럼 spec의 경로를 그대로 쓴다. 성공하면 본문을 돌려주고(204는 undefined), 실패하면 ApiError를 던진다.
export async function apiFetch<T>(path: string, init: ApiRequestInit = {}): Promise<T> {
  const url = buildUrl(path, init.query)
  const source = init.source ?? getApiSource()
  const { status, body } = source === 'mock' ? mockTransport(url, init) : await realTransport(url, init)

  if (status >= 200 && status < 300) return body as T
  if (isErrorBody(body)) throw new ApiError(status, body.error)
  // 1.4 형식이 아닌 응답(프록시 오류 등). 서버 code와 겹치지 않는 클라이언트 code로 알린다.
  throw new ApiError(status, {
    code: CLIENT_ERROR_CODES.unexpectedResponse,
    message: 'Unexpected response',
    request_id: '',
  })
}
