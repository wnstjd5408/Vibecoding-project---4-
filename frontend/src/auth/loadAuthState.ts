import { apiFetch } from '../api/client.ts'
import type { MeResponse, Role } from '../api/types.ts'
import type { AuthState } from './authContext.ts'

export const LOADING: AuthState = { status: 'loading', role: 'visitor', displayName: null }
const VISITOR: AuthState = { status: 'ready', role: 'visitor', displayName: null }
const FAILED: AuthState = { status: 'error', role: 'visitor', displayName: null }

// 서버가 주는 역할 값만 받는다. 계약에 없는 값은 상태에 넣지 않는다.
function isRole(value: unknown): value is Role {
  return value === 'member' || value === 'operator'
}

// E03(/api/me)으로 로그인 상태를 읽는다. 비로그인·비활성은 200 authenticated: false라서 방문자다.
export async function loadAuthState(): Promise<AuthState> {
  try {
    const me = await apiFetch<MeResponse>('/api/me')
    if (!me.authenticated) return VISITOR
    // 로그인했다고 했는데 역할이 계약에 없으면 잘못된 응답이다. 임의의 역할로 두지 않고 상태를 받지 못한 것으로 둔다.
    if (!isRole(me.role)) return FAILED
    return { status: 'ready', role: me.role, displayName: me.display_name ?? null }
  } catch {
    return FAILED
  }
}
