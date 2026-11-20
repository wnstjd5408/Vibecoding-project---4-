import { expect, test } from '@playwright/test'
import type { Page, Request, Route } from '@playwright/test'

// MEG-255 CS Agent API 클라이언트의 실제 fetch 경로. playwright.notes.config.ts가 VITE_API_MOCK=false로 서버를 띄우므로
// 브라우저가 실제로 보내는 요청(헤더·본문)과, 합성 HTTP 응답(SSE 본문, 끊긴 응답, 409·429·503)을 받은 뒤의 대화 상태를 시험한다.
// 응답은 모두 합성이다. 실제 백엔드로 하는 끊김 E2E는 T7(MEG-240) 범위다.

const CONVERSATION_ID = '11111111-1111-4111-8111-111111111111'
const TURN_ID = '22222222-2222-4222-8222-222222222222'
const NOTE_CONTEXT = { origin: 'note', note_id: 11, note_revision: 3, selection: { start: 0, end: 10 } }
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

const conversation = {
  conversation_id: CONVERSATION_ID,
  topic_label: '합성 주제',
  origin: 'note',
  note: { note_id: 11, note_revision: 3, title: '합성 노트' },
  context_selections: [],
  created_at: '2026-11-20T00:00:00Z',
}

const question = { kind: 'free', text: '합성 질문' }
const runningTurn = { turn_id: TURN_ID, seq: 1, question, status: 'running', created_at: '2026-11-20T00:00:01Z', step: 'compose', retry_after_seconds: 1 }
const completedTurn = {
  turn_id: TURN_ID,
  seq: 1,
  question,
  status: 'completed',
  created_at: '2026-11-20T00:00:01Z',
  finished_at: '2026-11-20T00:00:09Z',
  result: { state: 'answered', sections: [{ heading: '핵심', body: '합성 답변 [1]' }], sources: [{ ref: 1, source_kind: 'note', title: '합성 노트', cited_revision: 3 }], suggestions: [] },
}

function sseBody(events: [string, unknown][], lineEnd = '\n'): string {
  return events.map(([event, data]) => `event: ${event}${lineEnd}data: ${JSON.stringify(data)}${lineEnd}${lineEnd}`).join(`: keep-alive${lineEnd}${lineEnd}`)
}

const turnEvent: [string, unknown] = ['turn', { turn_id: TURN_ID, seq: 1 }]
const stepEvents: [string, unknown][] = [
  ['step', { step: 'understand', state: 'current' }],
  ['step', { step: 'understand', state: 'done' }],
  ['step', { step: 'retrieve', state: 'current' }],
  ['step', { step: 'retrieve', state: 'done', paragraph_count: 2, source_kind: 'note' }],
]

function fulfillSse(route: Route, body: string) {
  return route.fulfill({ status: 200, headers: { 'Content-Type': 'text/event-stream; charset=utf-8' }, body })
}

function apiError(route: Route, status: number, error: Record<string, unknown>, headers: Record<string, string> = {}) {
  return route.fulfill({ status, headers, json: { error: { message: 'synthetic', request_id: 'r-synthetic', ...error } } })
}

/* eslint-disable @typescript-eslint/no-explicit-any */
async function setup(page: Page) {
  // 등록한 순서의 반대로 먼저 맞춰 본다. 아래 시험의 경로가 이 기본 404보다 앞선다.
  // '**/api/**'는 개발 서버의 /src/api/*.ts 모듈까지 가로채므로 경로가 /api/로 시작하는 요청만 맞춘다.
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => apiError(route, 404, { code: 'not_found' }))
  await page.route('**/api/ai/conversations', (route) => route.fulfill({ status: 201, json: conversation }))
  await page.goto('/dev/mockup')
  await page.evaluate(async () => {
    const w = window as any
    w.agent = await import(/* @vite-ignore */ '/src/agent/conversation.ts' as string)
    w.controller = new w.agent.AgentConversationController()
  })
}

const e29 = `**/api/ai/conversations/${CONVERSATION_ID}/turns`
const e30 = `**/api/ai/turns/${TURN_ID}`

test('E29 요청 헤더와 본문, CRLF로 끝나는 SSE 응답을 받아 답변 턴을 넣는다', async ({ page }) => {
  await setup(page)
  const requests: Request[] = []
  await page.route(e29, (route) => {
    requests.push(route.request())
    return fulfillSse(route, sseBody([turnEvent, ...stepEvents, ['result', completedTurn]], '\r\n'))
  })
  const state = await page.evaluate(async (context) => {
    const w = window as any
    await w.controller.ask({ kind: 'free', text: '합성 질문' }, { context })
    return w.controller.getSnapshot()
  }, NOTE_CONTEXT)
  expect(requests).toHaveLength(1)
  const headers = requests[0].headers()
  expect(headers['accept']).toBe('text/event-stream')
  expect(headers['content-type']).toBe('application/json')
  expect(headers['idempotency-key']).toMatch(UUID)
  expect(requests[0].method()).toBe('POST')
  expect(requests[0].postDataJSON()).toEqual({ question: { kind: 'free', text: '합성 질문' } })
  expect(state.failure).toBeNull()
  expect(state.turns).toEqual([completedTurn])
})

test('AC-2 마지막 이벤트 없이 끝난 응답 뒤 E30을 retry_after_seconds 간격으로 불러 결과를 받는다', async ({ page }) => {
  await setup(page)
  await page.route(e29, (route) => fulfillSse(route, sseBody([turnEvent, ...stepEvents])))
  const e30Calls: number[] = []
  await page.route(e30, (route) => {
    e30Calls.push(Date.now())
    return route.fulfill({ json: e30Calls.length === 1 ? runningTurn : completedTurn })
  })
  const state = await page.evaluate(async (context) => {
    const w = window as any
    await w.controller.ask({ kind: 'free', text: '합성 질문' }, { context })
    return w.controller.getSnapshot()
  }, NOTE_CONTEXT)
  expect(e30Calls).toHaveLength(2)
  expect(e30Calls[1] - e30Calls[0]).toBeGreaterThanOrEqual(950)
  expect(state.failure).toBeNull()
  expect(state.turns).toEqual([completedTurn])
})

test('AC-3 응답을 못 받은 질문은 같은 키로 다시 보내고, 409 in_progress의 turn_id로 이어 본다', async ({ page }) => {
  await setup(page)
  const keys: string[] = []
  await page.route(e29, (route) => {
    keys.push(route.request().headers()['idempotency-key'])
    if (keys.length === 1) return route.abort('failed')
    return apiError(route, 409, { code: 'conflict', detail: 'in_progress', retry_after_seconds: 1, turn_id: TURN_ID }, { 'Retry-After': '1' })
  })
  await page.route(e30, (route) => route.fulfill({ json: completedTurn }))
  const result = await page.evaluate(async (context) => {
    const w = window as any
    await w.controller.ask({ kind: 'free', text: '합성 질문' }, { context })
    const failed = w.controller.getSnapshot().failure
    await w.controller.retry()
    return { failed, state: w.controller.getSnapshot() }
  }, NOTE_CONTEXT)
  expect(result.failed).toMatchObject({ kind: 'network', code: 'network_error', turnId: null })
  expect(keys).toHaveLength(2)
  expect(keys[1]).toBe(keys[0])
  expect(result.state.failure).toBeNull()
  expect(result.state.turns).toEqual([completedTurn])
})

test('E31 턴 id를 받기 전에 중단을 누르면 turn 이벤트를 받는 즉시 중단한다', async ({ page }) => {
  await setup(page)
  let release!: () => void
  const gate = new Promise<void>((resolve) => (release = resolve))
  let arrived!: () => void
  const received = new Promise<void>((resolve) => (arrived = resolve))
  await page.route(e29, async (route) => {
    arrived()
    await gate
    return fulfillSse(route, sseBody([turnEvent, stepEvents[0]]))
  })
  const cancelCalls: string[] = []
  await page.route(`${e30}/cancel`, (route) => {
    cancelCalls.push(route.request().method())
    return route.fulfill({ json: { turn_id: TURN_ID, status: 'cancelled', question } })
  })
  const cancelledTurn = { turn_id: TURN_ID, seq: 1, question, status: 'cancelled', created_at: '2026-11-20T00:00:01Z', finished_at: '2026-11-20T00:00:02Z' }
  await page.route(e30, (route) => route.fulfill({ json: cancelledTurn }))
  await page.evaluate((context) => {
    const w = window as any
    w.asked = w.controller.ask({ kind: 'free', text: '합성 질문' }, { context })
  }, NOTE_CONTEXT)
  await received
  const atCancel = await page.evaluate(async () => {
    const w = window as any
    await w.controller.cancel()
    return w.controller.getSnapshot().pending
  })
  release()
  const state = await page.evaluate(async () => {
    const w = window as any
    await w.asked
    // 중단은 바로 끝나고, 서버의 턴 기록(finished_at 포함)은 E30으로 뒤따라 바뀐다.
    for (let i = 0; i < 300 && !w.controller.getSnapshot().turns[0]?.finished_at; i += 1) await new Promise((resolve) => setTimeout(resolve, 10))
    return w.controller.getSnapshot()
  })
  expect(atCancel).toMatchObject({ phase: 'sending', turnId: null, cancelRequested: true })
  expect(cancelCalls).toEqual(['POST'])
  expect(state.cancelled).toEqual({ turnId: TURN_ID, question })
  expect(state.turns).toEqual([cancelledTurn])
  expect(state.failure).toBeNull()
})

// 아래 넷은 코드 리뷰 지적을 재현한 시험이다(중단 요청이 사라지는 경우, 중단 직후 질문, 대화 다시 읽기 실패).
function gated() {
  let release!: () => void
  const gate = new Promise<void>((resolve) => (release = resolve))
  let arrived!: () => void
  const received = new Promise<void>((resolve) => (arrived = resolve))
  return { gate, release, received, arrived }
}

test('턴 id를 받기 전에 누른 중단은 409 in_progress로 turn_id를 알게 돼도 보낸다', async ({ page }) => {
  await setup(page)
  const e29Gate = gated()
  await page.route(e29, async (route) => {
    e29Gate.arrived()
    await e29Gate.gate
    return apiError(route, 409, { code: 'conflict', detail: 'in_progress', retry_after_seconds: 1, turn_id: TURN_ID }, { 'Retry-After': '1' })
  })
  const cancelCalls: string[] = []
  await page.route(`${e30}/cancel`, (route) => {
    cancelCalls.push(route.request().method())
    return route.fulfill({ json: { turn_id: TURN_ID, status: 'cancelled', question } })
  })
  const cancelledTurn = { turn_id: TURN_ID, seq: 1, question, status: 'cancelled', created_at: '2026-11-20T00:00:01Z' }
  await page.route(e30, (route) => route.fulfill({ json: cancelCalls.length ? cancelledTurn : runningTurn }))
  await page.evaluate((context) => {
    const w = window as any
    w.asked = w.controller.ask({ kind: 'free', text: '합성 질문' }, { context })
  }, NOTE_CONTEXT)
  await e29Gate.received
  await page.evaluate(() => (window as any).controller.cancel())
  e29Gate.release()
  const state = await page.evaluate(async () => {
    const w = window as any
    await w.asked
    for (let i = 0; i < 300 && w.controller.getSnapshot().pending; i += 1) await new Promise((resolve) => setTimeout(resolve, 10))
    return w.controller.getSnapshot()
  })
  expect(cancelCalls).toEqual(['POST'])
  expect(state.pending).toBeNull()
  expect(state.cancelled).toEqual({ turnId: TURN_ID, question })
})

test('중단이 끝나자마자 보낸 질문은 기다리지 않고 바로 보낸다', async ({ page }) => {
  await setup(page)
  let e29Calls = 0
  await page.route(e29, (route) => {
    e29Calls += 1
    if (e29Calls === 1) return fulfillSse(route, sseBody([turnEvent, stepEvents[0]]) + ': keep-alive\n\n'.repeat(1))
    const second = { ...completedTurn, turn_id: '33333333-3333-4333-8333-333333333333', seq: 2 }
    return fulfillSse(route, sseBody([['turn', { turn_id: second.turn_id, seq: 2 }], ['result', second]]))
  })
  await page.route(`${e30}/cancel`, (route) => route.fulfill({ json: { turn_id: TURN_ID, status: 'cancelled', question } }))
  // 중단 뒤 턴을 다시 읽는 E30을 늦게 돌려준다. 그동안 보낸 새 질문이 막히지 않아야 한다.
  const e30Gate = gated()
  await page.route(e30, async (route) => {
    e30Gate.arrived()
    await e30Gate.gate
    return route.fulfill({ json: { turn_id: TURN_ID, seq: 1, question, status: 'cancelled', created_at: '2026-11-20T00:00:01Z' } })
  })
  const result = await page.evaluate(async (context) => {
    const w = window as any
    const asked = w.controller.ask({ kind: 'free', text: '합성 질문' }, { context })
    while (!w.controller.getSnapshot().pending?.turnId) await new Promise((resolve) => setTimeout(resolve, 10))
    await w.controller.cancel()
    await asked
    const afterCancel = w.controller.getSnapshot()
    w.second = w.controller.ask({ kind: 'free', text: '이어서 보낸 질문' })
    return { afterCancel }
  }, NOTE_CONTEXT)
  await page.waitForTimeout(300)
  const callsBeforeRelease = e29Calls
  e30Gate.release()
  const state = await page.evaluate(async () => {
    const w = window as any
    await w.second
    for (let i = 0; i < 300 && w.controller.getSnapshot().pending; i += 1) await new Promise((resolve) => setTimeout(resolve, 10))
    return w.controller.getSnapshot()
  })
  expect(result.afterCancel.pending).toBeNull()
  expect(result.afterCancel.cancelled).toEqual({ turnId: TURN_ID, question })
  expect(callsBeforeRelease).toBe(2)
  expect(state.turns.map((turn: any) => turn.status)).toEqual(['cancelled', 'completed'])
})

test('다시 시도의 E30 확인 중에 누른 중단은 실패한 이전 턴에 E31을 보내지 않고, 새 질문도 보내지 않는다', async ({ page }) => {
  await setup(page)
  let e29Calls = 0
  await page.route(e29, (route) => {
    e29Calls += 1
    return fulfillSse(route, sseBody([turnEvent, ['error', { error: { code: 'ai_unavailable', message: 'm', request_id: 'r' } }]]))
  })
  const cancelCalls: string[] = []
  await page.route(`${e30}/cancel`, (route) => {
    cancelCalls.push(route.request().method())
    return apiError(route, 409, { code: 'conflict', detail: 'turn_not_cancellable' })
  })
  const e30Gate = gated()
  await page.route(e30, async (route) => {
    e30Gate.arrived()
    await e30Gate.gate
    return route.fulfill({ json: { turn_id: TURN_ID, seq: 1, question, status: 'failed', failure: 'error', created_at: '2026-11-20T00:00:01Z' } })
  })
  await page.evaluate(async (context) => {
    const w = window as any
    await w.controller.ask({ kind: 'free', text: '합성 질문' }, { context })
    w.retried = w.controller.retry()
  }, NOTE_CONTEXT)
  await e30Gate.received
  await page.evaluate(() => (window as any).controller.cancel())
  e30Gate.release()
  const state = await page.evaluate(async () => {
    const w = window as any
    await w.retried
    for (let i = 0; i < 300 && w.controller.getSnapshot().pending; i += 1) await new Promise((resolve) => setTimeout(resolve, 10))
    return w.controller.getSnapshot()
  })
  expect(cancelCalls).toEqual([])
  expect(e29Calls).toBe(1)
  expect(state.pending).toBeNull()
  expect(state.failure).toMatchObject({ kind: 'failed', turnId: TURN_ID, question })
})

test('다른 턴을 이어 보는 중에 누른 중단은 그 턴을 중단하지 않고, 질문을 남긴 채 기다림만 멈춘다', async ({ page }) => {
  await setup(page)
  const OTHER = '44444444-4444-4444-8444-444444444444'
  await page.route(e29, (route) => apiError(route, 409, { code: 'conflict', detail: 'turn_in_progress', retry_after_seconds: 1, turn_id: OTHER }, { 'Retry-After': '1' }))
  const cancelCalls: string[] = []
  await page.route(`**/api/ai/turns/${OTHER}/cancel`, (route) => {
    cancelCalls.push('POST')
    return route.fulfill({ json: { turn_id: OTHER, status: 'cancelled', question: { kind: 'free', text: '다른 질문' } } })
  })
  await page.route(`**/api/ai/turns/${OTHER}`, (route) => route.fulfill({ json: { ...runningTurn, turn_id: OTHER, question: { kind: 'free', text: '다른 질문' } } }))
  const state = await page.evaluate(async (context) => {
    const w = window as any
    const asked = w.controller.ask({ kind: 'free', text: '합성 질문' }, { context })
    while (w.controller.getSnapshot().pending?.phase !== 'following') await new Promise((resolve) => setTimeout(resolve, 10))
    await w.controller.cancel()
    await asked
    return w.controller.getSnapshot()
  }, NOTE_CONTEXT)
  expect(cancelCalls).toEqual([])
  expect(state.pending).toBeNull()
  expect(state.failure).toMatchObject({ kind: 'turn_in_progress', question })
})

test('끊긴 뒤 E30이 401이면 다시 시도할 수 있는 network가 아니라 login_required로 남긴다', async ({ page }) => {
  await setup(page)
  await page.route(e29, (route) => fulfillSse(route, sseBody([turnEvent, stepEvents[0]])))
  await page.route(e30, (route) => apiError(route, 401, { code: 'login_required' }))
  const result = await page.evaluate(async (context) => {
    const w = window as any
    await w.controller.ask({ kind: 'free', text: '합성 질문' }, { context })
    const state = w.controller.getSnapshot()
    return { failure: state.failure, canRetry: w.agent.canRetry(state.failure) }
  }, NOTE_CONTEXT)
  expect(result.failure).toMatchObject({ kind: 'login_required', turnId: TURN_ID })
  expect(result.canRetry).toBe(false)
})

test('대화 다시 읽기(E28)가 실패해도 남아 있던 질문의 다시 보내기는 그대로다', async ({ page }) => {
  await setup(page)
  await page.route(e29, (route) => route.abort('failed'))
  await page.route(`**/api/ai/conversations/${CONVERSATION_ID}`, (route) => apiError(route, 404, { code: 'not_found' }))
  const result = await page.evaluate(async (context) => {
    const w = window as any
    await w.controller.ask({ kind: 'free', text: '합성 질문' }, { context })
    await w.controller.refresh()
    const state = w.controller.getSnapshot()
    return { state, canRetry: w.agent.canRetry(state.failure) }
  }, NOTE_CONTEXT)
  expect(result.state.failure).toMatchObject({ kind: 'network', question })
  expect(result.canRetry).toBe(true)
  expect(result.state.loadFailure).toMatchObject({ kind: 'not_found' })
})

test('스트림 전 거절은 code·detail로 나눈다: 429는 기다릴 시간을 지키고, 404·503·형식 밖 응답은 각각 다르게 남는다', async ({ page }) => {
  await setup(page)
  const replies: ((route: Route) => Promise<void>)[] = [
    (route) => apiError(route, 429, { code: 'rate_limited', retry_after_seconds: 30 }, { 'Retry-After': '30' }),
    (route) => apiError(route, 429, { code: 'ai_limit_reached' }),
    (route) => apiError(route, 404, { code: 'not_found' }),
    (route) => apiError(route, 503, { code: 'service_unavailable' }),
    (route) => apiError(route, 409, { code: 'conflict', detail: 'choice_expired' }),
    (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>app</title>' }),
  ]
  let calls = 0
  await page.route(e29, (route) => replies[calls++](route))
  const results = await page.evaluate(
    async ({ context, count }) => {
      const w = window as any
      const out: any[] = []
      for (let index = 0; index < count; index += 1) {
        await w.controller.ask({ kind: 'free', text: `질문 ${index}` }, { context })
        const failure = w.controller.getSnapshot().failure
        out.push({ kind: failure.kind, code: failure.code, waits: failure.retryAt !== null && failure.retryAt > Date.now() + 25_000, canRetry: w.agent.canRetry(failure) })
        if (index === 0) {
          // 기다릴 시간 전의 retry()는 요청을 보내지 않는다.
          await w.controller.retry()
        }
      }
      return out
    },
    { context: NOTE_CONTEXT, count: replies.length },
  )
  expect(calls).toBe(replies.length)
  expect(results).toEqual([
    { kind: 'rate_limited', code: 'rate_limited', waits: true, canRetry: false },
    { kind: 'limit_reached', code: 'ai_limit_reached', waits: false, canRetry: true },
    { kind: 'not_found', code: 'not_found', waits: false, canRetry: false },
    { kind: 'service_unavailable', code: 'service_unavailable', waits: false, canRetry: false },
    { kind: 'choice_expired', code: 'choice_expired', waits: false, canRetry: false },
    { kind: 'unexpected', code: 'unexpected_response', waits: false, canRetry: true },
  ])
})
