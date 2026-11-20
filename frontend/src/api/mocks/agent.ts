// CS Agent E27~E32의 가짜 응답(MEG-255). 값은 모두 합성이다. 서버(backend/app/agent*.py)의 응답 모양과 규칙을 흉내 낸다.
//  - E29는 실제 서버처럼 text/event-stream 바이트를 시간차를 두고 보낸다. 화면 코드는 실제 응답과 같은 SSE 파서로 읽는다.
//  - 서버 쪽 턴은 스트림과 따로 진행한다. 스트림이 끊겨도 턴은 끝까지 가고, E30이 그 결과를 준다(MEG-229 Q2 실측과 같다).
//  - 같은 키 재전송(재생·409 in_progress), 다른 대화의 키(409 idempotency_key_reused), 같은 대화의 진행 중 턴(409 turn_in_progress),
//    E31 중단을 서버 규칙대로 돌려준다.
//  - revokeAgentMockSources()는 지금까지 끝난 답변의 출처를 볼 수 없게 만든다. 서버의 가림 함수(agent_access.hidden_marks)처럼
//    그 출처를 쓴 첫 턴부터 가리고, 다시 묻기(retry_of_turn_id)는 그 첫 턴에만 한 번 허용한다(MEG-260, F6-15b).
//  - revokeAgentMockNote()는 대화의 노트를 볼 수 없게 만든다. E27~E32가 404다(F6-15).
// 시나리오는 setAgentMockScenario로 고른다. 다시 고르거나 resetAgentMock을 부를 때까지 다음 질문마다 같은 시나리오를 쓴다.
// 다만 rate_limited와 turn_in_progress는 한 번 거절한 뒤 answered로 돌아간다(기다린 뒤 다시 보내면 성공하는 흐름).
// 화면 개발 중에는 브라우저 콘솔이나 시험에서 `await import('/src/api/mocks/agent.ts')`로 불러 바꿀 수 있다.
import { newIdempotencyKey } from '../../ai/explain.ts'
import type {
  AgentConversation,
  AgentQuestion,
  AgentResult,
  AgentStep,
  AgentTurn,
  AskTurnRequest,
  CreateConversationRequest,
  TurnFailure,
} from '../../agent/types.ts'
import type { ApiErrorBody } from '../types.ts'
import { handleMock } from './handlers.ts'
import type { MockResponse, Route } from './handlers.ts'
import { getMockSession } from './session.ts'

export type AgentMockScenario =
  | 'answered' // 단계 3개를 거쳐 answered로 끝난다
  | 'delayed' // 생성 단계에서 delayed 이벤트가 온 뒤 answered로 끝난다
  | 'partial'
  | 'clarify'
  | 'no_evidence'
  | 'correction'
  | 'topic_check'
  | 'error' // 스트림 시작 뒤 실패(error 이벤트 ai_unavailable, 턴은 failed(error))
  | 'limit_after_start' // 스트림 시작 뒤 한도 초과(error 이벤트 ai_limit_reached, 턴은 failed(limit))
  | 'disconnect' // 자료 찾기 단계 뒤 연결이 끊긴다. 서버 쪽 턴은 조금 뒤 answered로 끝난다
  | 'eof' // 자료 찾기 단계 뒤 스트림이 마지막 이벤트 없이 닫힌다. 서버 쪽 턴은 조금 뒤 answered로 끝난다
  | 'rate_limited' // 스트림 전 429 rate_limited(retry_after_seconds 1). 한 번만
  | 'ai_limit_reached' // 스트림 전 429 ai_limit_reached
  | 'turn_in_progress' // 같은 대화에 다른 턴이 진행 중이다(409 turn_in_progress). 그 턴은 조금 뒤 answered로 끝난다. 한 번만
  | 'service_unavailable' // E27·E29가 503(노출 중단 플래그)

export type AgentMockRequest = { method: string; path: string; idempotencyKey?: string; body?: unknown }

// 서버는 2초를 권한다(TURN_POLL_SECONDS). 가짜 응답은 시험이 빨리 끝나도록 1초로 둔다.
const POLL_SECONDS = 1
// 끊긴 뒤 서버 쪽 턴이 끝나기까지 남은 시간. E30 첫 조회가 running을 보도록 조회 간격보다 길게 둔다.
const AFTER_CUT_MS = 1200

let scenario: AgentMockScenario = 'answered'
let stepMs = 80
let requests: AgentMockRequest[] = []

type MockTurn = {
  turn: Omit<AgentTurn, 'status' | 'result' | 'failure' | 'step' | 'finished_at'>
  conversationId: string
  key: string
  scenario: AgentMockScenario
  startedAt: number
  // 스트림 이벤트 시각(시작 기준 ms)
  timeline: { at: number; event: string; data: unknown; step?: AgentStep }[]
  finishAt: number
  // 스트림이 끊기거나 닫히는 시각(시작 기준 ms). 없으면 끝까지 보낸다.
  cutAt: number | null
  final: { status: 'completed' | 'failed'; result?: AgentResult; failure?: TurnFailure; code?: string }
  cancelledAt: number | null
  // 다시 묻기 턴이면 대상 턴 id
  retryOf: string | null
  // revokeAgentMockSources()로 이 턴이 인용한 출처를 볼 수 없게 됐다
  revoked: boolean
}

type MockConversation = { conversation: AgentConversation; turnIds: string[] }

const conversations = new Map<string, MockConversation>()
const turns = new Map<string, MockTurn>()
const keys = new Map<string, string>()
let noteRevoked = false

export function setAgentMockScenario(next: AgentMockScenario, options: { stepMs?: number } = {}): void {
  scenario = next
  if (options.stepMs !== undefined) stepMs = options.stepMs
}

export function resetAgentMock(): void {
  scenario = 'answered'
  stepMs = 80
  requests = []
  conversations.clear()
  turns.clear()
  keys.clear()
  noteRevoked = false
}

// 지금까지 끝난 답변(출처가 있는 completed 턴)의 출처를 볼 수 없게 만든다. 뒤에 만드는 턴은 영향이 없다.
export function revokeAgentMockSources(): void {
  const now = Date.now()
  for (const turn of turns.values()) {
    const final = turn.final.result
    if (statusAt(turn, now).status === 'completed' && final && 'sources' in final && (final.sources ?? []).length > 0) turn.revoked = true
  }
}

// 대화의 노트를 볼 수 없게 만든다(삭제·비공개 전환). E27~E32가 404를 돌려준다.
export function revokeAgentMockNote(): void {
  noteRevoked = true
}

// 시험이 보낸 요청(경로·Idempotency-Key)을 확인할 때 쓴다.
export function agentMockRequests(): AgentMockRequest[] {
  return requests.map((request) => ({ ...request }))
}

function errorBody(status: number, code: string, message: string, extra: Partial<ApiErrorBody['error']> = {}): MockResponse {
  const body: ApiErrorBody = { error: { code, message, request_id: 'r-mock-agent', ...extra } }
  return { status, body }
}

const loginRequired = () => errorBody(401, 'login_required', 'Login is required')
const notFound = () => errorBody(404, 'not_found', 'Resource not found')
const unavailable = () => errorBody(503, 'service_unavailable', 'Service temporarily unavailable; retry later')

// --- 합성 결과 ---

const NOTE_SOURCES = [
  { ref: 1, source_kind: 'note' as const, title: '예시 노트 · 요청이 서버까지 가는 길', section: '요청 흐름', excerpt: '합성 근거 문단 하나', cited_revision: 3 },
  { ref: 2, source_kind: 'note' as const, title: '예시 노트 · 캐시가 오래된 값을 돌려주는 경우', section: '만료', excerpt: '합성 근거 문단 둘', cited_revision: 1 },
]

function resultFor(kind: AgentMockScenario, topic: string): AgentResult {
  switch (kind) {
    case 'partial':
      return {
        state: 'partial',
        sections: [{ heading: '핵심', body: '합성 부분 답변 문장입니다 [1].' }],
        limitation: '합성 한계 문장입니다.',
        sources: [NOTE_SOURCES[0]],
      }
    case 'clarify':
      return {
        state: 'clarify',
        clarify: {
          prompt: '어느 뜻으로 물어보셨나요?',
          options: [
            { option_id: 'o-1', label: '합성 뜻 하나' },
            { option_id: 'o-2', label: '합성 뜻 둘' },
          ],
        },
      }
    case 'no_evidence':
      return { state: 'no_evidence', notice_code: 'no_evidence', next_actions: ['rephrase', 'new_conversation'] }
    case 'correction':
      return {
        state: 'correction',
        sections: [{ heading: '핵심', body: '합성 교정 설명입니다 [1].' }],
        corrections: [{ note_excerpt: '합성 노트 문장', corrected: '합성 고친 내용 [1]', source_refs: [1] }],
        unresolved: ['합성 노트 문장 둘은 참고한 노트에서 확인하지 못했어요. 맞는지 틀린지는 판단하지 않았어요.'],
        sources: [NOTE_SOURCES[0]],
      }
    case 'topic_check':
      return { state: 'topic_check', topic_check: { current_topic: topic } }
    default:
      return {
        state: 'answered',
        sections: [
          { heading: '핵심', body: '합성 답변 첫 절입니다 [1].' },
          { heading: '원리', body: '합성 답변 둘째 절입니다 [2].' },
        ],
        sources: NOTE_SOURCES,
        figures: [
          {
            figure_id: 'f-1',
            kind: 'diagram',
            mermaid: 'flowchart LR\n  A[요청] --> B[응답]',
            caption: '합성 그림',
            alt_text: '요청에서 응답으로 가는 합성 그림',
            source_refs: [1],
            after_section: 1,
          },
        ],
        suggestions: ['합성 추천 질문 하나', '합성 추천 질문 둘'],
      }
  }
}

const PRESET_TEXT = { detail: '더 자세히 설명해 줘', simple: '더 쉽게 설명해 줘', example: '예시를 들어 설명해 줘' } as const

// --- 서버 쪽 턴 ---

function statusAt(turn: MockTurn, now: number): { status: AgentTurn['status']; step?: AgentStep } {
  if (turn.cancelledAt !== null) return { status: 'cancelled' }
  if (now >= turn.finishAt) return { status: turn.final.status }
  const elapsed = now - turn.startedAt
  const passed = turn.timeline.filter((entry) => entry.at <= elapsed && entry.step !== undefined)
  return { status: 'running', step: passed.at(-1)?.step ?? 'understand' }
}

type MockHidden = NonNullable<AgentTurn['hidden']>

// 서버 가림 함수(agent_access.hidden_marks)를 줄인 것. 볼 수 없는 출처를 쓴 첫 턴(X)부터 가리고, X를 대상으로 한 다시 묻기 턴에서
// 연쇄가 끝난다. 완료된 다시 묻기가 있거나 X가 가린 턴의 추천 질문이면 X의 retry_allowed는 false다.
function hiddenMarks(conversationId: string, now: number): Map<string, MockHidden | null> {
  const ordered = (conversations.get(conversationId)?.turnIds ?? []).map((id) => turns.get(id)!)
  const retried = new Set(ordered.filter((turn) => turn.retryOf !== null && statusAt(turn, now).status === 'completed').map((turn) => turn.retryOf))
  const marks = new Map<string, MockHidden | null>()
  let first: string | null = null
  for (const turn of ordered) {
    const id = turn.turn.turn_id
    if (first !== null && turn.retryOf === first) first = null
    if (first === null && turn.revoked) {
      first = id
      const from = turn.turn.question.kind === 'suggested' ? turn.turn.question.from_turn_id : undefined
      const fromHidden = from !== undefined && (marks.get(from) ?? null) !== null
      marks.set(id, { reason: 'source_revoked', retry_allowed: !retried.has(id) && !fromHidden })
    } else if (first === null) {
      marks.set(id, null)
    } else {
      marks.set(id, { reason: 'source_revoked', retry_allowed: false })
    }
  }
  return marks
}

// 가린 추천 질문 턴은 질문 글을 뺀다(agent_access.turn_payload).
function visibleQuestion(question: AgentQuestion, hidden: MockHidden | null): AgentQuestion {
  if (!hidden || question.kind !== 'suggested') return question
  const { text: _text, ...rest } = question
  void _text
  return rest
}

function payloadOf(turn: MockTurn, now: number = Date.now()): AgentTurn {
  const { status, step } = statusAt(turn, now)
  const hidden = hiddenMarks(turn.conversationId, now).get(turn.turn.turn_id) ?? null
  const payload: AgentTurn = { ...turn.turn, question: visibleQuestion(turn.turn.question, hidden), status }
  if (hidden) payload.hidden = hidden
  if (status === 'running' && step) payload.step = step
  if (status === 'completed' && !hidden) payload.result = turn.final.result
  if (status === 'failed') payload.failure = turn.final.failure
  if (status !== 'running') {
    const at = turn.cancelledAt ?? turn.finishAt
    payload.finished_at = new Date(at).toISOString()
  }
  return payload
}

function questionOf(body: AskTurnRequest): AgentQuestion | null {
  const question = body.question
  if (question === undefined) return null
  if (question.kind === 'free') return question.text ? { kind: 'free', text: question.text } : null
  if (question.kind === 'suggested') {
    return question.text && question.from_turn_id ? { kind: 'suggested', text: question.text, from_turn_id: question.from_turn_id } : null
  }
  if (question.kind === 'preset' && question.preset in PRESET_TEXT) {
    return { kind: 'preset', text: PRESET_TEXT[question.preset], preset: question.preset }
  }
  return null
}

function createTurn(conversation: MockConversation, key: string, question: AgentQuestion, kind: AgentMockScenario, retryOf: string | null = null): MockTurn {
  const now = Date.now()
  const id = newIdempotencyKey()
  const steps: [AgentStep, 'current' | 'done', Record<string, unknown>?][] = [
    ['understand', 'current'],
    ['understand', 'done'],
    ['retrieve', 'current'],
    ['retrieve', 'done', { paragraph_count: kind === 'no_evidence' ? 0 : 3, source_kind: 'note' }],
    ['compose', 'current'],
    ['compose', 'done'],
  ]
  // 근거가 없으면 모델을 부르지 않고 자료 찾기 뒤에 끝난다(spec E29 6단계).
  const used = kind === 'no_evidence' ? steps.slice(0, 4) : kind === 'error' || kind === 'limit_after_start' ? steps.slice(0, 5) : steps
  const timeline: MockTurn['timeline'] = []
  let at = 0
  for (const [step, state, extra] of used) {
    at += stepMs
    timeline.push({ at, event: 'step', data: { step, state, ...extra }, step })
    if (kind === 'delayed' && step === 'compose' && state === 'current') {
      at += stepMs
      timeline.push({ at, event: 'delayed', data: {} })
    }
  }
  at += stepMs
  const cutAt = kind === 'disconnect' || kind === 'eof' ? timeline[3].at + stepMs / 2 : null
  const finishAt = now + (cutAt !== null ? Math.max(at, cutAt + AFTER_CUT_MS) : at)
  const final: MockTurn['final'] =
    kind === 'error'
      ? { status: 'failed', failure: 'error', code: 'ai_unavailable' }
      : kind === 'limit_after_start'
        ? { status: 'failed', failure: 'limit', code: 'ai_limit_reached' }
        : { status: 'completed', result: resultFor(kind, conversation.conversation.topic_label) }
  const turn: MockTurn = {
    turn: { turn_id: id, seq: conversation.turnIds.length + 1, question, created_at: new Date(now).toISOString() },
    conversationId: conversation.conversation.conversation_id,
    key,
    scenario: kind,
    startedAt: now,
    timeline,
    finishAt,
    cutAt,
    final,
    cancelledAt: null,
    retryOf,
    revoked: false,
  }
  if (conversation.conversation.origin === 'none' && conversation.conversation.topic_label === '' && question.text) {
    conversation.conversation.topic_label = question.text.slice(0, 20)
  }
  conversation.turnIds.push(id)
  turns.set(id, turn)
  keys.set(key, id)
  return turn
}

// --- SSE ---

const encoder = new TextEncoder()

function sse(event: string, data: unknown): Uint8Array {
  return encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
}

function endEvent(turn: MockTurn): Uint8Array {
  const payload = payloadOf(turn)
  if (payload.status === 'failed') {
    const code = turn.final.code ?? 'internal_error'
    const message = code === 'ai_limit_reached' ? 'AI usage limit reached; retry later' : 'AI service did not return a usable response'
    return sse('error', { error: { code, message, request_id: 'r-mock-agent' } })
  }
  return sse('result', payload)
}

function abortError(): Error {
  return new DOMException('The operation was aborted.', 'AbortError')
}

// 실행 중인 턴의 이벤트를 시간에 맞춰 보낸다. 중단되면 다음 순간에 cancelled 결과로 끝낸다.
function liveStream(turn: MockTurn, signal: AbortSignal | undefined): ReadableStream<Uint8Array> {
  const timers: ReturnType<typeof setTimeout>[] = []
  let closed = false
  return new ReadableStream<Uint8Array>({
    start(controller) {
      const stop = () => {
        closed = true
        for (const timer of timers) clearTimeout(timer)
      }
      const finish = () => {
        if (closed) return
        controller.enqueue(endEvent(turn))
        // 실제 서버처럼 마지막 이벤트 뒤에 keep-alive 주석을 한 번 보낸 뒤 닫는다.
        controller.enqueue(encoder.encode(': keep-alive\n\n'))
        stop()
        controller.close()
      }
      signal?.addEventListener(
        'abort',
        () => {
          if (closed) return
          stop()
          controller.error(abortError())
        },
        { once: true },
      )
      controller.enqueue(sse('turn', { turn_id: turn.turn.turn_id, seq: turn.turn.seq }))
      controller.enqueue(encoder.encode(': keep-alive\n\n'))
      const schedule = (at: number, run: () => void) => {
        timers.push(
          setTimeout(() => {
            if (closed) return
            if (turn.cancelledAt !== null) return finish()
            run()
          }, Math.max(turn.startedAt + at - Date.now(), 0)),
        )
      }
      for (const entry of turn.timeline) {
        if (turn.cutAt !== null && entry.at >= turn.cutAt) continue
        schedule(entry.at, () => controller.enqueue(sse(entry.event, entry.data)))
      }
      if (turn.cutAt !== null) {
        schedule(turn.cutAt, () => {
          stop()
          if (turn.scenario === 'eof') controller.close()
          else controller.error(new TypeError('network error'))
        })
        return
      }
      schedule(turn.finishAt - turn.startedAt, finish)
      // 중단(E31)은 다음 단계 전에 알아챈다. 단계 사이가 길지 않으므로 짧게 확인한다.
      const watch = setInterval(() => {
        if (closed) return clearInterval(watch)
        if (turn.cancelledAt !== null) {
          clearInterval(watch)
          finish()
        }
      }, Math.max(stepMs / 2, 10))
      timers.push(watch as unknown as ReturnType<typeof setTimeout>)
    },
    cancel() {
      closed = true
      for (const timer of timers) clearTimeout(timer)
    },
  })
}

// 끝난 턴의 같은 키 재생: turn 이벤트와 마지막 이벤트만 보낸다(agent_turns.ask).
function replayStream(turn: MockTurn): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(sse('turn', { turn_id: turn.turn.turn_id, seq: turn.turn.seq }))
      controller.enqueue(endEvent(turn))
      controller.close()
    },
  })
}

function runningTurnOf(conversation: MockConversation, now: number): MockTurn | undefined {
  return conversation.turnIds.map((id) => turns.get(id)!).find((turn) => statusAt(turn, now).status === 'running')
}

// E29. 스트림을 열면 { stream }, 스트림 전에 거절하면 { status, body }다.
export function openMockTurnStream(request: {
  conversationId: string
  body: AskTurnRequest
  key: string
  signal?: AbortSignal
}): { stream: ReadableStream<Uint8Array> } | { status: number; body?: unknown } {
  const { conversationId, body, key, signal } = request
  requests.push({ method: 'POST', path: `/api/ai/conversations/${conversationId}/turns`, idempotencyKey: key, body })
  if (getMockSession() === 'visitor') return loginRequired()
  if (scenario === 'service_unavailable') return unavailable()
  const conversation = conversations.get(conversationId)
  if (!conversation || noteRevoked) return notFound()
  const now = Date.now()
  const existingId = keys.get(key)
  if (existingId !== undefined) {
    const existing = turns.get(existingId)!
    if (existing.conversationId !== conversationId) {
      return errorBody(409, 'conflict', 'This Idempotency-Key was already used for another conversation', { detail: 'idempotency_key_reused' })
    }
    if (statusAt(existing, now).status === 'running') {
      return errorBody(409, 'conflict', 'The same request is still being processed', {
        detail: 'in_progress',
        retry_after_seconds: POLL_SECONDS,
        turn_id: existing.turn.turn_id,
      })
    }
    return { stream: replayStream(existing) }
  }
  let retryOf: string | null = null
  let question = questionOf(body)
  if (body.question === undefined && body.retry_of_turn_id) {
    // 질문 없는 다시 묻기: 대상 턴에 저장된 질문을 쓴다(MEG-257). 대상은 retry_allowed가 true인 가린 턴이어야 한다.
    const target = turns.get(body.retry_of_turn_id)
    if (target && target.conversationId === conversationId) {
      if (!hiddenMarks(conversationId, now).get(target.turn.turn_id)?.retry_allowed) {
        return errorBody(409, 'conflict', 'This question cannot be sent again', { detail: 'turn_not_retryable' })
      }
      question = target.turn.question
      retryOf = target.turn.turn_id
    }
  }
  if (question === null) {
    return errorBody(422, 'validation_failed', 'Request validation failed', {
      fields: [{ name: 'question', reason: 'invalid_value', message: 'Value is not allowed or refers to a missing item' }],
    })
  }
  if (scenario === 'turn_in_progress' && !runningTurnOf(conversation, now)) {
    // 다른 탭에서 보낸 것처럼 같은 대화에 다른 키의 턴을 먼저 실행해 둔다. 한 번만 쓰고 answered로 돌아간다.
    scenario = 'answered'
    const other = createTurn(conversation, newIdempotencyKey(), { kind: 'free', text: '다른 곳에서 보낸 합성 질문' }, 'answered')
    other.finishAt = other.startedAt + AFTER_CUT_MS + stepMs
  }
  const running = runningTurnOf(conversation, now)
  if (running) {
    return errorBody(409, 'conflict', 'Another question is still being answered', {
      detail: 'turn_in_progress',
      retry_after_seconds: POLL_SECONDS,
      turn_id: running.turn.turn_id,
    })
  }
  if (scenario === 'rate_limited') {
    // 한 번만 거절하고 answered로 돌아간다. 기다린 뒤 다시 보내면 성공하는 흐름을 화면에서 볼 수 있게 한다.
    scenario = 'answered'
    return errorBody(429, 'rate_limited', 'Too many requests; retry later', { retry_after_seconds: POLL_SECONDS })
  }
  if (scenario === 'ai_limit_reached') return errorBody(429, 'ai_limit_reached', 'AI usage limit reached; retry later')
  // 확인 카드에 답한 질문(의미 확인 선택·보충, 주제 전환 '이 대화에서 계속')과 다시 묻기는 같은 확인을 다시 하지 않는다.
  // 앞에 끝난 답이 없으면 그 질문이 주제를 정하므로 주제 전환 확인을 하지 않는다(agent_turns.check_request).
  const answeredBefore = conversation.turnIds.some((turnId) => statusAt(turns.get(turnId)!, now).status === 'completed')
  const confirmed = body.reply || retryOf
  const kind = (confirmed && (scenario === 'clarify' || scenario === 'topic_check')) || (scenario === 'topic_check' && !answeredBefore) ? 'answered' : scenario
  const turn = createTurn(conversation, key, question, kind, retryOf)
  return { stream: liveStream(turn, signal) }
}

// --- E27·E28·E30·E31·E32 ---

function readMockNote(noteId: number): { revision: number; title: string; body_markdown: string } | null {
  const response = handleMock({ method: 'GET', path: `/api/notes/${noteId}`, query: new URLSearchParams(), body: undefined })
  if (response.status !== 200) return null
  return response.body as { revision: number; title: string; body_markdown: string }
}

function createConversation(body: CreateConversationRequest): MockResponse {
  const id = newIdempotencyKey()
  const created_at = new Date().toISOString()
  if (body.origin === 'none') {
    const conversation: AgentConversation = { conversation_id: id, topic_label: '', origin: 'none', context_selections: [], created_at }
    conversations.set(id, { conversation, turnIds: [] })
    return { status: 201, body: conversation }
  }
  if (body.origin !== 'note' || !body.selection) {
    return errorBody(422, 'validation_failed', 'Request validation failed', {
      fields: [{ name: 'origin', reason: 'invalid_value', message: 'Value is not allowed or refers to a missing item' }],
    })
  }
  const note = readMockNote(body.note_id)
  if (!note) return notFound()
  if (note.revision !== body.note_revision) {
    return errorBody(409, 'conflict', 'The note changed; reload and try again', { detail: 'stale_revision' })
  }
  const text = [...note.body_markdown].slice(body.selection.start, body.selection.end).join('')
  if (body.selection.end <= body.selection.start || !text.trim()) {
    return errorBody(422, 'validation_failed', 'Request validation failed', {
      fields: [{ name: 'selection', reason: 'invalid_value', message: 'Value is not allowed or refers to a missing item' }],
    })
  }
  const conversation: AgentConversation = {
    conversation_id: id,
    topic_label: text.replace(/\s+/g, ' ').trim().slice(0, 20),
    origin: 'note',
    note: { note_id: body.note_id, note_revision: note.revision, title: note.title },
    context_selections: [
      {
        selection_id: newIdempotencyKey(),
        note_id: body.note_id,
        note_revision: note.revision,
        start: body.selection.start,
        end: body.selection.end,
        text_preview: text.slice(0, 100),
        revision_changed: false,
      },
    ],
    created_at,
  }
  conversations.set(id, { conversation, turnIds: [] })
  return { status: 201, body: conversation }
}

function log(method: string, path: string): void {
  requests.push({ method, path })
}

export const agentRoutes: Route[] = [
  {
    method: 'POST',
    pattern: /^\/api\/ai\/conversations$/,
    handle: ({ body }) => {
      log('POST', '/api/ai/conversations')
      if (getMockSession() === 'visitor') return loginRequired()
      if (scenario === 'service_unavailable') return unavailable()
      if (noteRevoked) return notFound()
      return createConversation((body ?? {}) as CreateConversationRequest)
    },
  },
  {
    method: 'GET',
    pattern: /^\/api\/ai\/conversations\/([^/]+)$/,
    handle: (_request, [id]) => {
      log('GET', `/api/ai/conversations/${id}`)
      if (getMockSession() === 'visitor') return loginRequired()
      const conversation = conversations.get(decodeURIComponent(id))
      if (!conversation || noteRevoked) return notFound()
      const now = Date.now()
      return {
        status: 200,
        body: { ...conversation.conversation, turns: conversation.turnIds.map((turnId) => payloadOf(turns.get(turnId)!, now)) },
      }
    },
  },
  {
    method: 'GET',
    pattern: /^\/api\/ai\/turns\/([^/]+)$/,
    handle: (_request, [id]) => {
      log('GET', `/api/ai/turns/${id}`)
      if (getMockSession() === 'visitor') return loginRequired()
      const turn = turns.get(decodeURIComponent(id))
      if (!turn || noteRevoked) return notFound()
      const payload = payloadOf(turn)
      return { status: 200, body: payload.status === 'running' ? { ...payload, retry_after_seconds: POLL_SECONDS } : payload }
    },
  },
  {
    method: 'POST',
    pattern: /^\/api\/ai\/turns\/([^/]+)\/cancel$/,
    handle: (_request, [id]) => {
      log('POST', `/api/ai/turns/${id}/cancel`)
      if (getMockSession() === 'visitor') return loginRequired()
      const turn = turns.get(decodeURIComponent(id))
      if (!turn || noteRevoked) return notFound()
      if (statusAt(turn, Date.now()).status !== 'running') {
        return errorBody(409, 'conflict', 'The response has already finished', { detail: 'turn_not_cancellable' })
      }
      turn.cancelledAt = Date.now()
      return { status: 200, body: { turn_id: turn.turn.turn_id, status: 'cancelled', question: turn.turn.question } }
    },
  },
  {
    method: 'GET',
    pattern: /^\/api\/ai\/turns\/([^/]+)\/sources\/([1-9][0-9]{0,2})$/,
    handle: (_request, [id, ref]) => {
      log('GET', `/api/ai/turns/${id}/sources/${ref}`)
      if (getMockSession() === 'visitor') return loginRequired()
      const turn = noteRevoked ? undefined : turns.get(decodeURIComponent(id))
      const payload = turn ? payloadOf(turn) : null
      const result = payload?.status === 'completed' ? payload.result : undefined
      const sources = result && 'sources' in result ? (result.sources ?? []) : []
      const source = sources.find((item) => item.ref === Number(ref))
      if (!source) return notFound()
      return {
        status: 200,
        body: {
          ref: source.ref,
          source_kind: source.source_kind,
          title: source.title,
          section: source.section ?? null,
          cited_revision: source.cited_revision,
          paragraph_text: `${source.excerpt ?? '합성 근거 문단'}입니다. 인용 당시의 합성 문단 원문입니다.`,
          highlight: null,
          changed_since_cited: false,
        },
      }
    },
  },
]
