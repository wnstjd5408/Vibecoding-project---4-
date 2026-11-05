// 사전 용어 서버 호출(API spec v0.2 E19~E23, 상세는 E06)을 모은 파일이다. 화면은 이 파일의 함수만 부른다.
// 요청·응답 모양은 backend/app/admin_glossary.py·glossary.py를 따른다. 가짜 응답은 VITE_API_MOCK=true일 때 apiFetch가 고른다.
import { isApiError } from '../../api/client.ts'
import type { ApiRequestInit } from '../../api/client.ts'

// useOperatorApi()가 돌려주는 함수. 권한 상실(401·403)이면 로그인 상태를 다시 읽고 오류는 그대로 던진다.
export type OperatorFetch = <T>(path: string, init?: ApiRequestInit) => Promise<T>

// E19 목록의 용어 하나. 설명과 이미지는 목록에 없고 E06으로 따로 읽는다.
export type GlossaryTerm = { id: number; key: string; label: string }

export type GlossaryImage = { id: number; url: string; alt: string }

// E06 상세: 설명(마크다운)과 이미지
export type GlossaryDetail = { description: string; images: GlossaryImage[] }

export type TermInput = { label: string; description: string }

// 저장할 때 이미지를 어떻게 할지: 지울 이미지 id와 새로 올릴 파일(한 장). 교체는 새 파일을 올려 성공한 뒤에 지운다(올리기가 실패해도 기존 그림이 남게).
export type ImageChange = { removeIds: number[]; upload: File | null }

// 서버가 용어 key를 만드는 규칙(backend/app/glossary_spans.py normalize_key): NFC, 공백 정리, 영문(ASCII)만 소문자.
// 서버의 E20은 같은 key면 새로 만들지 않고 기존 용어를 덮어쓰므로, 새 용어를 등록하기 전에 같은 key가 있는지 본다.
export function termKey(label: string): string {
  return label
    .normalize('NFC')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/[A-Z]/g, (letter) => letter.toLowerCase())
}

// 한 번에 받을 쪽 수의 상한. 용어가 이보다 많으면 나머지는 목록에 나오지 않는다(100개씩 20쪽).
const MAX_PAGES = 20

// E19: 사전 용어 목록(id 내림차순). next_cursor가 있으면 이어서 받는다.
export async function listTerms(operatorFetch: OperatorFetch): Promise<GlossaryTerm[]> {
  const terms: GlossaryTerm[] = []
  let cursor: string | undefined
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const result = await operatorFetch<{ terms: GlossaryTerm[]; next_cursor: string | null }>('/api/admin/glossary', {
      query: { limit: 100, cursor },
    })
    terms.push(...result.terms)
    if (!result.next_cursor) break
    cursor = result.next_cursor
  }
  return terms
}

// E06: 용어 하나의 설명과 이미지. 사전에 없는 용어는 404 not_found다.
export async function readTerm(operatorFetch: OperatorFetch, id: number): Promise<GlossaryDetail> {
  const result = await operatorFetch<{ body_markdown: string; images: GlossaryImage[] }>(`/api/glossary/${id}`)
  return { description: result.body_markdown, images: result.images }
}

// 설명은 저장했지만 이미지 단계가 실패했다. 서버에는 설명이 저장돼 있으므로 saved로 화면이 목록을 갱신한다.
//  - upload: 새 이미지를 올리지 못했다. 지우려던 기존 이미지는 아직 지우지 않았다.
//  - remove: 이미지를 지우지 못했다. uploaded가 true면 새 이미지는 올라가서 기존 이미지와 함께 남아 있다.
export class ImageNotSavedError extends Error {
  readonly saved: GlossaryTerm
  readonly stage: 'upload' | 'remove'
  readonly uploaded: boolean
  constructor(saved: GlossaryTerm, stage: 'upload' | 'remove', uploaded: boolean, cause: unknown) {
    super('Glossary entry saved but its image change was not', { cause })
    this.name = 'ImageNotSavedError'
    this.saved = saved
    this.stage = stage
    this.uploaded = uploaded
  }
}

// E20·E22·E23: 용어 이름과 설명을 저장한 뒤 이미지를 바꾼다. E20은 label에서 key를 만들어 같은 key의 용어를 고치거나 새로 만든다
// (id를 받지 않고 이름 변경도 없다). 이미지는 새 파일을 먼저 올리고, 성공한 뒤에 지울 것을 지운다. 올리기가 실패하면 기존 그림은 그대로다.
// 올린 뒤 지우기가 실패하면 새 이미지와 기존 이미지가 함께 남는다. 이미지 단계가 실패하면 ImageNotSavedError다.
export async function saveTerm(operatorFetch: OperatorFetch, input: TermInput, image: ImageChange): Promise<GlossaryTerm> {
  const { term } = await operatorFetch<{ term: GlossaryTerm }>('/api/admin/glossary', {
    method: 'POST',
    body: { label: input.label, body_markdown: input.description },
  })
  if (image.upload) {
    const form = new FormData()
    form.append('file', image.upload)
    try {
      await operatorFetch(`/api/admin/glossary/${term.id}/images`, { method: 'POST', body: form })
    } catch (failure) {
      throw new ImageNotSavedError(term, 'upload', false, failure)
    }
  }
  try {
    for (const imageId of image.removeIds) {
      await operatorFetch(`/api/admin/glossary/${term.id}/images/${imageId}`, { method: 'DELETE' })
    }
  } catch (failure) {
    throw new ImageNotSavedError(term, 'remove', image.upload !== null, failure)
  }
  return term
}

// E20의 422가 가리킨 입력 칸과 이유(fields[].reason). 값이 있는 칸만 오류다. 이름은 서버의 fields[].name(label·body_markdown)을 폼의 칸에 맞춘다.
export type FieldReasons = { label?: string; description?: string }

const FIELD_KEYS: Record<string, keyof FieldReasons> = { label: 'label', body_markdown: 'description' }

// 설명 저장(E20) 실패를 분류한다. 422 validation_failed면 어느 칸이 왜 틀렸는지 알려 준다. message 글자로는 가르지 않는다.
export function classifySaveFailure(error: unknown): { kind: 'invalid'; fields: FieldReasons } | { kind: 'other' } {
  if (!isApiError(error, 'validation_failed')) return { kind: 'other' }
  const fields: FieldReasons = {}
  for (const field of error.fields) {
    const key = FIELD_KEYS[field.name]
    if (key) fields[key] = field.reason
  }
  return Object.keys(fields).length > 0 ? { kind: 'invalid', fields } : { kind: 'other' }
}

// 이미지 올리기(E22)가 서버에서 거절된 이유. 413 payload_too_large, 415 unsupported_media_type, 422 validation_failed(file)다.
export type ImageFailure = 'too_large' | 'unsupported' | 'invalid' | 'other'

export function classifyImageFailure(cause: unknown): ImageFailure {
  if (isApiError(cause, 'payload_too_large')) return 'too_large'
  if (isApiError(cause, 'unsupported_media_type')) return 'unsupported'
  if (isApiError(cause, 'validation_failed')) return 'invalid'
  return 'other'
}

// E21: 사전 설명 삭제. 설명과 이미지만 지우고 용어 자체(terms 행)는 서버에 남는다(D-060). 사전 목록에서는 사라진다.
export async function deleteDescription(operatorFetch: OperatorFetch, id: number): Promise<void> {
  await operatorFetch(`/api/admin/glossary/${id}`, { method: 'DELETE' })
}
