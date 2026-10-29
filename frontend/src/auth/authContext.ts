import { createContext } from 'react'

// 화면이 읽는 로그인 상태. 방문자는 비로그인이거나 비활성 계정이다(E03 authenticated: false).
// member·operator는 서버가 주는 역할 값 그대로다(api/types.ts의 Role). 별도 변환 없이 한 가지 어휘만 쓴다.
export type AuthRole = 'visitor' | 'member' | 'operator'

export type AuthState = {
  // loading: 첫 E03 응답 전, ready: 상태를 알았다, error: E03을 받지 못했다(이때 role은 visitor로 둔다)
  status: 'loading' | 'ready' | 'error'
  role: AuthRole
  displayName: string | null
}

export type AuthContextValue = AuthState & {
  // E03을 다시 불러 상태를 갱신하고, 방금 읽은 상태를 돌려준다. 로그인·로그아웃 뒤에 부른다.
  // 읽지 못해도 예외를 던지지 않고 status가 'error'인 상태를 돌려주므로, 완료를 성공으로 보지 말고 상태를 확인한다.
  refresh: () => Promise<AuthState>
  // 이미 확인한 상태를 추가 조회 없이 그대로 전역에 반영한다(예: 로그아웃 확인에서 방문자를 읽은 뒤). 진행 중인 조회 결과는 버린다.
  apply: (state: AuthState) => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)
