// API spec v0.2의 요청·응답 모양 중 화면 공통 기반이 쓰는 것만 둔다. 화면별 응답 타입은 그 화면 티켓에서 더한다.

export type Role = 'user' | 'operator'

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
    studied_on: string
    subjects: { id: number; name: string }[]
    parent_note_id: number | null
    is_published?: boolean
    revision?: number
    needs_review?: boolean
  }[]
}

// E08 PUT /api/favorites/{term_id}
export type FavoriteResponse = { term_id: number; is_favorite: boolean }
