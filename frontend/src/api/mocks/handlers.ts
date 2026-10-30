// 가짜 응답을 한곳에 모았다. API spec v0.2 3절 예시와 2.2절 응답 모양을 따르고, 값은 모두 합성이다.
// 실제 API가 생기면 해당 엔드포인트의 항목만 지우거나 apiSource를 real로 두면 된다.
import type { ApiErrorBody, NoteListResponse } from '../types.ts'
import { getMockSession, setMockSession } from './session.ts'

export type MockRequest = { method: string; path: string; query: URLSearchParams; body: unknown }
export type MockResponse = { status: number; body?: unknown }

type Route = {
  method: string
  pattern: RegExp
  handle: (request: MockRequest, params: string[]) => MockResponse
}

// 오류 본문은 1.4 형식이다. message는 1.4.6의 영어 고정 문구를 그대로 쓴다.
export function mockError(status: number, code: string, message: string, detail?: string): MockResponse {
  const body: ApiErrorBody = { error: { code, message, request_id: 'r-mock-0001', ...(detail ? { detail } : {}) } }
  return { status, body }
}

const loginRequired = () => mockError(401, 'login_required', 'Login is required')
const notFound = () => mockError(404, 'not_found', 'Resource not found')

// 운영자 API의 가짜 응답이 맨 앞에서 부른다. 서버처럼 방문자는 401 login_required, 일반 사용자는 403 forbidden을 돌려주고,
// 운영자면 null이라 그대로 이어서 처리한다(backend/app/auth.py의 require_operator와 같은 규칙이다).
//   handle: () => operatorOnly() ?? { status: 200, body: ... }
export function operatorOnly(): MockResponse | null {
  const session = getMockSession()
  if (session === 'visitor') return loginRequired()
  if (session === 'member') return mockError(403, 'forbidden', 'Operator permission is required')
  return null
}

// 합성 계정. 실제 계정·비밀번호가 아니다. 역할 값은 서버 계약(member·operator)과 같다.
const ACCOUNTS = {
  'member@example.test': { password: 'example-password', role: 'member', display_name: '합성 사용자' },
  'operator@example.test': { password: 'example-password', role: 'operator', display_name: '합성 운영자' },
} as const

// E06 예시 2의 용어 7을 즐겨찾기했는지. 가짜 응답이 흉내 낸다.
let favoriteTerm7 = false

const SUBJECTS = [
  { id: 1, name: '네트워크', note_count: 2 },
  { id: 2, name: '운영체제', note_count: 1 },
  { id: 3, name: '데이터베이스', note_count: 1 },
]

const NOTES = [
  { id: 11, title: '예시 노트 · 요청이 서버까지 가는 길', studied_on: '2026-10-14', subjects: [SUBJECTS[0]], parent_note_id: null },
  { id: 12, title: '예시 노트 · 프로세스가 번갈아 실행되는 이유', studied_on: '2026-10-09', subjects: [SUBJECTS[1]], parent_note_id: null },
  { id: 13, title: '예시 노트 · 인덱스가 조회를 빠르게 하는 방식', studied_on: '2026-10-02', subjects: [SUBJECTS[2]], parent_note_id: null },
  { id: 14, title: '예시 노트 · 캐시가 오래된 값을 돌려주는 경우', studied_on: '2026-09-27', subjects: [SUBJECTS[0]], parent_note_id: null },
].map((note) => ({ ...note, subjects: note.subjects.map(({ id, name }) => ({ id, name })) }))

const EXAMPLE_IMAGE =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="120"><rect width="320" height="120" fill="#dde2e9"/><text x="160" y="66" text-anchor="middle" font-size="20" fill="#16202f">EXAMPLE IMAGE</text></svg>')

const GLOSSARY_IMAGE =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="160"><rect width="320" height="160" fill="#dde2e9"/><text x="160" y="86" text-anchor="middle" font-size="20" fill="#16202f">합성 구조도</text></svg>')

// 노트 본문 속 label의 모든 위치를 glossary_spans 형식(코드포인트, 끝 제외)으로 만든다. 가짜 응답이 서버 계산을 흉내 낸다.
function spansOf(body: string, label: string, termId: number) {
  const spans: { term_id: number; start: number; end: number }[] = []
  for (let at = body.indexOf(label); at >= 0; at = body.indexOf(label, at + label.length)) {
    const start = [...body.slice(0, at)].length
    spans.push({ term_id: termId, start, end: start + [...label].length })
  }
  return spans
}

// 위치 계산 시험용 합성 노트: 제목·굵게·이스케이프·엔티티·목록·인라인 코드·코드 블록·이모지(UTF-16 두 칸)가 섞여 있다.
const RICH_BODY = [
  '## 프로세스 **스케줄링**',
  '',
  '😀 ExampleTerm 은 \\*별표\\* 와 &amp; 가 있는 글에서도 찾아요.',
  '',
  '- 첫째 항목 ExampleTerm',
  '- 둘째 `code ExampleTerm` 항목',
  '',
  '```js',
  'const a = ExampleTerm',
  '```',
  '',
  '끝 줄입니다.',
].join('\n')

const RICH_NOTE = {
  id: 12,
  revision: 1,
  title: '예시 노트 · 프로세스가 번갈아 실행되는 이유',
  studied_on: '2026-10-09',
  subjects: [{ id: 2, name: '운영체제' }],
  sources: [],
  body_markdown: RICH_BODY,
  images: {},
  glossary_terms: [{ term_id: 7, key: 'exampleterm', label: 'ExampleTerm' }],
  glossary_spans: spansOf(RICH_BODY, 'ExampleTerm', 7),
}

const routes: Route[] = [
  // 백엔드 상태 확인. 개발 서버 프록시가 실제 백엔드의 /health로 이어 주는 경로와 같은 모양이다.
  { method: 'GET', pattern: /^\/api\/health$/, handle: () => ({ status: 200, body: { status: 'ok' } }) },
  // E01 로그인. 맞지 않으면 사유를 구분하지 않고 401 invalid_credentials다.
  {
    method: 'POST',
    pattern: /^\/api\/auth\/login$/,
    handle: ({ body }) => {
      const { email, password } = (body ?? {}) as { email?: string; password?: string }
      const account = typeof email === 'string' && email in ACCOUNTS ? ACCOUNTS[email as keyof typeof ACCOUNTS] : null
      if (!account || account.password !== password) {
        return mockError(401, 'invalid_credentials', 'Invalid email or password')
      }
      setMockSession(account.role)
      return { status: 200, body: { user: { role: account.role, display_name: account.display_name } } }
    },
  },
  // E02 로그아웃. 세션이 없어도 204다.
  {
    method: 'POST',
    pattern: /^\/api\/auth\/logout$/,
    handle: () => {
      setMockSession('visitor')
      return { status: 204 }
    },
  },
  // E03 내 상태. 비로그인도 200이다.
  {
    method: 'GET',
    pattern: /^\/api\/me$/,
    handle: () => {
      const session = getMockSession()
      if (session === 'visitor') return { status: 200, body: { authenticated: false } }
      const account = session === 'operator' ? ACCOUNTS['operator@example.test'] : ACCOUNTS['member@example.test']
      return { status: 200, body: { authenticated: true, role: account.role, display_name: account.display_name } }
    },
  },
  // E04 과목·노트 목록. 운영자는 노트마다 공개 여부 등이 더 온다.
  {
    method: 'GET',
    pattern: /^\/api\/notes$/,
    handle: ({ query }) => {
      const subjectId = query.get('subject_id')
      const notes = subjectId ? NOTES.filter((note) => note.subjects.some((s) => String(s.id) === subjectId)) : NOTES
      const operator = getMockSession() === 'operator'
      const body: NoteListResponse = {
        subjects: SUBJECTS,
        notes: operator ? notes.map((note) => ({ ...note, is_published: true, revision: 1, needs_review: false })) : notes,
      }
      return { status: 200, body }
    },
  },
  // E05 노트 읽기. 예시 1의 노트 11과, 마크다운 문법·이모지가 섞인 시험용 노트 12만 있다.
  {
    method: 'GET',
    pattern: /^\/api\/notes\/(\d+)$/,
    handle: (_request, [noteId]) => {
      if (noteId === '12') return { status: 200, body: RICH_NOTE }
      if (noteId !== '11') return notFound()
      return {
        status: 200,
        body: {
          id: 11,
          revision: 3,
          title: 'Example Note',
          studied_on: '2026-10-14',
          subjects: [{ id: 1, name: '네트워크' }],
          sources: [{ url: 'https://example.test/doc', label: '예시 문서' }],
          body_markdown: '이 노트는 ExampleTerm 을 설명합니다. UnknownWord 는 사전에 없습니다. ![그림](note-image:blk-1)',
          images: {
            // 예시 1은 https://storage.example.test/... URL이다. 가짜 응답에서도 그림이 보이도록 같은 모양의 data URL을 쓴다.
            'blk-1': { url: EXAMPLE_IMAGE, alt: '그림', expires_at: '2026-10-23T05:35:00Z' },
          },
          glossary_terms: [{ term_id: 7, key: 'exampleterm', label: 'ExampleTerm' }],
          glossary_spans: [{ term_id: 7, start: 6, end: 17 }],
        },
      }
    },
  },
  // E06 용어 바텀시트. 예시 2의 용어 7만 있고, 방문자에게는 is_favorite 키가 없다.
  {
    method: 'GET',
    pattern: /^\/api\/glossary\/(\d+)$/,
    handle: (_request, [termId]) => {
      if (termId !== '7') return notFound()
      const body = {
        term: { id: 7, key: 'exampleterm', label: 'ExampleTerm' },
        body_markdown: '합성 설명 문장입니다.',
        // 예시 2는 https://storage.example.test/... URL이다. 가짜 응답에서도 그림이 보이도록 같은 모양의 data URL을 쓴다.
        images: [{ id: 3, url: GLOSSARY_IMAGE, alt: '합성 구조도' }],
      }
      return { status: 200, body: getMockSession() === 'visitor' ? body : { ...body, is_favorite: favoriteTerm7 } }
    },
  },
  // E07 용어 열람 기록. 방문자는 오류 없이 recorded가 false다.
  {
    method: 'POST',
    pattern: /^\/api\/term-views$/,
    handle: () => ({ status: 200, body: { recorded: getMockSession() !== 'visitor' } }),
  },
  // E09 AI 설명. 방문자는 항상 401 login_required다. 로그인한 사용자 응답은 이 화면들이 쓰지 않아 만들지 않는다(등록 안 된 경로와 같은 404).
  {
    method: 'POST',
    pattern: /^\/api\/ai\/explanations$/,
    handle: () => (getMockSession() === 'visitor' ? loginRequired() : notFound()),
  },
  // E08 즐겨찾기. 방문자는 항상 401 login_required다.
  {
    method: 'PUT',
    pattern: /^\/api\/favorites\/(\d+)$/,
    handle: ({ body }, [termId]) => {
      if (getMockSession() === 'visitor') return loginRequired()
      if (termId !== '7') return notFound()
      favoriteTerm7 = Boolean((body as { favorited?: boolean } | undefined)?.favorited)
      return { status: 200, body: { term_id: 7, is_favorite: favoriteTerm7 } }
    },
  },
]

// 등록되지 않은 엔드포인트는 404 not_found로 답한다. 실제 백엔드에 없는 경로를 부른 것과 같다.
export function handleMock(request: MockRequest): MockResponse {
  for (const route of routes) {
    if (route.method !== request.method) continue
    const match = route.pattern.exec(request.path)
    if (match) return route.handle(request, match.slice(1))
  }
  return notFound()
}
