import { useContext } from 'react'
import { AuthContext } from './authContext.ts'
import type { AuthContextValue } from './authContext.ts'

// 로그인 상태를 읽는다. const { role, displayName, refresh } = useAuth()
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth는 AuthProvider 안에서만 쓸 수 있다')
  return value
}
