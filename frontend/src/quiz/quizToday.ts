// 오늘의 퀴즈(E11) 요청과 오류 분류. 한 번에 하나만 보내고, 서버가 준 대기 시간 동안은 다시 보내지 않는다.
import { apiFetch, isApiError } from '../api/client.ts'
import type { QuizTodayResponse } from '../api/types.ts'

let inFlight: Promise<QuizTodayResponse> | null = null
// 429가 준 retry_after_seconds 동안은 요청하지 않는다. 화면을 나갔다 돌아와도 이어진다.
let wait: { until: number; error: unknown } | null = null

// 서버가 지정한 재시도 가능 시각(ms). 기다릴 필요가 없으면 null이다.
export function quizRetryAvailableAt(): number | null {
  return wait !== null && wait.until > Date.now() ? wait.until : null
}

// 진행 중인 요청이 있으면 새로 보내지 않고 그 요청을 이어서 본다(화면이 다시 만들어져도 중복 요청이 나가지 않는다).
export function requestQuizToday(): Promise<QuizTodayResponse> {
  if (inFlight) return inFlight
  if (wait !== null) {
    if (wait.until > Date.now()) return Promise.reject(wait.error)
    wait = null
  }
  const request = apiFetch<QuizTodayResponse>('/api/quiz/today', { method: 'POST' }).catch((error: unknown) => {
    if (isApiError(error, 'rate_limited') && error.retryAfterSeconds !== undefined && error.retryAfterSeconds > 0) {
      wait = { until: Date.now() + error.retryAfterSeconds * 1000, error }
    }
    throw error
  })
  inFlight = request
  const clear = () => {
    if (inFlight === request) inFlight = null
  }
  request.then(clear, clear)
  return request
}

// generating일 때 다시 부르기까지 기다릴 시간(ms). 서버 값이 없거나 이상하면 임시로 5초, 너무 짧으면 1초로 맞춘다.
export const DEFAULT_POLL_SECONDS = 5
export const MIN_POLL_SECONDS = 1
export function pollDelayMs(retryAfterSeconds: unknown): number {
  const seconds = typeof retryAfterSeconds === 'number' && Number.isFinite(retryAfterSeconds) && retryAfterSeconds > 0 ? retryAfterSeconds : DEFAULT_POLL_SECONDS
  // setTimeout은 약 24일(2^31-1ms)을 넘으면 바로 실행되므로 그 안으로 맞춘다.
  return Math.min(Math.max(seconds, MIN_POLL_SECONDS) * 1000, 2_147_483_647)
}

// 오류를 code로 가른다(message 글자로 가르지 않는다). 401 login_required는 화면이 공통 로그인 안내로 따로 처리한다.
export type QuizFailure = 'rate_limited' | 'ai_unavailable' | 'failed'

export function classifyQuizError(error: unknown): QuizFailure {
  if (isApiError(error, 'rate_limited')) return 'rate_limited'
  if (isApiError(error, 'ai_unavailable')) return 'ai_unavailable'
  return 'failed'
}
