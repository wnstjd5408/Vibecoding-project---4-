import { apiFetch } from '../api/client.ts'
import type { AuthState } from '../auth/authContext.ts'
import { loadAuthState } from '../auth/loadAuthState.ts'
import { startNewSession } from '../auth/sessionGeneration.ts'

// E02 로그아웃. 세션이 없어도 서버는 204로 답한다. 실패하면 ApiError를 던진다.
export function logout(): Promise<void> {
  // 로그아웃에 성공하면 새 세션 번호를 올려, 같은 표시 이름의 다른 계정이 이전 계정의 요청·대기를 이어받지 않게 한다.
  // 실패하면 로그인 상태가 그대로이므로 올리지 않는다. 로그아웃 요청 중에 시작된 요청은 이전 번호를 가져 성공 뒤의 번호와 구분된다.
  return apiFetch<void>('/api/auth/logout', { method: 'POST' }).then(() => startNewSession())
}

// 로그아웃(E02)이 성공한 뒤 E03으로 읽은 결과.
//  - logged_out: 방문자로 확인됐다. 이동한다
//  - still_logged_in: 아직 로그인 상태로 읽혔다. 로그아웃이 안 된 것이다
//  - unknown: E03을 받지 못했다(네트워크 오류·503 등). 이미 로그아웃됐을 수 있어 로그인 상태가 유지된다고 단정하지 않는다
export type LogoutResult = 'logged_out' | 'still_logged_in' | 'unknown'

// state는 방금 읽은 상태다. logged_out이면 화면이 이 상태를 전역에 그대로 반영해, 같은 E03을 한 번 더 부르지 않는다.
export type LogoutCheck = { result: LogoutResult; state: AuthState }

// 전역 로그인 상태(useAuth)는 건드리지 않고 E03만 읽어 확인한다. 확인하지 못했을 때 헤더가 방문자로 바뀌어 상태를 잘못 알리지 않게 하려는 것이다.
// loadAuthState는 E03이 실패해도 예외 없이 status 'error'를 돌려주므로, 완료를 성공으로 보지 않고 상태를 확인한다.
export async function checkLoggedOut(load: () => Promise<AuthState> = loadAuthState): Promise<LogoutCheck> {
  const state = await load()
  if (state.status !== 'ready') return { result: 'unknown', state }
  return { result: state.role === 'visitor' ? 'logged_out' : 'still_logged_in', state }
}
