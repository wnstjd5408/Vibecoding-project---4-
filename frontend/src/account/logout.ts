import { apiFetch } from '../api/client.ts'
import type { AuthState } from '../auth/authContext.ts'

// E02 로그아웃. 세션이 없어도 서버는 204로 답한다. 실패하면 ApiError를 던진다.
export function logout(): Promise<void> {
  return apiFetch<void>('/api/auth/logout', { method: 'POST' })
}

// 로그아웃(E02) 직후 방문자 상태가 확인됐는지. 이동은 확인된 경우에만 한다.
// refresh()는 E03이 실패해도 예외를 던지지 않고 status가 'error'인 상태를 돌려주므로, 완료를 성공으로 보지 않고 상태를 확인한다.
// E03을 받지 못했거나 아직 로그인 상태로 읽히면 false다(로그아웃이 끝났다고 알리지 않는다).
export async function confirmLogout(refresh: () => Promise<AuthState>): Promise<boolean> {
  const state = await refresh()
  return state.status === 'ready' && state.role === 'visitor'
}
