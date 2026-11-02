import { isApiError } from '../api/client.ts'

// 로그인 안내를 띄울 오류인지. HTTP 상태가 401이고 code가 login_required일 때만 true다.
// message 문자열로는 가르지 않는다(영어 고정 문구라 분기에 쓰지 않는다, API spec 1.4.6).
export function isLoginRequired(error: unknown): boolean {
  return isApiError(error, 'login_required') && error.status === 401
}
