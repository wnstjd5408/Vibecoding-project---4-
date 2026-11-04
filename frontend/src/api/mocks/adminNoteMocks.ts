// 운영자 노트(E04·E05의 운영자 보기와 E15~E18)의 가짜 응답. 요청·응답 모양과 검증 규칙은 backend/app/admin_notes.py(MEG-79)와 notes.py를 따른다.
// 서버의 요청 모델은 모르는 필드를 거부(extra="forbid")한다. E17의 충돌 검사 필드는 expected_revision이다.
// 값은 모두 합성이고 이 저장소는 새로 고치면 처음 상태로 돌아간다.
import type { ApiErrorBody, FieldError, NoteListResponse } from '../types.ts'
import { NOTES, SUBJECTS, mockError, operatorOnly } from './handlers.ts'
import type { MockResponse, Route } from './handlers.ts'
import { getMockSession } from './session.ts'

const FIELD_MESSAGES: Record<string, string> = {
  required: 'Value is required',
  too_long: 'Value is too long',
  out_of_range: 'Value is out of range',
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

type MockNote = {
  id: number
  title: string
  studiedOn: string
  body: string
  subjectIds: number[]
  isPublished: boolean
  revision: number
  // 시험용으로 만들었거나 고친 노트. 이런 노트는 방문자 읽기(E05)에서도 이 저장소의 내용을 준다.
  touched: boolean
}

// 처음 상태는 기존 가짜 노트 목록(NOTES)과 같다. handlers.ts와 서로 불러서 모듈 평가 시점이 아니라 처음 쓸 때 만든다.
let store: MockNote[] | null = null
// 삭제한 노트의 id. 삭제한 뒤에는 기존 예시 노트(11·12)도 읽을 수 없어야 한다.
const deletedIds = new Set<number>()
let nextId = 100

function notes(): MockNote[] {
  store ??= NOTES.map((note) => ({
    id: note.id,
    title: note.title,
    studiedOn: note.studied_on,
    body: `합성 본문 예시: ${note.title}`,
    subjectIds: note.subjects.map((subject) => subject.id),
    isPublished: true,
    revision: 1,
    touched: false,
  }))
  return store
}

const BIGINT = /^[1-9][0-9]{0,18}$/
const DATE = /^\d{4}-\d{2}-\d{2}$/
const gone = () => mockError(404, 'not_found', 'Resource not found')

// 서버 규칙(admin_notes.py): 제목 1~300자, 본문 200,000자 이하
const TITLE_MAX = 300
const BODY_MAX = 200_000

const subjectsOf = (note: MockNote) => SUBJECTS.filter((subject) => note.subjectIds.includes(subject.id)).map(({ id, name }) => ({ id, name }))

// E04. 운영자는 비공개 노트와 is_published·revision·needs_review도 받는다. 과목 목록은 걸러도 전부 오고 공개 노트가 없는 과목은 운영자만 본다.
export function readNoteList(subjectId: string | null): NoteListResponse {
  const operator = getMockSession() === 'operator'
  const visible = notes().filter((note) => operator || note.isPublished)
  const shown = subjectId ? visible.filter((note) => note.subjectIds.some((id) => String(id) === subjectId)) : visible
  const counts = (id: number) => visible.filter((note) => note.subjectIds.includes(id)).length
  return {
    subjects: SUBJECTS.map(({ id, name }) => ({ id, name, note_count: counts(id) })).filter((subject) => operator || subject.note_count > 0),
    notes: shown.map((note) => ({
      id: note.id,
      title: note.title,
      studied_on: note.studiedOn,
      subjects: subjectsOf(note),
      parent_note_id: null,
      ...(operator ? { is_published: note.isPublished, revision: note.revision, needs_review: false } : {}),
    })),
  }
}

// E05(노트 읽기)가 이 저장소의 노트를 어떻게 다룰지.
//  - found: 이 저장소의 내용을 준다(운영자는 어느 노트든, 그 밖에는 공개 노트만).
//  - hidden: 볼 수 없다. 비공개 노트를 운영자가 아닌 사람이 읽거나 삭제한 노트다. 기존 예시 노트(11·12)가 있어도 예시로 넘기지 않고 404로 답한다.
//  - null: 이 저장소가 맡을 노트가 아니다(처음 그대로인 공개 노트, 이 저장소에 없는 id). 기존 예시 응답으로 이어 간다.
export type NoteRead = { kind: 'found'; body: object } | { kind: 'hidden' } | null

export function readNoteForMock(id: number): NoteRead {
  if (deletedIds.has(id)) return { kind: 'hidden' }
  const note = notes().find((item) => item.id === id)
  if (!note) return null
  const operator = getMockSession() === 'operator'
  if (!operator && !note.isPublished) return { kind: 'hidden' }
  if (!operator && !note.touched) return null
  return {
    kind: 'found',
    body: {
      id: note.id,
      revision: note.revision,
      title: note.title,
      studied_on: note.studiedOn,
      subjects: subjectsOf(note),
      sources: [],
      body_markdown: note.body,
      images: {},
      glossary_terms: [],
      glossary_spans: [],
    },
  }
}

// 서버의 NoteFields가 받는 필드 전체. 이 밖의 필드는 422다.
const NOTE_FIELDS = ['title', 'body_markdown', 'studied_on', 'study_minutes', 'importance', 'understanding', 'needs_review', 'memo', 'is_published']

function strictObject(body: unknown, allowed: string[]): { input: Record<string, unknown>; unknown: string[] } {
  const input = body !== null && typeof body === 'object' && !Array.isArray(body) ? (body as Record<string, unknown>) : {}
  return { input, unknown: Object.keys(input).filter((name) => !allowed.includes(name)) }
}

const isInt = (value: unknown): value is number => typeof value === 'number' && Number.isInteger(value)

// NoteFields 검증. 보낸 필드만 본다. titleRequired가 true면 title이 없을 때 required다(작성).
function checkFields(input: Record<string, unknown>, titleRequired: boolean): Array<[string, string]> {
  const problems: Array<[string, string]> = []
  const title = input.title
  if (title === undefined) {
    if (titleRequired) problems.push(['title', 'required'])
  } else if (typeof title !== 'string') problems.push(['title', 'invalid_format'])
  else if (title.trim() === '') problems.push(['title', 'required'])
  else if (title.length > TITLE_MAX) problems.push(['title', 'too_long'])
  const body = input.body_markdown
  if (body !== undefined) {
    if (typeof body !== 'string') problems.push(['body_markdown', 'invalid_format'])
    else if (body.length > BODY_MAX) problems.push(['body_markdown', 'too_long'])
  }
  const studiedOn = input.studied_on
  if (studiedOn !== undefined && studiedOn !== null && (typeof studiedOn !== 'string' || !DATE.test(studiedOn))) problems.push(['studied_on', 'invalid_format'])
  const minutes = input.study_minutes
  if (minutes !== undefined && minutes !== null && (!isInt(minutes) || minutes < 0)) problems.push(['study_minutes', isInt(minutes) ? 'out_of_range' : 'invalid_format'])
  const importance = input.importance
  if (importance !== undefined && importance !== null && !['상', '중', '하'].includes(importance as string)) problems.push(['importance', 'invalid_value'])
  const understanding = input.understanding
  if (understanding !== undefined && understanding !== null && (!isInt(understanding) || understanding < 1 || understanding > 5)) problems.push(['understanding', isInt(understanding) ? 'out_of_range' : 'invalid_format'])
  for (const name of ['needs_review', 'is_published']) {
    if (input[name] !== undefined && typeof input[name] !== 'boolean') problems.push([name, 'invalid_format'])
  }
  const memo = input.memo
  if (memo !== undefined && memo !== null && typeof memo !== 'string') problems.push(['memo', 'invalid_format'])
  return problems
}

export const adminNoteRoutes: Route[] = [
  // E15 편집용 노트 한 개. 운영자만 읽고, 없거나 삭제한 노트는 404다. 비공개 열(is_published 등)도 함께 온다.
  {
    method: 'GET',
    pattern: /^\/api\/admin\/notes\/([^/]+)$/,
    handle: (_request, [noteId]) => {
      const denied = operatorOnly()
      if (denied) return denied
      const note = BIGINT.test(noteId) ? notes().find((item) => item.id === Number(noteId)) : undefined
      if (!note) return gone()
      return {
        status: 200,
        body: {
          id: note.id,
          revision: note.revision,
          title: note.title,
          body_markdown: note.body,
          studied_on: note.studiedOn,
          study_minutes: null,
          importance: null,
          understanding: null,
          needs_review: false,
          memo: null,
          is_published: note.isPublished,
          parent_note_id: null,
          created_at: '2026-10-01T00:00:00Z',
          updated_at: '2026-10-01T00:00:00Z',
          subjects: subjectsOf(note),
          sources: [],
          images: {},
        },
      }
    },
  },
  // E16 노트 작성. title이 필수이고 새 노트는 is_published를 주지 않으면 비공개다. 응답은 { id, revision }이고 201이다.
  {
    method: 'POST',
    pattern: /^\/api\/admin\/notes$/,
    handle: ({ body }) => {
      const denied = operatorOnly()
      if (denied) return denied
      const { input, unknown } = strictObject(body, NOTE_FIELDS)
      const problems: Array<[string, string]> = [...unknown.map((name): [string, string] => [name, 'invalid_format']), ...checkFields(input, true)]
      if (problems.length > 0) return validationFailed(problems)
      const created: MockNote = {
        id: nextId++,
        title: input.title as string,
        studiedOn: typeof input.studied_on === 'string' ? input.studied_on : '',
        body: typeof input.body_markdown === 'string' ? input.body_markdown : '',
        subjectIds: [],
        isPublished: input.is_published === true,
        revision: 1,
        touched: true,
      }
      notes().push(created)
      return { status: 201, body: { id: created.id, revision: created.revision } }
    },
  },
  // E17 노트 수정·공개 전환. 보낸 필드만 바꾸고, expected_revision이 있는데 서버의 revision과 다르면 409 conflict(detail stale_revision)다.
  // expected_revision을 보내지 않으면 충돌 검사를 하지 않는다(서버와 같다). UPDATE마다 revision이 1 오른다(공개 전환 포함). 응답은 { id, revision, is_published }다.
  {
    method: 'PATCH',
    pattern: /^\/api\/admin\/notes\/([^/]+)$/,
    handle: ({ body }, [noteId]) => {
      const denied = operatorOnly()
      if (denied) return denied
      if (!BIGINT.test(noteId)) return gone()
      const { input, unknown } = strictObject(body, [...NOTE_FIELDS, 'expected_revision'])
      const problems: Array<[string, string]> = [...unknown.map((name): [string, string] => [name, 'invalid_format']), ...checkFields(input, false)]
      const expected = input.expected_revision
      if (expected !== undefined && expected !== null && (!isInt(expected) || expected < 1)) problems.push(['expected_revision', isInt(expected) ? 'out_of_range' : 'invalid_format'])
      if (problems.length > 0) return validationFailed(problems)
      const note = notes().find((item) => item.id === Number(noteId))
      if (!note) return gone()
      if (typeof expected === 'number' && expected !== note.revision) return mockError(409, 'conflict', 'The note has changed since it was loaded', 'stale_revision')
      if (typeof input.title === 'string') note.title = input.title
      if (typeof input.studied_on === 'string') note.studiedOn = input.studied_on
      if (typeof input.body_markdown === 'string') note.body = input.body_markdown
      if (typeof input.is_published === 'boolean') note.isPublished = input.is_published
      note.revision += 1
      note.touched = true
      return { status: 200, body: { id: note.id, revision: note.revision, is_published: note.isPublished } }
    },
  },
  // E18 노트 삭제. 204, 없으면 404다. 삭제한 노트는 방문자 읽기(E05)에서도 404다.
  {
    method: 'DELETE',
    pattern: /^\/api\/admin\/notes\/([^/]+)$/,
    handle: (_request, [noteId]) => {
      const denied = operatorOnly()
      if (denied) return denied
      if (!BIGINT.test(noteId) || !notes().some((note) => note.id === Number(noteId))) return gone()
      store = notes().filter((note) => note.id !== Number(noteId))
      deletedIds.add(Number(noteId))
      return { status: 204 }
    },
  },
]
