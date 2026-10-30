// AI 설명(E09) 요청. 재시도 키 규칙(Q-N5)과 오류 분류를 한곳에 둔다.
import { apiFetch, isApiError } from '../api/client.ts'
import type { ExplainResponse } from '../api/types.ts'

export type ExplainTarget = { noteId: number; revision: number; start: number; end: number }

// 원문(UTF-16 위치)의 범위를 요청에 쓰는 코드포인트 위치로 바꾼다. 이모지는 UTF-16으로 두 칸이라 그대로 보내면 어긋난다.
export function toCodePointRange(body: string, start: number, end: number): { start: number; end: number } {
  const before = [...body.slice(0, start)].length
  return { start: before, end: before + [...body.slice(start, end)].length }
}

// 키는 한 선택 범위(노트·개정·위치)마다 하나다. 안전하지 않은 http 주소(휴대폰으로 개발 PC에 접속)에는 randomUUID가 없어 getRandomValues로 만든다.
export function newIdempotencyKey(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export type ExplainFailure =
  | 'limit_reached'
  | 'rate_limited'
  | 'ai_unavailable'
  | 'in_progress'
  | 'stale_revision'
  | 'result_unavailable'
  | 'not_found'
  | 'invalid'
  | 'failed'

// 오류를 code·detail로 구분한다. message 글자로 나누지 않는다.
export function classifyExplainError(error: unknown): ExplainFailure {
  if (isApiError(error, 'ai_limit_reached')) return 'limit_reached'
  if (isApiError(error, 'rate_limited')) return 'rate_limited'
  if (isApiError(error, 'ai_unavailable')) return 'ai_unavailable'
  if (isApiError(error, 'conflict', 'in_progress')) return 'in_progress'
  if (isApiError(error, 'conflict', 'stale_revision')) return 'stale_revision'
  if (isApiError(error, 'conflict', 'result_unavailable')) return 'result_unavailable'
  if (isApiError(error, 'not_found')) return 'not_found'
  if (isApiError(error, 'validation_failed') || isApiError(error, 'bad_request')) return 'invalid'
  return 'failed'
}

// 응답을 받지 못해 서버가 처리했는지 모르는 경우와 진행 중(409 in_progress)은 같은 키로 다시 보낸다.
// 그 밖의 응답(성공, AI 실패 502, result_unavailable, 한도·검증 오류 등)은 끝난 요청이라 키를 버리고, 사용자가 다시 시도하면 새 키를 쓴다.
function keepsKey(error: unknown): boolean {
  if (!isApiError(error)) return true
  if (error.code === 'network_error' || error.code === 'unexpected_response') return true
  if (error.status >= 500 && error.code !== 'ai_unavailable') return true
  return isApiError(error, 'conflict', 'in_progress')
}

const keys = new Map<string, string>()
const inFlight = new Map<string, Promise<ExplainResponse>>()

// 같은 선택의 요청이 진행 중이면 새로 보내지 않고 그 요청을 이어서 본다(시트를 닫았다 다시 열어도 중복 호출·새 키가 생기지 않는다).
export function requestExplanation(target: ExplainTarget): Promise<ExplainResponse> {
  const id = `${target.noteId}:${target.revision}:${target.start}:${target.end}`
  const running = inFlight.get(id)
  if (running) return running
  const key = keys.get(id) ?? newIdempotencyKey()
  keys.set(id, key)
  const request = apiFetch<ExplainResponse>('/api/ai/explanations', {
    method: 'POST',
    headers: { 'Idempotency-Key': key },
    body: { note_id: target.noteId, note_revision: target.revision, selection: { start: target.start, end: target.end } },
  }).then(
    (response) => {
      keys.delete(id)
      return response
    },
    (error: unknown) => {
      if (!keepsKey(error)) keys.delete(id)
      throw error
    },
  )
  inFlight.set(id, request)
  const clear = () => {
    if (inFlight.get(id) === request) inFlight.delete(id)
  }
  request.then(clear, clear)
  return request
}
