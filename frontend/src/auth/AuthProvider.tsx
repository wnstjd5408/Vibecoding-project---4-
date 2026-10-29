import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { AuthContext } from './authContext.ts'
import type { AuthContextValue, AuthState } from './authContext.ts'
import { createLatestRequest } from './latestRequest.ts'
import { LOADING, loadAuthState } from './loadAuthState.ts'

// 앱 전체에서 로그인 상태를 한곳에 둔다. 시작할 때 한 번 읽고, 로그인·로그아웃 뒤에는 refresh로 다시 읽는다.
// 시작 조회와 refresh가 겹쳐도 가장 나중에 시작한 요청의 결과만 반영한다.
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(LOADING)
  const requests = useRef(createLatestRequest())

  const refresh = useCallback(async () => {
    const id = requests.current.begin()
    const next = await loadAuthState()
    if (requests.current.isLatest(id)) setState(next)
    // 호출한 쪽이 방금 읽은 상태를 확인할 수 있게 돌려준다(예: 로그인 뒤 상태를 확인하고 이동).
    return next
  }, [])

  useEffect(() => {
    const gate = requests.current
    const id = gate.begin()
    void loadAuthState().then((next) => {
      if (gate.isLatest(id)) setState(next)
    })
    return () => {
      // 이 효과가 정리되면(StrictMode 재실행·언마운트) 이 조회 결과는 오래된 것이 된다.
      gate.begin()
    }
  }, [])

  const value = useMemo<AuthContextValue>(() => ({ ...state, refresh }), [state, refresh])
  return <AuthContext value={value}>{children}</AuthContext>
}
