import { apiFetch, isApiError } from '../api/client.ts'
import type { LoginResponse, Role } from '../api/types.ts'
import { userPaths } from '../routes/paths.ts'

// E01 로그인. 성공하면 서버가 세션 쿠키를 심고 역할과 이름을 준다. 실패하면 ApiError를 던진다.
// 비밀번호는 요청 본문으로만 보내고 어디에도 남기지 않는다.
export function login(email: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>('/api/auth/login', { method: 'POST', body: { email, password } })
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
