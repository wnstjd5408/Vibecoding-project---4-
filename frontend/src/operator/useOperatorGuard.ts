import { useCallback } from 'react'
import { isApiError } from '../api/client.ts'
import { useAuth } from '../auth/useAuth.ts'

// 운영자 화면이 API 오류를 받았을 때 부른다. 401(login_required)이나 403(forbidden)이면 서버가 알려 준 권한 상실이므로
// 로그인 상태를 다시 읽는다. 역할이 바뀌면 경로 보호(RequireOperator)가 화면을 내보낸다. 처리했으면 true, 아니면 false(화면이 직접 다룬다).
//   try { await apiFetch(...) } catch (error) { if (!onApiError(error)) setFailed(true) }
export function useOperatorGuard() {
  const { refresh } = useAuth()
  const onApiError = useCallback(
    (error: unknown): boolean => {
      if (!isApiError(error, 'login_required') && !isApiError(error, 'forbidden')) return false
      void refresh()
      return true
    },
    [refresh],
  )
  return { onApiError }
}
