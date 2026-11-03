// 운영자 노트(E04·E05의 운영자 보기와 E16~E18)의 가짜 응답. 목록·상세 모양은 backend/app/notes.py를 따른다.
// E16~E18은 백엔드에 아직 없고 필드 명세도 저장소에 없다. 아래 요청 본문({ title, studied_on, body_markdown }, 수정은 revision과
// 선택 is_published 포함)과 응답은 **추정**이다. 서버 명세가 정해지면 이 파일과 operator/notes/notesApi.ts를 함께 맞춘다.
// 값은 모두 합성이고 이 저장소는 새로 고치면 처음 상태로 돌아간다.
import type { ApiErrorBody, FieldError, NoteListResponse } from '../types.ts'
import { NOTES, SUBJECTS, mockError, operatorOnly } from './handlers.ts'
import type { MockResponse, Route } from './handlers.ts'
import { getMockSession } from './session.ts'

const FIELD_MESSAGES: Record<string, string> = {
  required: 'Value is required',
  too_long: 'Value is too long',
  invalid_format: 'Value format is invalid',
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

// E05. 운영자는 어느 노트든, 그 밖에는 공개 노트를 준다. 기존 가짜 노트 11·12는 시험용 본문이 따로 있어 손대지 않았으면 null을 돌려 그쪽으로 이어 간다.
export function readNoteForMock(id: number): object | null {
  const note = notes().find((item) => item.id === id)
  const operator = getMockSession() === 'operator'
  if (!note || (!operator && !note.isPublished)) return null
  if (!operator && !note.touched) return null
  return {
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
  }
}

function strictObject(body: unknown, allowed: string[]): { input: Record<string, unknown>; unknown: string[] } {
  const input = body !== null && typeof body === 'object' && !Array.isArray(body) ? (body as Record<string, unknown>) : {}
  return { input, unknown: Object.keys(input).filter((name) => !allowed.includes(name)) }
}

function checkFields(input: Record<string, unknown>, required: boolean): Array<[string, string]> {
  const problems: Array<[string, string]> = []
  const text = (name: string, check: (value: string) => string | null) => {
    const value = input[name]
    if (value === undefined) {
      if (required) problems.push([name, 'required'])
    } else if (typeof value !== 'string') problems.push([name, 'invalid_format'])
    else {
      const reason = check(value)
      if (reason) problems.push([name, reason])
    }
  }
  text('title', (value) => (value.trim() === '' ? 'required' : null))
  text('studied_on', (value) => (DATE.test(value) ? null : 'invalid_format'))
  text('body_markdown', () => null)
  return problems
}

export const adminNoteRoutes: Route[] = [
  // E16 노트 작성(필드 추정). 새 노트는 비공개로 시작한다. 201.
  {
    method: 'POST',
    pattern: /^\/api\/admin\/notes$/,
    handle: ({ body }) => {
      const denied = operatorOnly()
      if (denied) return denied
      const { input, unknown } = strictObject(body, ['title', 'studied_on', 'body_markdown'])
      const problems: Array<[string, string]> = [...unknown.map((name): [string, string] => [name, 'invalid_format']), ...checkFields(input, true)]
      if (problems.length > 0) return validationFailed(problems)
      const created: MockNote = {
        id: nextId++,
        title: (input.title as string).trim(),
        studiedOn: input.studied_on as string,
        body: input.body_markdown as string,
        subjectIds: [],
        isPublished: false,
        revision: 1,
        touched: true,
      }
      notes().push(created)
      return { status: 201, body: { id: created.id, revision: created.revision, is_published: created.isPublished } }
    },
  },
  // E17 노트 수정(필드 추정). revision이 서버와 다르면 409 conflict(detail stale_revision)다. UPDATE마다 revision이 1 오른다(공개 전환 포함).
  {
    method: 'PATCH',
    pattern: /^\/api\/admin\/notes\/([^/]+)$/,
    handle: ({ body }, [noteId]) => {
      const denied = operatorOnly()
      if (denied) return denied
      if (!BIGINT.test(noteId)) return gone()
      const { input, unknown } = strictObject(body, ['revision', 'title', 'studied_on', 'body_markdown', 'is_published'])
      const problems: Array<[string, string]> = [...unknown.map((name): [string, string] => [name, 'invalid_format']), ...checkFields(input, false)]
      if (!Number.isInteger(input.revision)) problems.push(['revision', input.revision === undefined ? 'required' : 'invalid_format'])
      if (input.is_published !== undefined && typeof input.is_published !== 'boolean') problems.push(['is_published', 'invalid_format'])
      if (problems.length > 0) return validationFailed(problems)
      const note = notes().find((item) => item.id === Number(noteId))
      if (!note) return gone()
      if (input.revision !== note.revision) return mockError(409, 'conflict', 'The note has changed since it was loaded', 'stale_revision')
      if (typeof input.title === 'string') note.title = input.title.trim()
      if (typeof input.studied_on === 'string') note.studiedOn = input.studied_on
      if (typeof input.body_markdown === 'string') note.body = input.body_markdown
      if (typeof input.is_published === 'boolean') note.isPublished = input.is_published
      note.revision += 1
      note.touched = true
      return { status: 200, body: { id: note.id, revision: note.revision, is_published: note.isPublished } }
    },
  },
  // E18 노트 삭제. 204, 없으면 404다.
  {
    method: 'DELETE',
    pattern: /^\/api\/admin\/notes\/([^/]+)$/,
    handle: (_request, [noteId]) => {
      const denied = operatorOnly()
      if (denied) return denied
      if (!BIGINT.test(noteId) || !notes().some((note) => note.id === Number(noteId))) return gone()
      store = notes().filter((note) => note.id !== Number(noteId))
      return { status: 204 }
    },
  },
]
