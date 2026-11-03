// 운영자 신고(E25·E26)와 사전에 바른 설명 넣기(E20·E22)의 가짜 응답. 요청·응답 모양과 검증 규칙은 backend/app/admin_reports.py·
// admin_glossary.py를 따르고 값은 모두 합성이다. 이 저장소는 새로 고치면 처음 상태로 돌아간다.
import type { ApiErrorBody, FieldError } from '../types.ts'
import { mockError, operatorOnly } from './handlers.ts'
import type { MockResponse, Route } from './handlers.ts'

const FIELD_MESSAGES: Record<string, string> = {
  required: 'Value is required',
  too_long: 'Value is too long',
  invalid_format: 'Value format is invalid',
  invalid_value: 'Value is not allowed or refers to a missing item',
}

function validationFailed(fields: Array<[name: string, reason: string]>): MockResponse {
  const error: ApiErrorBody = {
    error: {
      code: 'validation_failed',
      message: 'One or more fields are invalid',
      request_id: 'r-mock-0001',
      fields: fields.map(([name, reason]): FieldError => ({ name, reason, message: FIELD_MESSAGES[reason] })),
    },
  }
  return { status: 422, body: error }
}

type MockReport = {
  id: number
  status: 'open' | 'resolved'
  body: string
  target:
    | { type: 'ai_explanation'; id: number; term_key_snapshot: string; body: string }
    | { type: 'quiz_item'; id: number; question: string; answer: string }
}

// 합성 신고. 실제 신고가 아니다. 서버처럼 id가 큰 것부터 준다.
let reports: MockReport[] = [
  { id: 3, status: 'resolved', body: '합성 신고 내용', target: { type: 'ai_explanation', id: 30, term_key_snapshot: 'DNS', body: '합성 AI 설명 예시: 이미 처리된 신고예요.' } },
  { id: 2, status: 'open', body: '합성 신고 내용', target: { type: 'quiz_item', id: 20, question: '합성 문항 예시: 이 문항의 정답이 맞는지 확인해 주세요.', answer: '합성 정답' } },
  { id: 1, status: 'open', body: '합성 신고 내용', target: { type: 'ai_explanation', id: 10, term_key_snapshot: 'TCP', body: '합성 AI 설명 예시: 데이터를 순서대로 보내 줘요.' } },
]
const invalidatedExplanations = new Set<number>()

// 사전 용어. 같은 key(이름을 정리한 값)로 저장하면 그 용어를 고친다(E20).
const terms = new Map<string, { id: number; key: string; label: string }>()
let nextTermId = 100
let nextImageId = 1

const BIGINT = /^[1-9][0-9]{0,18}$/
const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp']
const IMAGE_MAX_BYTES = 4 * 1024 * 1024
const MAX_LABEL = 100

function strictObject(body: unknown, allowed: string[]): { input: Record<string, unknown>; unknown: string[] } {
  const input = body !== null && typeof body === 'object' && !Array.isArray(body) ? (body as Record<string, unknown>) : {}
  return { input, unknown: Object.keys(input).filter((name) => !allowed.includes(name)) }
}

export const adminReportRoutes: Route[] = [
  // E25 신고 목록. status(기본 open)가 같은 신고를 id 내림차순으로 limit(기본 100)개 주고, 더 있으면 next_cursor를 준다.
  {
    method: 'GET',
    pattern: /^\/api\/admin\/reports$/,
    handle: ({ query }) => {
      const denied = operatorOnly()
      if (denied) return denied
      const status = query.get('status') ?? 'open'
      if (status !== 'open' && status !== 'resolved') return validationFailed([['status', 'invalid_value']])
      const limitText = query.get('limit')
      const limit = limitText === null ? 100 : Number(limitText)
      if (!Number.isInteger(limit) || limit < 1 || limit > 100) return validationFailed([['limit', 'invalid_format']])
      const cursor = query.get('cursor')
      if (cursor !== null && !BIGINT.test(cursor)) return validationFailed([['cursor', 'invalid_format']])
      const rows = reports.filter((report) => report.status === status && (cursor === null || report.id < Number(cursor)))
      const page = rows.slice(0, limit)
      return {
        status: 200,
        body: {
          reports: page.map(({ id, status: state, body, target }) => ({ id, status: state, body, target })),
          next_cursor: rows.length > limit ? String(page[page.length - 1].id) : null,
        },
      }
    },
  },
  // E26 신고 처리. 본문은 { status: "resolved", invalidate_explanation?: boolean }이고 모르는 필드는 거부한다. 이미 처리된 신고도 200이다.
  {
    method: 'PATCH',
    pattern: /^\/api\/admin\/reports\/([^/]+)$/,
    handle: ({ body }, [reportId]) => {
      const denied = operatorOnly()
      if (denied) return denied
      if (!BIGINT.test(reportId)) return mockError(404, 'not_found', 'Resource not found')
      const { input, unknown } = strictObject(body, ['status', 'invalidate_explanation'])
      const problems: Array<[string, string]> = unknown.map((name) => [name, 'invalid_format'])
      if (!('status' in input)) problems.push(['status', 'required'])
      else if (input.status !== 'resolved') problems.push(['status', 'invalid_value'])
      if ('invalidate_explanation' in input && typeof input.invalidate_explanation !== 'boolean') problems.push(['invalidate_explanation', 'invalid_format'])
      if (problems.length > 0) return validationFailed(problems)
      const report = reports.find((item) => item.id === Number(reportId))
      if (!report) return mockError(404, 'not_found', 'Resource not found')
      if (input.invalidate_explanation === true && report.target.type === 'ai_explanation') invalidatedExplanations.add(report.target.id)
      reports = reports.map((item) => (item.id === report.id ? { ...item, status: 'resolved' } : item))
      return { status: 200, body: { id: report.id, status: 'resolved' } }
    },
  },
  // E20 사전 설명 저장. 새 용어면 201, 같은 이름의 용어가 이미 있으면 그 용어를 고치고 200이다.
  {
    method: 'POST',
    pattern: /^\/api\/admin\/glossary$/,
    handle: ({ body }) => {
      const denied = operatorOnly()
      if (denied) return denied
      const { input, unknown } = strictObject(body, ['label', 'body_markdown'])
      const problems: Array<[string, string]> = unknown.map((name) => [name, 'invalid_format'])
      const label = input.label
      if (typeof label !== 'string') problems.push(['label', label === undefined ? 'required' : 'invalid_format'])
      else if (label.length === 0) problems.push(['label', 'required'])
      else if (label.length > MAX_LABEL) problems.push(['label', 'too_long'])
      if ('body_markdown' in input && typeof input.body_markdown !== 'string') problems.push(['body_markdown', 'invalid_format'])
      if (problems.length > 0) return validationFailed(problems)
      const trimmed = (label as string).trim()
      const key = trimmed.normalize('NFC').toLowerCase()
      if (!key) return validationFailed([['label', 'required']])
      const existing = terms.get(key)
      const term = { id: existing?.id ?? nextTermId++, key, label: trimmed }
      terms.set(key, term)
      return { status: existing ? 200 : 201, body: { term } }
    },
  },
  // E22 사전 이미지 올리기. 멀티파트의 file(png·jpeg·webp, 4MB 이하)과 선택 alt를 받는다. 서버는 내용으로 형식을 판정하지만 여기서는 type으로 본다.
  {
    method: 'POST',
    pattern: /^\/api\/admin\/glossary\/([^/]+)\/images$/,
    handle: ({ body }, [termId]) => {
      const denied = operatorOnly()
      if (denied) return denied
      if (!BIGINT.test(termId)) return mockError(404, 'not_found', 'Resource not found')
      const file = body instanceof FormData ? body.get('file') : null
      if (!(file instanceof File)) return validationFailed([['file', 'required']])
      if (file.size > IMAGE_MAX_BYTES) return mockError(413, 'payload_too_large', 'Request is too large')
      if (!IMAGE_TYPES.includes(file.type)) return mockError(415, 'unsupported_media_type', 'Unsupported file type')
      if (![...terms.values()].some((term) => term.id === Number(termId))) return mockError(404, 'not_found', 'Resource not found')
      return { status: 201, body: { id: nextImageId++ } }
    },
  },
]
