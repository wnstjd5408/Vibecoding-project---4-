import { useCallback } from 'react'
import { apiFetch } from '../api/client.ts'
import type { ApiRequestInit } from '../api/client.ts'
import { useOperatorGuard } from './useOperatorGuard.ts'

// 운영자 API(E19~E26 등)를 부르는 함수. apiFetch와 같지만, 서버가 권한 상실(401 login_required·403 forbidden)을 알려 주면
// 로그인 상태를 다시 읽어 경로 보호가 화면을 내보내게 한 뒤 오류는 그대로 던진다. 운영자 화면에서는 apiFetch 대신 이것을 쓰면
// 권한 처리를 따로 챙기지 않아도 된다.
//   const operatorFetch = useOperatorApi()
//   try { const data = await operatorFetch<Report[]>('/api/reports') } catch (error) { setFailed(true) } // 권한 상실이면 이미 처리됐다
// 권한 상실 오류는 던져지므로 화면은 일반 실패와 같이 다뤄도 된다(곧 화면이 내보내진다).
export function useOperatorApi() {
  const { onApiError } = useOperatorGuard()
  return useCallback(
    async <T>(path: string, init?: ApiRequestInit): Promise<T> => {
      try {
        return await apiFetch<T>(path, init)
      } catch (error) {
        onApiError(error)
        throw error
      }
    },
    [onApiError],
  )
}
