import { useCallback } from 'react'
import { isApiError } from '../api/client.ts'
import { useAuth } from '../auth/useAuth.ts'

// 운영자 권한을 잃었다고 서버가 알려 준 오류인지. 401(login_required)은 로그인이 풀린 것이고, 403(forbidden)은 운영자 권한이 없는 것이다.
// HTTP 상태와 code를 함께 본다. 같은 403이라도 origin_not_allowed 같은 다른 code는 권한 상실이 아니다. message로는 가르지 않는다(API spec 1.4.6).
export function isAuthLoss(error: unknown): boolean {
  return (isApiError(error, 'login_required') && error.status === 401) || (isApiError(error, 'forbidden') && error.status === 403)
}

// 운영자 화면이 API 오류를 받았을 때 부른다. 권한 상실이면 로그인 상태를 다시 읽는다. 역할이 바뀌면 경로 보호(RequireOperator)가 화면을 내보낸다.
// 처리했으면 true, 아니면 false(화면이 직접 다룬다). 화면마다 이 훅을 부르는 대신 useOperatorApi를 쓰면 호출할 때마다 자동으로 처리된다.
//   try { await apiFetch(...) } catch (error) { if (!onApiError(error)) setFailed(true) }
export function useOperatorGuard() {
  const { refresh } = useAuth()
  const onApiError = useCallback(
    (error: unknown): boolean => {
      if (!isAuthLoss(error)) return false
      void refresh()
      return true
    },
    [refresh],
  )
  return { onApiError }
}
