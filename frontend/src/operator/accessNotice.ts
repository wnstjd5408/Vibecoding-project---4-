// 운영자 경로에 들어올 수 없는 사람을 기본 화면으로 보낼 때 함께 넘기는 안내 종류. 라우터 location.state에 담긴다.
//  - login_required: 로그인하지 않았다(401)
//  - operator_only: 로그인했지만 운영자가 아니다(403)
export type AccessNoticeKind = 'login_required' | 'operator_only'

export type AccessNoticeState = { accessNotice: AccessNoticeKind }

export function readAccessNotice(state: unknown): AccessNoticeKind | null {
  const value = (state as { accessNotice?: unknown } | null)?.accessNotice
  return value === 'login_required' || value === 'operator_only' ? value : null
}
