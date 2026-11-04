import type { AuthRole } from '../auth/authContext.ts'

// 역할 표시. 서버 값(member·operator)을 목업 문구로 바꿔 보인다. 사용자 내 정보(F4-5)와 운영자 내 정보(F4-3d)가 함께 쓴다.
export const ROLE_LABEL: Record<Exclude<AuthRole, 'visitor'>, string> = { member: '일반 사용자', operator: '운영자' }
