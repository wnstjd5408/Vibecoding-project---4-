import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { apiFetch } from '../api/client.ts'
import type { MeResponse } from '../api/types.ts'
import { AuthContext } from './authContext.ts'
import type { AuthContextValue, AuthState } from './authContext.ts'

const LOADING: AuthState = { status: 'loading', role: 'visitor', displayName: null }
const VISITOR: AuthState = { status: 'ready', role: 'visitor', displayName: null }
const FAILED: AuthState = { status: 'error', role: 'visitor', displayName: null }

// E03(/api/me)으로 로그인 상태를 읽는다. 비로그인·비활성은 200 authenticated: false라서 방문자다.
async function loadAuthState(): Promise<AuthState> {
  try {
    const me = await apiFetch<MeResponse>('/api/me')
    if (me.authenticated && me.role) return { status: 'ready', role: me.role, displayName: me.display_name ?? null }
    return VISITOR
  } catch {
    return FAILED
  }
}

// 앱 전체에서 로그인 상태를 한곳에 둔다. 시작할 때 한 번 읽고, 로그인·로그아웃 뒤에는 refresh로 다시 읽는다.
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(LOADING)

  const refresh = useCallback(async () => {
    setState(await loadAuthState())
  }, [])

  useEffect(() => {
    let cancelled = false
    void loadAuthState().then((next) => {
      if (!cancelled) setState(next)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const value = useMemo<AuthContextValue>(() => ({ ...state, refresh }), [state, refresh])
  return <AuthContext value={value}>{children}</AuthContext>
}
