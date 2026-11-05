import type { QuizItem } from '../types.ts'
import type { MockRequest, MockResponse } from './handlers.ts'
import { currentSession } from '../../auth/sessionGeneration.ts'

let session = -1
let items: QuizItem[] = []
const answers = new Map<string, string>()
export function mockQuizItems(): QuizItem[] {
  if (session !== currentSession()) {
    session = currentSession()
    answers.clear()
    items = [
      { id: 41, difficulty: '중', question: '합성 질문 1입니다.', answered: false, followups: [], can_request_followup: false },
      { id: 42, difficulty: '하', question: '합성 질문 2입니다.', answered: true, your_answer: '합성 답변', correct_answer: '합성 정답', explanation: '합성 해설', followups: [{ seq: 1, question: '합성 꼬리 질문', answered: false }], can_request_followup: false },
    ]
  }
  return structuredClone(items)
}
function error(status: number, code: string, detail?: string): MockResponse {
  return { status, body: { error: { code, detail, message: 'Synthetic error', request_id: 'r-mock-quiz' } } }
}
export function mockQuizAction(request: MockRequest): MockResponse | null {
  const match = /^\/api\/quiz\/items\/(\d+)\/(answer|followups)(?:\/([12])\/answer)?$/.exec(request.path)
  if (!match) return null
  mockQuizItems()
  const item = items.find(value => value.id === Number(match[1]))
  if (!item) return error(404, 'not_found')
  const seq = Number(match[3])
  if (request.method === 'POST' && match[2] === 'followups' && !seq) {
    if (!item.answered) return error(409, 'conflict', 'answer_first')
    const existing = item.followups.find(value => !value.answered)
    if (existing) return { status: 200, body: { ...existing, followups_remaining: 2 - item.followups.length } }
    if (item.followups.length >= 2) return error(409, 'conflict', 'followup_limit_reached')
    const next = { seq: item.followups.length + 1, question: `합성 꼬리 질문 ${item.followups.length + 1}`, answered: false }
    item.followups.push(next)
    item.can_request_followup = false
    return { status: 200, body: { ...next, followups_remaining: 2 - item.followups.length } }
  }
  const answer = (request.body as { answer?: unknown } | null)?.answer
  if (typeof answer !== 'string' || !answer.trim() || [...answer].length > 1000) return error(422, 'validation_failed')
  if (request.method === 'POST' && match[2] === 'answer' && !seq) {
    if (item.answered && item.your_answer !== answer) return error(409, 'conflict', 'already_answered')
    item.answered = true
    item.your_answer = answer
    item.correct_answer = '합성 정답'
    item.explanation = '합성 해설'
    item.can_request_followup = item.followups.length < 2 && item.followups.every(value => value.answered)
    return { status: 200, body: { ...item, item_id: item.id, followups_remaining: 2 - item.followups.length } }
  }
  if (request.method === 'PUT' && seq) {
    const followup = item.followups.find(value => value.seq === seq)
    if (!followup) return error(404, 'not_found')
    const key = `${item.id}:${seq}`
    if (followup.answered && answers.get(key) !== answer) return error(409, 'conflict', 'already_answered')
    answers.set(key, answer)
    followup.answered = true
    item.can_request_followup = item.followups.length < 2 && item.followups.every(value => value.answered)
    return { status: 200, body: { seq, answered: true, can_request_followup: item.can_request_followup } }
  }
  return error(404, 'not_found')
}
