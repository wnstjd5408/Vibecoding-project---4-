// API spec v0.2의 요청·응답 모양 중 화면 공통 기반이 쓰는 것만 둔다. 화면별 응답 타입은 그 화면 티켓에서 더한다.

// 서버 계약의 역할 값이다. DB(profiles.role)와 E01·E03·E24 모두 'operator'와 'member'만 쓴다. 화면에서는 member를 "사용자"로 부른다.
export type Role = 'member' | 'operator'

// 1.4 오류 응답. 클라이언트는 code·detail·fields[].reason으로 분기한다. message는 영어 고정 문구라 분기에 쓰지 않는다.
export type FieldError = { name: string; reason: string; message: string }

export type ApiErrorBody = {
  error: {
    code: string
    message: string
    request_id: string
    detail?: string
    fields?: FieldError[]
    retry_after_seconds?: number
  }
}

// E01 POST /api/auth/login
export type LoginRequest = { email: string; password: string }
export type LoginResponse = { user: { role: Role; display_name: string } }

// E03 GET /api/me. 비로그인·비활성도 200이고 authenticated가 false다.
export type MeResponse = { authenticated: boolean; role?: Role; display_name?: string }

// E04 GET /api/notes. 운영자는 노트마다 is_published, revision, needs_review가 더 온다.
export type NoteListResponse = {
  subjects: { id: number; name: string; note_count: number }[]
  notes: {
    id: number
    title: string
    studied_on: string | null
    subjects: { id: number; name: string }[]
    parent_note_id: number | null
    is_published?: boolean
    revision?: number
    needs_review?: boolean
  }[]
}

// E05 GET /api/notes/{id}. glossary_spans의 start·end는 body_markdown 원문의 유니코드 코드포인트 위치이고 끝은 포함하지 않는다(2026-10-30 결정).
// images의 키는 본문 `note-image:<키>` 토큰이다. url은 서명 URL이라 expires_at 뒤에는 열리지 않을 수 있어 E05를 다시 불러 새로 받는다.
export type NoteReadResponse = {
  id: number
  revision: number
  title: string
  studied_on: string | null
  subjects: { id: number; name: string }[]
  sources: { url: string; label: string }[]
  body_markdown: string
  images: Record<string, { url: string; alt: string; expires_at: string }>
  glossary_terms: { term_id: number; key: string; label: string }[]
  glossary_spans: { term_id: number; start: number; end: number }[]
}

// E06 GET /api/glossary/{term_id}. 사전에 없는 용어(AI로만 설명된 용어 포함)는 404다. is_favorite는 로그인했을 때만 온다.
// images[].url이 공개 주소인지 서명 URL인지는 아직 정해지지 않았다(기술 검토 Q7). 안 열리면 E06을 다시 불러 새 값을 받는다.
export type GlossaryResponse = {
  term: { id: number; key: string; label: string }
  body_markdown: string
  images: { id: number; url: string; alt: string }[]
  is_favorite?: boolean
}

// E07 POST /api/term-views. 방문자는 오류 없이 recorded가 false다.
export type TermViewResponse = { recorded: boolean }

// E08 PUT /api/favorites/{term_id}
export type FavoriteResponse = { term_id: number; is_favorite: boolean }
