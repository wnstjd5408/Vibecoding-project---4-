// 운영자 용어 사전(E19~E23)의 가짜 응답과, 운영자가 만든 용어를 돌려주는 E06 응답. 요청·응답 모양과 검증 규칙은
// backend/app/admin_glossary.py·glossary.py를 따르고 값은 모두 합성이다. 이 저장소는 새로 고치면 처음 상태로 돌아간다.
import type { ApiErrorBody, FieldError, GlossaryResponse } from '../types.ts'
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

type MockImage = { id: number; url: string; alt: string }
type MockTerm = { id: number; key: string; label: string; body: string; images: MockImage[] }

// 합성 용어. 실제 용어가 아니다. 서버처럼 id가 큰 것부터 목록에 준다.
let terms: MockTerm[] = [
  { id: 1, key: 'dns', label: 'DNS', body: '도메인 이름을 서버의 숫자 주소로 바꿔 주는 이름 찾기 서비스예요.', images: [] },
  { id: 2, key: '패킷', label: '패킷', body: '네트워크로 보내는 데이터를 잘게 나눈 조각이에요.', images: [] },
  { id: 3, key: '라우터', label: '라우터', body: '패킷이 갈 길을 골라 전달하는 장비예요.', images: [] },
  { id: 4, key: '캐시', label: '캐시', body: '자주 쓰는 데이터를 가까운 곳에 잠시 보관해 두는 방식이에요.', images: [] },
]
let nextTermId = 5
let nextImageId = 1

const BIGINT = /^[1-9][0-9]{0,18}$/
const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp']
const IMAGE_MAX_BYTES = 4 * 1024 * 1024
const MAX_LABEL = 200
const MAX_BODY = 200_000

// 서버의 normalize_key와 같은 규칙: NFC, 공백 정리, 영문(ASCII)만 소문자.
function keyOf(label: string): string {
  return label
    .normalize('NFC')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[A-Z]/g, (letter) => letter.toLowerCase())
}

// 운영자가 만든 용어를 E06 응답 모양으로 준다. 없으면 null이다(E06 가짜 응답이 기본 용어로 이어 간다).
export function readOperatorTerm(id: number): GlossaryResponse | null {
  const term = terms.find((item) => item.id === id)
  if (!term) return null
  return { term: { id: term.id, key: term.key, label: term.label }, body_markdown: term.body, images: term.images.map((image) => ({ ...image })) }
}

function strictObject(body: unknown, allowed: string[]): { input: Record<string, unknown>; unknown: string[] } {
  const input = body !== null && typeof body === 'object' && !Array.isArray(body) ? (body as Record<string, unknown>) : {}
  return { input, unknown: Object.keys(input).filter((name) => !allowed.includes(name)) }
}

const gone = () => mockError(404, 'not_found', 'Resource not found')

export const adminGlossaryRoutes: Route[] = [
  // E19 사전 용어 목록. id 내림차순이고 limit(기본 100)개를 주며, 더 있으면 next_cursor를 준다.
  {
    method: 'GET',
    pattern: /^\/api\/admin\/glossary$/,
    handle: ({ query }) => {
      const denied = operatorOnly()
      if (denied) return denied
      const limitText = query.get('limit')
      const limit = limitText === null ? 100 : Number(limitText)
      if (!Number.isInteger(limit) || limit < 1 || limit > 100) return validationFailed([['limit', 'invalid_format']])
      const cursor = query.get('cursor')
      if (cursor !== null && !BIGINT.test(cursor)) return validationFailed([['cursor', 'invalid_format']])
      const rows = [...terms].sort((a, b) => b.id - a.id).filter((term) => cursor === null || term.id < Number(cursor))
      const page = rows.slice(0, limit)
      return {
        status: 200,
        body: {
          terms: page.map(({ id, key, label }) => ({ id, key, label })),
          next_cursor: rows.length > limit ? String(page[page.length - 1].id) : null,
        },
      }
    },
  },
  // E20 사전 설명 저장. label에서 key를 만들어 같은 key의 용어를 고치면 200, 새로 만들면 201이다. 이름 변경은 없다.
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
      const description = input.body_markdown
      if (description !== undefined && typeof description !== 'string') problems.push(['body_markdown', 'invalid_format'])
      else if (typeof description === 'string' && description.length > MAX_BODY) problems.push(['body_markdown', 'too_long'])
      if (problems.length > 0) return validationFailed(problems)
      const trimmed = (label as string).trim()
      const key = keyOf(trimmed)
      if (!key) return validationFailed([['label', 'required']])
      const existing = terms.find((term) => term.key === key)
      const text = typeof description === 'string' ? description : ''
      if (existing) {
        existing.label = trimmed
        existing.body = text
        return { status: 200, body: { term: { id: existing.id, key, label: trimmed } } }
      }
      const created: MockTerm = { id: nextTermId++, key, label: trimmed, body: text, images: [] }
      terms = [...terms, created]
      return { status: 201, body: { term: { id: created.id, key, label: trimmed } } }
    },
  },
  // E21 사전 설명 삭제. 설명과 이미지를 지우고 목록에서 빠진다. 사전 용어가 아니면 404다.
  {
    method: 'DELETE',
    pattern: /^\/api\/admin\/glossary\/([^/]+)$/,
    handle: (_request, [termId]) => {
      const denied = operatorOnly()
      if (denied) return denied
      if (!BIGINT.test(termId) || !terms.some((term) => term.id === Number(termId))) return gone()
      terms = terms.filter((term) => term.id !== Number(termId))
      return { status: 204 }
    },
  },
  // E22 사전 이미지 올리기. 멀티파트의 file(png·jpeg·webp, 4MB 이하)과 선택 alt를 받는다. 서버는 내용으로 형식을 판정하지만 여기서는 type으로 본다.
  {
    method: 'POST',
    pattern: /^\/api\/admin\/glossary\/([^/]+)\/images$/,
    handle: ({ body }, [termId]) => {
      const denied = operatorOnly()
      if (denied) return denied
      if (!BIGINT.test(termId)) return gone()
      const file = body instanceof FormData ? body.get('file') : null
      if (!(file instanceof File)) return validationFailed([['file', 'required']])
      if (file.size > IMAGE_MAX_BYTES) return mockError(413, 'payload_too_large', 'Request is too large')
      if (!IMAGE_TYPES.includes(file.type)) return mockError(415, 'unsupported_media_type', 'Unsupported file type')
      const term = terms.find((item) => item.id === Number(termId))
      if (!term) return gone()
      const alt = body instanceof FormData ? body.get('alt') : null
      const image: MockImage = { id: nextImageId++, url: URL.createObjectURL(file), alt: typeof alt === 'string' ? alt.trim() : '' }
      term.images = [...term.images, image]
      return { status: 201, body: { id: image.id } }
    },
  },
  // E23 사전 이미지 삭제. 그 용어의 이미지가 아니면 404다.
  {
    method: 'DELETE',
    pattern: /^\/api\/admin\/glossary\/([^/]+)\/images\/([^/]+)$/,
    handle: (_request, [termId, imageId]) => {
      const denied = operatorOnly()
      if (denied) return denied
      if (!BIGINT.test(termId) || !BIGINT.test(imageId)) return gone()
      const term = terms.find((item) => item.id === Number(termId))
      if (!term || !term.images.some((image) => image.id === Number(imageId))) return gone()
      term.images = term.images.filter((image) => image.id !== Number(imageId))
      return { status: 204 }
    },
  },
]
