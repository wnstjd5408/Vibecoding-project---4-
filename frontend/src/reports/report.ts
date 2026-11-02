// 오류 신고(E10) 요청과 오류 분류.
import { apiFetchWithStatus, isApiError } from '../api/client.ts'
import type { ReportResponse, ReportTarget } from '../api/types.ts'

// 신고 본문 상한(E10). 공백 제거·유니코드 정규화 없이 입력한 그대로 코드포인트 단위로 센다(서버와 같은 기준, 김준성 2026-11-02).
// 조합 이모지는 화면에 하나로 보여도 여러 코드포인트라 여러 글자로 센다.
export const REPORT_BODY_LIMIT = 1000

export function countChars(text: string): number {
  return [...text].length
}

// 붙여 넣기로 상한을 넘으면 앞 1,000자만 남긴다.
export function clampBody(text: string): string {
  const chars = [...text]
  return chars.length > REPORT_BODY_LIMIT ? chars.slice(0, REPORT_BODY_LIMIT).join('') : text
}

// alreadyReported: 같은 대상의 열린 신고가 이미 있어 서버가 200으로 기존 신고를 돌려준 경우. 오류가 아니라 성공이다.
export async function sendReport(target: ReportTarget, body: string): Promise<{ alreadyReported: boolean }> {
  const { status } = await apiFetchWithStatus<ReportResponse>('/api/reports', { method: 'POST', body: { target, body } })
  return { alreadyReported: status === 200 }
}

export type ReportFailure = 'not_found' | 'body_too_long' | 'body_invalid' | 'rate_limited' | 'failed'

// 오류를 code와 fields[].reason으로 구분한다. message 글자로 나누지 않는다.
// 404는 대상이 없는 경우와 권한이 없는 경우를 서버가 구분하지 않으므로 사유를 추측하지 않는다.
export function classifyReportError(error: unknown): ReportFailure {
  if (isApiError(error, 'not_found')) return 'not_found'
  if (isApiError(error, 'rate_limited')) return 'rate_limited'
  if (isApiError(error, 'validation_failed')) {
    const field = error.fields.find((item) => item.name === 'body')
    if (field?.reason === 'too_long') return 'body_too_long'
    if (field) return 'body_invalid'
    // 대상 자체가 잘못됐다(target 누락, target.type 허용 밖 등). 다시 보내도 같으므로 404와 같은 공통 안내다.
    if (error.fields.some((item) => item.name === 'target' || item.name.startsWith('target.'))) return 'not_found'
  }
  return 'failed'
}
