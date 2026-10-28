// 공통 기반을 눈으로 확인하는 샘플 화면(MEG-105). 제품 화면이 아니다.
//  1) 실제 백엔드: 개발 서버 프록시를 거쳐 /api/health를 부른다
//  2) 가짜 응답: 같은 apiFetch로 가짜 응답을 받고, 오류는 code로 구분한다
//  3) 로그인 상태: 방문자·사용자·운영자 상태를 한곳(useAuth)에서 읽는다
import { useEffect, useState } from 'react'
import { apiFetch, isApiError } from '../api/client.ts'
import { setMockSession } from '../api/mocks/session.ts'
import type { MockSession } from '../api/mocks/session.ts'
import { getApiSource, setApiSource } from '../api/source.ts'
import type { FavoriteResponse, NoteListResponse } from '../api/types.ts'
import { useAuth } from '../auth/useAuth.ts'
import DevNav from './DevNav.tsx'

type Result = { kind: 'idle' } | { kind: 'loading' } | { kind: 'ok'; text: string } | { kind: 'error'; text: string }

const ROLE_LABEL = { visitor: '방문자', user: '사용자', operator: '운영자' } as const

function show(result: Result): string {
  if (result.kind === 'idle') return '아직 부르지 않았습니다'
  if (result.kind === 'loading') return '확인 중…'
  return result.text
}

// 오류는 message 글자가 아니라 code·detail로 구분해 보여 준다.
function describeError(error: unknown): string {
  if (isApiError(error)) {
    return `오류 code=${error.code}${error.detail ? ` detail=${error.detail}` : ''} (HTTP ${error.status})`
  }
  return '알 수 없는 오류'
}

export default function FoundationDemo() {
  const auth = useAuth()
  const [source, setSource] = useState(getApiSource())
  const [health, setHealth] = useState<Result>({ kind: 'loading' })
  const [notes, setNotes] = useState<Result>({ kind: 'idle' })
  const [favorite, setFavorite] = useState<Result>({ kind: 'idle' })

  // 1) 실제 백엔드. source를 real로 못 박아 가짜 응답과 섞이지 않게 한다.
  useEffect(() => {
    apiFetch<{ status: string }>('/api/health', { source: 'real' })
      .then((body) => setHealth({ kind: 'ok', text: `백엔드 응답: ${body.status}` }))
      .catch((error: unknown) => setHealth({ kind: 'error', text: describeError(error) }))
  }, [])

  const loadNotes = () => {
    setNotes({ kind: 'loading' })
    apiFetch<NoteListResponse>('/api/notes', { source: 'mock' })
      .then((body) => setNotes({ kind: 'ok', text: body.notes.map((note) => note.title).join(' / ') }))
      .catch((error: unknown) => setNotes({ kind: 'error', text: describeError(error) }))
  }

  const toggleFavorite = () => {
    setFavorite({ kind: 'loading' })
    apiFetch<FavoriteResponse>('/api/favorites/7', { method: 'PUT', body: { favorited: true }, source: 'mock' })
      .then((body) => setFavorite({ kind: 'ok', text: `즐겨찾기 저장됨: is_favorite=${body.is_favorite}` }))
      .catch((error: unknown) => setFavorite({ kind: 'error', text: describeError(error) }))
  }

  // 3) 가짜 응답으로 로그인 상태를 바꾼 뒤 E03을 다시 읽는다.
  const switchTo = async (session: MockSession) => {
    setMockSession(session)
    setApiSource('mock')
    setSource('mock')
    await auth.refresh()
  }

  const backToReal = async () => {
    setApiSource('real')
    setSource('real')
    await auth.refresh()
  }

  return (
    <main style={{ padding: '2rem', display: 'grid', gap: '1.5rem' }}>
      <h1>공통 기반 샘플</h1>

      <section aria-labelledby="demo-real">
        <h2 id="demo-real">1. 실제 백엔드로 가는 /api 요청</h2>
        <p>
          <code>/api/health</code> → {show(health)}
        </p>
      </section>

      <section aria-labelledby="demo-mock">
        <h2 id="demo-mock">2. 가짜 응답과 오류 구분</h2>
        <p>
          <button type="button" onClick={loadNotes}>
            노트 목록(E04) 불러오기
          </button>{' '}
          {show(notes)}
        </p>
        <p>
          <button type="button" onClick={toggleFavorite}>
            즐겨찾기(E08) 누르기
          </button>{' '}
          {show(favorite)}
        </p>
        <p>방문자 상태에서 즐겨찾기를 누르면 login_required, 로그인한 상태에서는 저장됩니다.</p>
      </section>

      <section aria-labelledby="demo-auth">
        <h2 id="demo-auth">3. 로그인 상태 (useAuth)</h2>
        <p>
          현재 상태: <strong>{ROLE_LABEL[auth.role]}</strong>
          {auth.displayName ? ` (${auth.displayName})` : ''} · 응답 출처: {source === 'mock' ? '가짜 응답' : '실제 백엔드'}
          {auth.status === 'error' ? ' · 상태(E03)를 받지 못했습니다' : ''}
        </p>
        <p>
          {(['visitor', 'user', 'operator'] as const).map((session) => (
            <button key={session} type="button" onClick={() => void switchTo(session)} style={{ marginRight: '0.5rem' }}>
              가짜 {ROLE_LABEL[session]}로 바꾸기
            </button>
          ))}
          <button type="button" onClick={() => void backToReal()}>
            실제 백엔드로 되돌리기
          </button>
        </p>
      </section>

      <DevNav />
    </main>
  )
}
