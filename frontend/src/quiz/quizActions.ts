import { ApiError, apiFetch, isApiError } from '../api/client.ts'
import type { QuizItem } from '../api/types.ts'

export type AnswerResult = Required<Pick<QuizItem, 'your_answer' | 'correct_answer' | 'explanation' | 'difficulty' | 'can_request_followup'>> & { item_id: number; followups_remaining: number }
export type FollowupResult = { seq: number; question: string; followups_remaining: number }
export type FollowupAnswerResult = { seq: number; answered: boolean; can_request_followup: boolean }

// 화면을 나갔다 돌아와도 진행 중인 쓰기를 중복 전송하지 않는다. 계정은 세션 번호로 분리한다.
const pending = new Map<string, { answer: string | undefined; promise: Promise<unknown> }>()
const waits = new Map<string, { until: number; error: unknown }>()
export function actionKey(session: number, item: number, action: string): string { return `${session}:${item}:${action}` }
export function actionWait(key: string): number { return waits.get(key)?.until ?? 0 }

function request<T>(key: string, path: string, method: 'POST' | 'PUT', answer?: string): Promise<T> {
  const active = pending.get(key)
  if (active) {
    if (active.answer !== answer) return Promise.reject(new ApiError(409, { code: 'conflict', detail: 'write_pending', message: 'A write is pending', request_id: '' }))
    return active.promise as Promise<T>
  }
  const wait = waits.get(key)
  if (wait && wait.until > Date.now()) return Promise.reject(wait.error)
  waits.delete(key)
  const promise = apiFetch<T>(path, { method, ...(answer === undefined ? {} : { body: { answer } }) }).catch((error: unknown) => {
    if (isApiError(error) && (error.code === 'rate_limited' || error.detail === 'in_progress')) {
      const seconds = error.retryAfterSeconds ?? 60
      if (Number.isFinite(seconds) && seconds > 0) waits.set(key, { until: Date.now() + Math.min(seconds * 1000, 2_147_483_647), error })
    }
    throw error
  })
  const entry = { answer, promise }
  pending.set(key, entry)
  const clear = () => { if (pending.get(key) === entry) pending.delete(key) }
  void promise.then(clear, clear)
  return promise
}

export const submitAnswer = (session: number, item: number, answer: string) => request<AnswerResult>(actionKey(session, item, 'answer'), `/api/quiz/items/${item}/answer`, 'POST', answer)
export const generateFollowup = (session: number, item: number) => request<FollowupResult>(actionKey(session, item, 'followup'), `/api/quiz/items/${item}/followups`, 'POST')
export const saveFollowupAnswer = (session: number, item: number, seq: number, answer: string) => request<FollowupAnswerResult>(actionKey(session, item, `followup-${seq}`), `/api/quiz/items/${item}/followups/${seq}/answer`, 'PUT', answer)

// 목업에 없는 오류 문구는 임시 문구다. 서버 message나 내부 오류를 그대로 표시하지 않는다.
export function actionError(error: unknown): string {
  if (!isApiError(error)) return '처리하지 못했어요. 다시 확인해 주세요.'
  if (error.code === 'not_found') return '이 문항을 찾을 수 없어요. 퀴즈를 다시 불러와 주세요.'
  if (error.code === 'validation_failed') return '답을 1~1,000자로 입력해 주세요. 공백만으로는 저장할 수 없어요.'
  if (error.code === 'ai_limit_reached') return 'AI 사용 한도에 도달했어요. 나중에 다시 시도해 주세요.'
  if (error.code === 'ai_unavailable') return '꼬리 질문을 만들지 못했어요. 다시 시도해 주세요.'
  if (error.code === 'rate_limited') return '요청이 많아요. 잠시 뒤에 다시 시도해 주세요.'
  if (error.detail === 'already_answered') return '이미 다른 답이 저장되어 있어요. 퀴즈를 다시 불러와 확인해 주세요.'
  if (error.detail === 'answer_first') return '문항에 먼저 답해 주세요. 퀴즈를 다시 불러와 확인해 주세요.'
  if (error.detail === 'followup_limit_reached') return '꼬리 질문은 문항당 2개까지 받을 수 있어요.'
  if (error.detail === 'in_progress') return '꼬리 질문을 만드는 중이에요. 잠시 뒤에 다시 확인해 주세요.'
  if (error.detail === 'write_pending') return '이전에 보낸 답을 저장하고 있어요. 잠시 뒤 퀴즈를 다시 불러와 주세요.'
  return '처리 결과를 확인하지 못했어요. 퀴즈를 다시 불러와 확인해 주세요.'
}
