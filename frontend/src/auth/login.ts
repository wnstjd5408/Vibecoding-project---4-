import { apiFetch, isApiError } from '../api/client.ts'
import type { LoginResponse, Role } from '../api/types.ts'
import { userPaths } from '../routes/paths.ts'
import type { AuthState } from './authContext.ts'
import { startNewSession } from './sessionGeneration.ts'

// E01 로그인. 성공하면 서버가 세션 쿠키를 심고 역할과 이름을 준다. 실패하면 ApiError를 던진다.
// 비밀번호는 요청 본문으로만 보내고 어디에도 남기지 않는다.
export function login(email: string, password: string): Promise<LoginResponse> {
  // 새 세션 번호를 올려, 이전 세션의 진행 중 요청·대기가 이 로그인 뒤의 화면으로 넘어오지 않게 한다. 요청 전과 성공 뒤에 모두 올린다.
  startNewSession()
  return apiFetch<LoginResponse>('/api/auth/login', { method: 'POST', body: { email, password } }).then((response) => {
    startNewSession()
    return response
  })
}

// 로그인 뒤 이동할 곳. 로그인 안내 시트(F1-1c·F2-2b) 어디서 왔든 같고, 역할로만 정한다.
//  - member(사용자): 오늘의 퀴즈 첫 화면(F3-3a)
//  - operator(운영자): 과목·노트 목록(F1-1b). 같은 경로에서 운영자 상태로 보인다
export function landingPath(role: Role): string {
  return role === 'operator' ? userPaths.noteList : userPaths.quiz
}

// 화면이 고르는 실패 종류. 문구는 서버 message가 아니라 code로 고른다(API spec 1.4.6).
//  - credentials: 계정 없음·비밀번호 오류·비활성 계정이 모두 401 invalid_credentials로 온다(구분하지 않는다)
//  - rate_limited: 429. 짧은 시간에 너무 많이 시도했다
//  - unavailable: 그 밖(네트워크 실패, 5xx, 형식이 다른 응답 등)
export type LoginFailure = { kind: 'credentials' } | { kind: 'rate_limited'; retryAfterSeconds?: number } | { kind: 'unavailable' }

export function classifyLoginFailure(error: unknown): LoginFailure {
  if (isApiError(error, 'invalid_credentials')) return { kind: 'credentials' }
  if (isApiError(error, 'rate_limited')) return { kind: 'rate_limited', retryAfterSeconds: error.retryAfterSeconds }
  return { kind: 'unavailable' }
}

// 로그인(E01) 직후 로그인 상태를 확인한 결과. 이동은 확인된 상태일 때만 한다.
//  - ok: E03이 로그인 상태와 역할을 확인했다. 이 역할로 이동한다
//  - 그 밖: E03을 받지 못했거나(네트워크 오류·503), 쿠키가 적용되지 않아 비로그인으로 읽혔다. 이동하지 않고 안내한다
export type LoginConfirmation = { ok: true; role: Role } | { ok: false }

// refresh()는 E03이 실패해도 예외를 던지지 않고 status가 'error'인 상태를 돌려준다. 완료를 성공으로 보지 않고 상태를 확인한다.
export async function confirmLogin(refresh: () => Promise<AuthState>): Promise<LoginConfirmation> {
  const state = await refresh()
  if (state.status !== 'ready' || state.role === 'visitor') return { ok: false }
  return { ok: true, role: state.role }
}
