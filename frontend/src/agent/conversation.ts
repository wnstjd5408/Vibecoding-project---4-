// CS Agent 대화 상태(MEG-255). 화면(T6c·T6d)은 이 상태만 보고 그린다. 서버 호출 규칙을 한곳에 모았다.
//
// 규칙(API spec v0.2 2절·4절 E29·6절, MEG-239 결정 요청 10·14 잠정 적용):
//  - 사용자 동작 하나에 Idempotency-Key 하나다. 진행 중에 같은 동작(ask·retry)을 다시 부르면 새 요청 없이 진행 중인 요청을 돌려준다.
//    처리 여부를 모르는 실패(네트워크·형식 밖 응답)와 서버가 선점을 지운 거절(429)은 retry()가 같은 키로 다시 보낸다.
//    서버가 실패로 끝낸 턴(failed)은 retry()가 E30으로 상태를 먼저 확인하고, 그래도 failed면 새 키로 보낸다(디자인 S8, 결정 41).
//  - 스트림이 끊기거나 마지막 이벤트 없이 끝나면 turn 이벤트로 받은 turn_id를 E30으로 조회한다. running이면 서버가 준
//    retry_after_seconds 뒤에 다시 조회한다. 서버는 연결과 무관하게 턴을 끝까지 실행한다(MEG-229 Q2).
//  - 409 in_progress(같은 키의 턴이 진행 중)는 오류 본문의 turn_id로 이어 본다. 409 turn_in_progress(같은 대화의 다른 턴이
//    진행 중)는 그 턴을 이어 보고 대화에 넣은 뒤, 이번 질문은 보내지 않은 채 failure(turn_in_progress)로 남긴다. 지연이나
//    실패 뒤에 질문을 저절로 다시 보내지 않는다(결정 37).
//  - 429는 retry_after_seconds가 지나기 전에는 retry()가 요청을 보내지 않는다.
//  - 대화는 이 객체가 살아 있는 동안만 메모리에 둔다(결정 요청 10 권장안 잠정 적용). 노트 화면이 useAgentConversation으로
//    만들고, 다른 노트로 가거나 새로 고치면 버린다. 패널을 닫았다 열어도 노트 화면에 있으면 남고, refresh()가 E28로 다시 읽는다.
//
// 화면에 보여 줄 문구는 여기서 정하지 않는다. failure.kind·failure.code와 pending.steps로 화면이 고른다.
import { ApiError, CLIENT_ERROR_CODES, isApiError } from '../api/client.ts'
import { newIdempotencyKey } from '../ai/explain.ts'
import { cancelTurn, createConversation, openTurnStream, readConversation, readTurn } from './api.ts'
import type {
  AgentConversation,
  AgentStep,
  AgentTurn,
  AgentTurnRead,
  AskQuestion,
  AskTurnRequest,
  CreateConversationRequest,
  SourceKind,
  TurnEvent,
} from './types.ts'

export const STEP_ORDER: readonly AgentStep[] = ['understand', 'retrieve', 'compose']

export type StepView = { step: AgentStep; state: 'current' | 'done'; paragraphCount?: number; sourceKind?: SourceKind }

// 진행 중인 사용자 동작 하나.
//  creating: E27로 대화를 만드는 중 / sending: E29 응답을 기다리는 중 / streaming: 이벤트를 받는 중
//  recovering: 스트림이 끊겨 E30으로 이 턴을 조회하는 중 / following: 같은 대화의 다른 턴(409 turn_in_progress)을 조회하는 중
export type PendingPhase = 'creating' | 'sending' | 'streaming' | 'recovering' | 'following'

export type PendingTurn = {
  question: AskQuestion
  phase: PendingPhase
  // 이 턴의 id. turn 이벤트나 409의 turn_id로 안다. following이면 이어 보는 다른 턴의 id다.
  turnId: string | null
  seq: number | null
  steps: StepView[]
  delayed: boolean
  // 중단을 눌렀다. turn_id를 아직 모르면 turn 이벤트를 받는 즉시 E31을 부른다.
  cancelRequested: boolean
  // E31이 응답을 받지 못했다(네트워크 등). 화면은 다시 중단을 누르게 할 수 있다.
  cancelFailed: boolean
}

export type FailureKind =
  | 'failed' // 턴이 failed로 끝났다(ai_unavailable·internal_error·interrupted). S8
  | 'limit_reached' // 429 ai_limit_reached 또는 failed(limit). S12
  | 'rate_limited' // 429 rate_limited. retryAt 전에는 다시 보내지 않는다
  | 'turn_in_progress' // 같은 대화의 다른 턴이 진행 중이었다. 그 턴은 turns에 들어갔고, 이번 질문은 보내지 않았다
  | 'network' // 응답을 받지 못해 처리 여부를 모른다. retry()는 같은 키로 다시 보낸다
  | 'not_found' // 대화·노트·턴을 볼 수 없다(없음·권한 없음·회수를 구분하지 않는다). S9
  | 'stale_revision' // 노트 개정이 바뀌었다
  | 'choice_expired' // 확인 카드의 선택이 더는 유효하지 않다
  | 'turn_not_retryable' // '같은 질문 다시 하기'를 쓸 수 없는 턴이다
  | 'invalid' // 400·422
  | 'service_unavailable' // 503(노출 중단 플래그)
  | 'login_required' // 401
  | 'unexpected' // 그 밖의 응답

export type AgentFailure = {
  kind: FailureKind
  // 서버 code(또는 클라이언트 code). 화면이 문구를 더 나눌 때 쓴다.
  code: string
  // 보내려던 질문. 실패·제한 뒤에도 질문을 남겨 두는 데 쓴다. 질문과 무관한 실패(E28 등)는 null이다.
  question: AskQuestion | null
  // 실패한 턴의 id. 턴이 생기기 전에 거절됐으면 null이다.
  turnId: string | null
  // 이 시각(ms) 전에는 retry()가 요청을 보내지 않는다. 기다릴 필요가 없으면 null이다.
  retryAt: number | null
}

export type AgentState = {
  conversation: AgentConversation | null
  // 받은 턴(오래된 순). completed·cancelled 턴과 E28로 읽은 턴이다. 지금 진행 중인 턴은 pending에 있다.
  turns: AgentTurn[]
  pending: PendingTurn | null
  failure: AgentFailure | null
  // 마지막으로 중단한 질문. '중단한 질문 다시 넣기'에 쓴다(E31 응답의 question).
  cancelled: { turnId: string; question: AgentTurn['question'] } | null
  // E28로 대화를 다시 읽는 중
  refreshing: boolean
}

export type AskOptions = Omit<AskTurnRequest, 'question'> & {
  // 대화가 아직 없으면 이 문맥으로 E27을 먼저 부른다.
  context?: CreateConversationRequest
}

// 한 사용자 동작. 같은 동작을 다시 보낼 때는 같은 key를 쓴다.
type Action = {
  request: AskTurnRequest
  context: CreateConversationRequest | undefined
  key: string
  // 이 동작으로 생긴 턴. failed로 끝난 턴이면 retry()가 E30으로 먼저 확인한다.
  turnId: string | null
  // turnId를 어디서 알았는가. 409 in_progress에서 안 턴이 E30에서 404면 서버가 선점을 지운 것이라 같은 키로 다시 보낸다.
  turnIdFrom: 'event' | 'in_progress' | null
  keyRenewals: number
}

type Run = { action: Action; abort: AbortController; promise: Promise<void> }

// E30 조회 규칙. 서버 권장 간격이 없으면 DEFAULT_POLL_MS다. 연속 실패가 MAX_POLL_ERRORS를 넘거나
// 전체 대기가 MAX_POLL_MS를 넘으면 network 실패로 멈춘다(서버는 실행이 만료되면 failed(interrupted)로 바꾸므로 보통 그 전에 끝난다).
export const POLL_RULES = { DEFAULT_POLL_MS: 2000, MAX_POLL_ERRORS: 3, MAX_POLL_MS: 10 * 60 * 1000 }
// 409 in_progress → E30 404(선점이 지워짐) → 같은 키로 다시 보내기를 몇 번까지 할지
const MAX_RESENDS = 2

class StreamCut extends Error {
  constructor() {
    super('Stream ended before the final event')
    this.name = 'StreamCut'
  }
}

class Stopped extends Error {
  constructor() {
    super('Stopped')
    this.name = 'Stopped'
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new Stopped())
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    const onAbort = () => {
      clearTimeout(timer)
      reject(new Stopped())
    }
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

function failureOf(error: ApiError, question: AskQuestion | null, turnId: string | null): AgentFailure {
  const base = { code: error.code, question, turnId, retryAt: null }
  if (error.code === 'rate_limited') {
    const seconds = error.retryAfterSeconds
    return { ...base, kind: 'rate_limited', retryAt: seconds && seconds > 0 ? Date.now() + seconds * 1000 : null }
  }
  if (error.code === 'ai_limit_reached') return { ...base, kind: 'limit_reached' }
  if (error.code === 'not_found') return { ...base, kind: 'not_found' }
  if (error.code === 'login_required') return { ...base, kind: 'login_required' }
  if (error.code === 'service_unavailable') return { ...base, kind: 'service_unavailable' }
  if (error.code === 'validation_failed' || error.code === 'bad_request') return { ...base, kind: 'invalid' }
  if (error.code === 'conflict' && error.detail === 'stale_revision') return { ...base, kind: 'stale_revision', code: error.detail }
  if (error.code === 'conflict' && error.detail === 'choice_expired') return { ...base, kind: 'choice_expired', code: error.detail }
  if (error.code === 'conflict' && error.detail === 'turn_not_retryable') return { ...base, kind: 'turn_not_retryable', code: error.detail }
  if (error.code === CLIENT_ERROR_CODES.networkError) return { ...base, kind: 'network' }
  if (error.code === 'ai_unavailable' || error.code === 'internal_error') return { ...base, kind: 'failed' }
  return { ...base, kind: 'unexpected' }
}

// 다시 보내도 같은 결과가 나오는 실패는 retry()가 요청을 보내지 않는다.
const FINAL_KINDS: ReadonlySet<FailureKind> = new Set([
  'not_found',
  'stale_revision',
  'choice_expired',
  'turn_not_retryable',
  'invalid',
  'service_unavailable',
  'login_required',
])

export function canRetry(failure: AgentFailure | null, now: number = Date.now()): boolean {
  if (failure === null || failure.question === null || FINAL_KINDS.has(failure.kind)) return false
  return failure.retryAt === null || failure.retryAt <= now
}

// E30의 지금 단계(step)로 단계 표시를 만든다. 앞 단계는 끝난 것으로 보고, 앞서 받은 문단 수는 남긴다.
function stepsAt(previous: StepView[], current: AgentStep | undefined): StepView[] {
  if (current === undefined) return previous
  const index = STEP_ORDER.indexOf(current)
  return STEP_ORDER.slice(0, index + 1).map((step, at) => {
    const known = previous.find((view) => view.step === step)
    return { ...known, step, state: at < index ? 'done' : (known?.state ?? 'current') }
  })
}

function withStep(steps: StepView[], data: Extract<TurnEvent, { type: 'step' }>['data']): StepView[] {
  const view: StepView = { step: data.step, state: data.state }
  if (data.paragraph_count !== undefined) view.paragraphCount = data.paragraph_count
  if (data.source_kind !== undefined) view.sourceKind = data.source_kind
  const at = steps.findIndex((item) => item.step === data.step)
  if (at < 0) return [...steps, view]
  return steps.map((item, index) => (index === at ? { ...item, ...view } : item))
}

function mergeTurn(turns: AgentTurn[], turn: AgentTurn): AgentTurn[] {
  const rest = turns.filter((item) => item.turn_id !== turn.turn_id)
  return [...rest, turn].sort((a, b) => a.seq - b.seq)
}

const INITIAL: AgentState = { conversation: null, turns: [], pending: null, failure: null, cancelled: null, refreshing: false }

export class AgentConversationController {
  private state: AgentState = INITIAL
  private listeners = new Set<() => void>()
  private run: Run | null = null
  // 마지막으로 실패한 동작. retry()가 이어서 쓴다.
  private failedAction: Action | null = null
  private refreshAbort: AbortController | null = null

  // useSyncExternalStore에 넘길 수 있게 화살표 함수로 둔다.
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  getSnapshot = (): AgentState => this.state

  private set(patch: Partial<AgentState>): void {
    this.state = { ...this.state, ...patch }
    for (const listener of this.listeners) listener()
  }

  private setPending(run: Run, patch: Partial<PendingTurn>): void {
    if (this.run !== run || this.state.pending === null) return
    this.set({ pending: { ...this.state.pending, ...patch } })
  }

  // 질문하기(W2·W4). 대화가 없으면 options.context로 E27을 먼저 부른다.
  // 진행 중인 동작이 있으면 새로 보내지 않고 그 동작의 promise를 돌려준다(같은 동작을 두 번 눌러도 키는 하나).
  ask(question: AskQuestion, options: AskOptions = {}): Promise<void> {
    if (this.run) return this.run.promise
    const { context, ...rest } = options
    if (this.state.conversation === null && context === undefined) {
      return Promise.reject(new Error('A conversation context is required for the first question'))
    }
    const action: Action = {
      request: { question, ...rest },
      context,
      key: newIdempotencyKey(),
      turnId: null,
      turnIdFrom: null,
      keyRenewals: 0,
    }
    return this.start(action)
  }

  // 실패한 동작을 다시 보낸다(S8 '다시 시도', 네트워크 실패, 429 대기 뒤).
  //  - 턴이 failed로 끝났으면 E30으로 그 턴을 먼저 확인한다. 끝난 결과가 있으면 보여 주고, failed면 새 키로 보낸다.
  //  - 처리 여부를 모르거나 서버가 선점을 지운 경우(429·네트워크)는 같은 키로 보낸다.
  //  - retryAt 전이거나 다시 보내도 같은 결과인 실패면 아무것도 하지 않는다.
  retry(): Promise<void> {
    if (this.run) return this.run.promise
    const failure = this.state.failure
    const action = this.failedAction
    if (!action || !canRetry(failure)) return Promise.resolve()
    return this.start(action, failure?.turnId != null ? 'check' : 'send')
  }

  // 실패 표시만 지운다. 사용 제한(S12)의 '다시 확인'처럼 서버를 부르지 않고 보내기 잠금을 풀 때 쓴다(결정 요청 12 권장안).
  dismissFailure(): void {
    if (this.state.failure !== null) this.set({ failure: null })
  }

  // 응답 중단(E31). turn_id를 아직 모르면 turn 이벤트를 받는 즉시 부른다.
  async cancel(): Promise<void> {
    const run = this.run
    const pending = this.state.pending
    if (!run || !pending) return
    if (pending.phase === 'creating') {
      // 아직 턴이 없다. E27만 멈추고 끝낸다.
      this.finishRun(run, {})
      run.abort.abort()
      return
    }
    this.setPending(run, { cancelRequested: true, cancelFailed: false })
    if (pending.turnId !== null) await this.sendCancel(run, pending.turnId)
  }

  private async sendCancel(run: Run, turnId: string): Promise<void> {
    let response
    try {
      response = await cancelTurn(turnId)
    } catch (error) {
      if (this.run !== run) return
      if (isApiError(error, 'conflict', 'turn_not_cancellable')) {
        // 이미 끝났다. 스트림이나 E30 조회가 결과를 받는다.
        this.setPending(run, { cancelRequested: false })
        return
      }
      this.setPending(run, { cancelRequested: false, cancelFailed: true })
      return
    }
    if (this.run !== run) return
    // 받다 만 답변은 보여 주지 않는다. 스트림·조회를 멈추고 E30으로 중단된 턴을 받아 넣는다.
    run.abort.abort()
    let turn: AgentTurn | null = null
    try {
      turn = await readTurn(turnId)
    } catch {
      turn = null
    }
    const pending = this.state.pending
    const stored: AgentTurn = turn ?? {
      turn_id: turnId,
      seq: pending?.seq ?? Number.MAX_SAFE_INTEGER,
      question: response.question,
      status: 'cancelled',
      created_at: new Date().toISOString(),
    }
    this.finishRun(run, {
      turns: mergeTurn(this.state.turns, stored),
      cancelled: { turnId, question: response.question },
    })
  }

  // 대화를 E28로 다시 읽는다('이전 대화 보기', 출처 화면에서 돌아올 때). 진행 중인 동작이 있으면 읽지 않는다.
  async refresh(): Promise<void> {
    const conversation = this.state.conversation
    if (conversation === null || this.run || this.refreshAbort) return
    const abort = new AbortController()
    this.refreshAbort = abort
    this.set({ refreshing: true })
    try {
      const { turns, ...rest } = await readConversation(conversation.conversation_id, abort.signal)
      if (this.refreshAbort !== abort) return
      this.set({ conversation: rest, turns: [...turns].sort((a, b) => a.seq - b.seq), refreshing: false })
    } catch (error) {
      if (this.refreshAbort !== abort) return
      const failure = isApiError(error) ? failureOf(error, null, null) : failureOf(networkError(), null, null)
      this.set({ refreshing: false, failure })
    } finally {
      if (this.refreshAbort === abort) this.refreshAbort = null
    }
  }

  // 새 대화(헤더의 '새 대화', 주제 전환의 '새 대화로 질문'). 진행 중에는 열지 않는다(결정 요청 11 권장안: 생성 중에는 잠근다).
  // 대화를 만들기만 하고 질문은 보내지 않는다. 바로 질문하려면 reset() 뒤 ask(question, { context })를 쓴다.
  async newConversation(context: CreateConversationRequest): Promise<boolean> {
    if (this.run) return false
    this.reset()
    const abort = new AbortController()
    this.refreshAbort = abort
    this.set({ refreshing: true })
    try {
      const conversation = await createConversation(context, abort.signal)
      if (this.refreshAbort !== abort) return false
      this.set({ conversation, turns: [], refreshing: false })
      return true
    } catch (error) {
      if (this.refreshAbort !== abort) return false
      const failure = isApiError(error) ? failureOf(error, null, null) : failureOf(networkError(), null, null)
      this.set({ refreshing: false, failure })
      return false
    } finally {
      if (this.refreshAbort === abort) this.refreshAbort = null
    }
  }

  // 대화를 비운다. 진행 중인 요청의 응답은 버린다(서버 실행은 끝까지 간다).
  reset(): void {
    this.abort()
    this.failedAction = null
    this.set(INITIAL)
  }

  // 화면을 떠날 때 부른다. 진행 중인 읽기만 멈추고 대화는 남긴다(StrictMode의 두 번 마운트에도 안전하다).
  abort(): void {
    const run = this.run
    if (run) {
      this.run = null
      run.abort.abort()
      if (this.state.pending !== null) this.set({ pending: null })
    }
    if (this.refreshAbort) {
      this.refreshAbort.abort()
      this.refreshAbort = null
      if (this.state.refreshing) this.set({ refreshing: false })
    }
  }

  // --- 실행 ---

  private start(action: Action, mode: 'send' | 'check' = 'send'): Promise<void> {
    const abort = new AbortController()
    const run: Run = { action, abort, promise: Promise.resolve() }
    // 진행 중인 E28 다시 읽기는 멈춘다. 늦게 온 목록이 이번 턴을 덮어쓰지 않게 하기 위해서다.
    if (this.refreshAbort) {
      this.refreshAbort.abort()
      this.refreshAbort = null
    }
    this.run = run
    this.failedAction = null
    this.set({
      refreshing: false,
      failure: null,
      cancelled: null,
      pending: {
        question: action.request.question,
        phase: this.state.conversation === null ? 'creating' : 'sending',
        turnId: mode === 'check' ? action.turnId : null,
        seq: null,
        steps: [],
        delayed: false,
        cancelRequested: false,
        cancelFailed: false,
      },
    })
    run.promise = this.execute(run, mode).catch((error: unknown) => {
      // 여기까지 온 오류는 예상하지 못한 것이다. 화면이 멈추지 않게 실패로 남긴다.
      if (this.run === run && !(error instanceof Stopped)) this.fail(run, failureOf(unexpected(), action.request.question, action.turnId))
    })
    return run.promise
  }

  private finishRun(run: Run, patch: Partial<AgentState>): void {
    if (this.run !== run) return
    this.run = null
    this.set({ ...patch, pending: null })
  }

  private fail(run: Run, failure: AgentFailure): void {
    if (this.run !== run) return
    this.failedAction = run.action
    this.finishRun(run, { failure })
  }

  private async execute(run: Run, mode: 'send' | 'check'): Promise<void> {
    const { action } = run
    if (mode === 'check' && action.turnId !== null) {
      // 실패 화면의 '다시 시도': 기존 턴의 상태를 먼저 확인한다(S8 "기존 요청 상태 확인 후 중복 방지").
      const outcome = await this.poll(run, action.turnId, 'recovering')
      if (outcome.kind === 'turn' && outcome.turn.status === 'failed') {
        // 실패가 확인됐다. 새 키로 다시 보낸다(디자인 S8, 결정 41).
        action.key = newIdempotencyKey()
        action.turnId = null
        action.turnIdFrom = null
        this.setPending(run, { turnId: null, phase: 'sending', steps: [], delayed: false })
      } else if (this.afterPoll(run, outcome, action.turnId ?? '') === 'done') {
        return
      } else {
        this.setPending(run, { turnId: null, phase: 'sending', steps: [], delayed: false })
      }
    }
    for (let resends = 0; ; resends += 1) {
      const outcome = await this.send(run)
      if (outcome !== 'resend') return
      if (resends >= MAX_RESENDS) {
        return this.fail(run, failureOf(networkError(), action.request.question, null))
      }
      this.setPending(run, { turnId: null, phase: 'sending', steps: [], delayed: false })
    }
  }

  // E29를 한 번 보낸다. 'resend'면 같은 키(또는 새 키)로 한 번 더 보내야 한다.
  private async send(run: Run): Promise<'done' | 'resend'> {
    const { action, abort } = run
    const question = action.request.question
    let conversation = this.state.conversation
    try {
      if (conversation === null) {
        if (action.context === undefined) throw new Error('A conversation context is required')
        this.setPending(run, { phase: 'creating' })
        conversation = await createConversation(action.context, abort.signal)
        if (this.run !== run) return 'done'
        this.set({ conversation, turns: [] })
      }
      this.setPending(run, { phase: 'sending' })
      const events = await openTurnStream(conversation.conversation_id, action.request, action.key, abort.signal)
      this.setPending(run, { phase: 'streaming' })
      for await (const event of events) {
        if (this.run !== run) return 'done'
        const finished = this.onEvent(run, event)
        if (finished) return 'done'
      }
      throw new StreamCut()
    } catch (error) {
      if (abort.signal.aborted || this.run !== run) return 'done'
      if (!(error instanceof ApiError)) {
        // 읽는 중에 끊겼거나(TypeError 등), 마지막 이벤트 없이 끝났거나, 이벤트 형식이 틀렸다.
        return this.recover(run)
      }
      return this.rejected(run, error, question)
    }
  }

  // 스트림 이벤트 하나를 상태에 반영한다. 마지막 이벤트(result·error)면 true다.
  private onEvent(run: Run, event: TurnEvent): boolean {
    const pending = this.state.pending
    if (pending === null) return true
    switch (event.type) {
      case 'turn':
        run.action.turnId = event.data.turn_id
        run.action.turnIdFrom = 'event'
        this.setPending(run, { turnId: event.data.turn_id, seq: event.data.seq })
        if (pending.cancelRequested) void this.sendCancel(run, event.data.turn_id)
        return false
      case 'step':
        this.setPending(run, { steps: withStep(pending.steps, event.data) })
        return false
      case 'delayed':
        this.setPending(run, { delayed: true })
        return false
      case 'result':
        this.settle(run, event.data)
        return true
      case 'error': {
        const error = new ApiError(0, event.data)
        this.fail(run, failureOf(error, run.action.request.question, run.action.turnId ?? pending.turnId))
        return true
      }
    }
  }

  // 끝난 턴을 받았다. completed·cancelled는 대화에 넣고, failed는 실패로 남긴다.
  private settle(run: Run, turn: AgentTurn): void {
    run.action.turnId = turn.turn_id
    if (turn.status === 'failed') {
      const code = turn.failure === 'limit' ? 'ai_limit_reached' : turn.failure === 'interrupted' ? 'internal_error' : 'ai_unavailable'
      this.fail(run, {
        kind: turn.failure === 'limit' ? 'limit_reached' : 'failed',
        code,
        question: run.action.request.question,
        turnId: turn.turn_id,
        retryAt: null,
      })
      return
    }
    const patch: Partial<AgentState> = { turns: mergeTurn(this.state.turns, turn) }
    if (turn.status === 'cancelled') patch.cancelled = { turnId: turn.turn_id, question: turn.question }
    this.finishRun(run, patch)
  }

  // 스트림이 끊긴 뒤. turn_id를 알면 E30으로 받는다. 모르면 처리 여부를 모르므로 실패로 남기고 retry()가 같은 키로 보낸다.
  private async recover(run: Run): Promise<'done' | 'resend'> {
    const turnId = run.action.turnId
    if (turnId === null) {
      this.fail(run, failureOf(networkError(), run.action.request.question, null))
      return 'done'
    }
    const outcome = await this.poll(run, turnId, 'recovering')
    return this.afterPoll(run, outcome, turnId)
  }

  private afterPoll(run: Run, outcome: PollOutcome, turnId: string): 'done' | 'resend' {
    if (outcome.kind === 'resend') return 'resend'
    if (outcome.kind === 'turn') this.settle(run, outcome.turn)
    if (outcome.kind === 'error') {
      // 404는 턴이나 노트를 볼 수 없게 된 것이다(S9). 그 밖에는 처리 여부를 확인하지 못한 것이라 retry()가 E30부터 다시 본다.
      const failure = failureOf(outcome.error, run.action.request.question, turnId)
      this.fail(run, failure.kind === 'not_found' ? failure : { ...failure, kind: 'network' })
    }
    return 'done'
  }

  // 스트림이 열리기 전의 거절
  private async rejected(run: Run, error: ApiError, question: AskQuestion): Promise<'done' | 'resend'> {
    const { action } = run
    if (isApiError(error, 'conflict', 'in_progress') && error.turnId) {
      // 같은 키의 턴이 진행 중이다(앞서 보낸 요청이 서버에 닿았다). 그 턴을 이어 본다.
      action.turnId = error.turnId
      action.turnIdFrom = 'in_progress'
      this.setPending(run, { turnId: error.turnId })
      return this.recover(run)
    }
    if (isApiError(error, 'conflict', 'turn_in_progress') && error.turnId) {
      // 같은 대화에 다른 턴이 진행 중이다. 그 턴을 이어 보고, 끝난 결과가 있으면 대화에 넣는다.
      // 이번 질문은 보내지 않고 실패(turn_in_progress)로 남긴다. 질문은 failure.question에 남고 retry()가 같은 키로 보낸다.
      this.setPending(run, { steps: [], delayed: false })
      const other = await this.poll(run, error.turnId, 'following')
      if (other.kind === 'stopped' || this.run !== run) return 'done'
      if (other.kind === 'turn' && other.turn.status !== 'failed') this.set({ turns: mergeTurn(this.state.turns, other.turn) })
      this.fail(run, { kind: 'turn_in_progress', code: 'turn_in_progress', question, turnId: null, retryAt: null })
      return 'done'
    }
    if (isApiError(error, 'conflict', 'idempotency_key_reused') && action.keyRenewals < 1) {
      // 같은 사용자가 다른 대화에서 쓴 키다. 새 키로 한 번 더 보낸다(spec 2.1).
      action.key = newIdempotencyKey()
      action.keyRenewals += 1
      return 'resend'
    }
    // 그 밖의 거절. 다시 보내도 같은 결과인 실패(FINAL_KINDS)는 retry()가 보내지 않으므로 다음 질문은 새 동작(새 키)이 된다.
    this.fail(run, failureOf(error, question, null))
    return 'done'
  }

  // E30으로 턴이 끝날 때까지 조회한다. 실패 처리는 부른 쪽이 정한다.
  //  turn: 끝난 턴 / resend: 409 in_progress로 안 턴이 사라졌다(서버가 429로 선점을 지웠다, spec E29 3단계). 같은 키로 다시 보낸다
  //  error: 더 조회해도 소용없다 / stopped: 중단·화면 이탈로 멈췄다
  private async poll(run: Run, turnId: string, phase: 'recovering' | 'following'): Promise<PollOutcome> {
    const { action, abort } = run
    const startedAt = Date.now()
    let errors = 0
    this.setPending(run, { phase, turnId })
    for (;;) {
      if (Date.now() - startedAt > POLL_RULES.MAX_POLL_MS) return { kind: 'error', error: networkError() }
      let turn: AgentTurnRead
      try {
        turn = await readTurn(turnId, abort.signal)
      } catch (error) {
        if (abort.signal.aborted || this.run !== run) return { kind: 'stopped' }
        if (!(error instanceof ApiError)) return { kind: 'error', error: unexpected() }
        if (error.code === 'not_found' && phase === 'recovering' && action.turnIdFrom === 'in_progress') {
          action.turnId = null
          action.turnIdFrom = null
          return { kind: 'resend' }
        }
        if (error.code === 'rate_limited') {
          const seconds = error.retryAfterSeconds
          await this.wait(run, seconds !== undefined && seconds > 0 ? seconds * 1000 : POLL_RULES.DEFAULT_POLL_MS)
          continue
        }
        if (!isTransient(error)) return { kind: 'error', error }
        errors += 1
        if (errors > POLL_RULES.MAX_POLL_ERRORS) return { kind: 'error', error: networkError() }
        await this.wait(run, POLL_RULES.DEFAULT_POLL_MS)
        continue
      }
      if (this.run !== run) return { kind: 'stopped' }
      errors = 0
      if (turn.status !== 'running') {
        const { retry_after_seconds: _poll, ...finished } = turn
        void _poll
        return { kind: 'turn', turn: finished }
      }
      const pending = this.state.pending
      if (pending) this.setPending(run, { steps: stepsAt(pending.steps, turn.step) })
      const seconds = turn.retry_after_seconds
      await this.wait(run, seconds !== undefined && seconds > 0 ? seconds * 1000 : POLL_RULES.DEFAULT_POLL_MS)
    }
  }

  private async wait(run: Run, ms: number): Promise<void> {
    await sleep(ms, run.abort.signal)
  }
}

type PollOutcome =
  | { kind: 'turn'; turn: AgentTurn }
  | { kind: 'resend' }
  | { kind: 'error'; error: ApiError }
  | { kind: 'stopped' }

// 다시 조회하면 나아질 수 있는 오류(네트워크·형식 밖 응답·5xx)
function isTransient(error: ApiError): boolean {
  return error.code === CLIENT_ERROR_CODES.networkError || error.code === CLIENT_ERROR_CODES.unexpectedResponse || error.status >= 500
}

function networkError(): ApiError {
  return new ApiError(0, { code: CLIENT_ERROR_CODES.networkError, message: 'Network request failed', request_id: '' })
}

function unexpected(): ApiError {
  return new ApiError(0, { code: CLIENT_ERROR_CODES.unexpectedResponse, message: 'Unexpected response', request_id: '' })
}
