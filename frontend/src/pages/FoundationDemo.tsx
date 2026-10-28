// 공통 기반을 눈으로 확인하는 샘플 화면(MEG-105). 제품 화면이 아니다.
// 응답 출처(가짜/실제)는 환경변수 VITE_API_MOCK 한 곳이 정한다. 이 화면은 어느 쪽이든 같은 apiFetch를 쓴다.
//  1) /api/health 요청이 어디까지 가는지
//  2) 오류 응답을 message 글자가 아니라 code로 구분해 보여 주는지
//  3) 로그인 상태(방문자·사용자·운영자)를 한곳(useAuth)에서 읽는지
import { useEffect, useState } from 'react'
import { apiFetch, CLIENT_ERROR_CODES, isApiError } from '../api/client.ts'
import { setMockSession } from '../api/mocks/session.ts'
import type { MockSession } from '../api/mocks/session.ts'
import { getApiSource } from '../api/source.ts'
import type { FavoriteResponse, NoteListResponse } from '../api/types.ts'
import { useAuth } from '../auth/useAuth.ts'
import DevNav from './DevNav.tsx'

type Result = { kind: 'idle' } | { kind: 'loading' } | { kind: 'ok'; text: string } | { kind: 'error'; text: string }

const ROLE_LABEL = { visitor: '방문자', user: '사용자', operator: '운영자' } as const

// 오류 종류별 안내. 키는 서버 code(와 클라이언트 code)이고 message 글자로는 고르지 않는다.
const ERROR_LABEL: Record<string, string> = {
  login_required: '로그인 안내가 필요한 오류',
  invalid_credentials: '로그인 정보가 맞지 않는 오류',
  not_found: '대상이 없는 오류',
  [CLIENT_ERROR_CODES.networkError]: '네트워크 오류',
}

function show(result: Result): string {
  if (result.kind === 'idle') return '아직 부르지 않았습니다'
  if (result.kind === 'loading') return '확인 중…'
  return result.text
}

function describeError(error: unknown): string {
  if (!isApiError(error)) return '알 수 없는 오류'
  const label = ERROR_LABEL[error.code] ?? '그 밖의 오류'
  return `${label} — code=${error.code}${error.detail ? ` detail=${error.detail}` : ''} (HTTP ${error.status})`
}

export default function FoundationDemo() {
  const auth = useAuth()
  const source = getApiSource()
  const [health, setHealth] = useState<Result>({ kind: 'loading' })
  const [notes, setNotes] = useState<Result>({ kind: 'idle' })
  const [favorite, setFavorite] = useState<Result>({ kind: 'idle' })
  const [login, setLogin] = useState<Result>({ kind: 'idle' })

  useEffect(() => {
    apiFetch<{ status: string }>('/api/health')
      .then((body) => setHealth({ kind: 'ok', text: `응답: ${body.status}` }))
      .catch((error: unknown) => setHealth({ kind: 'error', text: describeError(error) }))
  }, [])

  const loadNotes = () => {
    setNotes({ kind: 'loading' })
    apiFetch<NoteListResponse>('/api/notes')
      .then((body) => setNotes({ kind: 'ok', text: body.notes.map((note) => note.title).join(' / ') }))
      .catch((error: unknown) => setNotes({ kind: 'error', text: describeError(error) }))
  }

  const pressFavorite = () => {
    setFavorite({ kind: 'loading' })
    apiFetch<FavoriteResponse>('/api/favorites/7', { method: 'PUT', body: { favorited: true } })
      .then((body) => setFavorite({ kind: 'ok', text: `즐겨찾기 저장됨: is_favorite=${body.is_favorite}` }))
      .catch((error: unknown) => setFavorite({ kind: 'error', text: describeError(error) }))
  }

  const wrongLogin = () => {
    setLogin({ kind: 'loading' })
    apiFetch('/api/auth/login', { method: 'POST', body: { email: 'user@example.test', password: 'wrong' } })
      .then(() => setLogin({ kind: 'ok', text: '로그인됨' }))
      .catch((error: unknown) => setLogin({ kind: 'error', text: describeError(error) }))
  }

  // 가짜 응답 출처에서만 쓴다. 가짜 로그인 상태를 바꾼 뒤 E03을 다시 읽는다.
  const switchTo = async (session: MockSession) => {
    setMockSession(session)
    await auth.refresh()
  }

  return (
    <main style={{ padding: '2rem', display: 'grid', gap: '1.5rem' }}>
      <h1>공통 기반 샘플</h1>
      <p>
        응답 출처: <strong>{source === 'mock' ? '가짜 응답 (VITE_API_MOCK=true)' : '실제 백엔드 (개발 서버 프록시)'}</strong>
      </p>

      <section aria-labelledby="demo-health">
        <h2 id="demo-health">1. /api 요청</h2>
        <p>
          <code>/api/health</code> → {show(health)}
        </p>
      </section>

      <section aria-labelledby="demo-errors">
        <h2 id="demo-errors">2. 응답과 오류 구분</h2>
        <p>
          <button type="button" onClick={loadNotes}>
            노트 목록(E04) 불러오기
          </button>{' '}
          {show(notes)}
        </p>
        <p>
          <button type="button" onClick={pressFavorite}>
            즐겨찾기(E08) 누르기
          </button>{' '}
          {show(favorite)}
        </p>
        <p>
          <button type="button" onClick={wrongLogin}>
            잘못된 비밀번호로 로그인(E01)
          </button>{' '}
          {show(login)}
        </p>
        <p>
          가짜 응답에서는 노트 목록이 보이고, 방문자의 즐겨찾기는 login_required, 잘못된 비밀번호는 invalid_credentials로
          서로 다른 오류가 됩니다. 실제 백엔드에는 아직 이 엔드포인트가 없어 not_found가 보입니다.
        </p>
      </section>

      <section aria-labelledby="demo-auth">
        <h2 id="demo-auth">3. 로그인 상태 (useAuth)</h2>
        <p>
          현재 상태: <strong>{ROLE_LABEL[auth.role]}</strong>
          {auth.displayName ? ` (${auth.displayName})` : ''}
          {auth.status === 'error' ? ' · 상태(E03)를 받지 못했습니다' : ''}
        </p>
        <p>
          {(['visitor', 'user', 'operator'] as const).map((session) => (
            <button
              key={session}
              type="button"
              disabled={source !== 'mock'}
              onClick={() => void switchTo(session)}
              style={{ marginRight: '0.5rem' }}
            >
              가짜 {ROLE_LABEL[session]}로 바꾸기
            </button>
          ))}
        </p>
        {source !== 'mock' ? <p>상태 전환 버튼은 VITE_API_MOCK=true일 때만 쓸 수 있습니다.</p> : null}
      </section>

      <DevNav />
    </main>
  )
}
