// 계정 발급(E24: POST /api/admin/users, 운영자만) 호출과 실패 분류. 화면은 이 파일의 함수만 부른다.
//
// TODO(MEG-68): E24 명세(MEG-27 첨부)를 받으면 요청 본문 이름과 422의 fields[].name을 맞춘다. 경로는 docs/architecture/architecture.json에 있고,
// 요청 본문은 E01과 같은 이름으로 추정했다({ email, display_name, password }). 결과 화면은 응답 필드에 기대지 않고 입력한 값을 보여 주므로
// 응답 모양이 달라도 화면은 바뀌지 않는다.
import type { ApiRequestInit } from '../../api/client.ts'
import { isApiError } from '../../api/client.ts'

export const ISSUE_ACCOUNT_PATH = '/api/admin/users'

export type IssueAccountInput = { email: string; displayName: string; password: string }

// useOperatorApi()가 돌려주는 함수. 권한 상실(401·403)이면 로그인 상태를 다시 읽고 오류는 그대로 던진다.
export type OperatorFetch = <T>(path: string, init?: ApiRequestInit) => Promise<T>

// 계정을 발급한다. 성공하면 아무것도 돌려주지 않는다(비밀번호를 비롯해 입력값이 이 함수 밖에 남지 않게 한다).
export async function issueAccount(operatorFetch: OperatorFetch, input: IssueAccountInput): Promise<void> {
  await operatorFetch(ISSUE_ACCOUNT_PATH, {
    method: 'POST',
    body: { email: input.email, display_name: input.displayName, password: input.password },
  })
}

// 폼 칸 이름별 오류 reason(서버의 fields[].reason). 값이 있는 칸만 오류다.
export type FieldReasons = { email?: string; displayName?: string; password?: string }

// 발급 실패를 화면이 고르는 안내 종류로 나눈다. message 글자로는 가르지 않는다(영어 고정 문구, API spec 1.4.6).
//  - email_exists: 409 conflict, detail email_exists. 같은 이메일의 계정이 이미 있다
//  - invalid: 422 validation_failed. fields[].reason으로 어느 칸이 왜 틀렸는지 안다
//  - other: 그 밖(네트워크 실패, 5xx, 형식이 다른 응답 등)
export type IssueFailure = { kind: 'email_exists' } | { kind: 'invalid'; fields: FieldReasons } | { kind: 'other' }

const FIELD_KEYS: Record<string, keyof FieldReasons> = { email: 'email', display_name: 'displayName', password: 'password' }

export function classifyIssueFailure(error: unknown): IssueFailure {
  if (isApiError(error, 'conflict', 'email_exists')) return { kind: 'email_exists' }
  if (isApiError(error, 'validation_failed')) {
    const fields: FieldReasons = {}
    for (const field of error.fields) {
      const key = FIELD_KEYS[field.name]
      if (key) fields[key] = field.reason
    }
    return { kind: 'invalid', fields }
  }
  return { kind: 'other' }
}
