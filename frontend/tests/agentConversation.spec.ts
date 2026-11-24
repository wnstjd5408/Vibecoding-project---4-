import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// MEG-255 CS Agent API 클라이언트와 대화 상태. playwright.config.ts가 VITE_API_MOCK=true로 서버를 띄우므로
// 가짜 API(src/api/mocks/agent.ts)가 E27~E32와 E29의 SSE 바이트를 흉내 낸다. 화면은 T6c 범위라 아직 없어서,
// 개발 서버가 내주는 모듈을 브라우저에서 직접 불러 대화 상태(AgentConversationController)를 시험한다.
// 실제 fetch 경로(요청 헤더, 끊긴 응답, 409 in_progress)는 agentTransport.spec.ts가 합성 HTTP 응답으로 시험한다.
// 실제 백엔드로 하는 끊김 E2E는 T7(MEG-240) 범위다(결정 요청 14 권장안).

const NOTE_CONTEXT = { origin: 'note', note_id: 11, note_revision: 3, selection: { start: 0, end: 10 } }

/* eslint-disable @typescript-eslint/no-explicit-any */
async function setup(page: Page) {
  await page.goto('/dev/mockup')
  await page.evaluate(async () => {
    const w = window as any
    const load = (path: string) => import(/* @vite-ignore */ path)
    w.agent = await load('/src/agent/conversation.ts')
    w.mock = await load('/src/api/mocks/agent.ts')
    w.sse = await load('/src/agent/sse.ts')
    const session = await load('/src/api/mocks/session.ts')
    w.mock.resetAgentMock()
    session.setMockSession('member')
    // 상태가 바뀔 때마다 화면이 쓸 값만 짧게 남긴다.
    w.record = (controller: any) => {
      const log: any[] = []
      controller.subscribe(() => {
        const state = controller.getSnapshot()
        log.push({
          phase: state.pending?.phase ?? null,
          turnId: state.pending?.turnId ?? null,
          steps: (state.pending?.steps ?? []).map((s: any) => `${s.step}:${s.state}${s.paragraphCount !== undefined ? `:${s.paragraphCount}:${s.sourceKind}` : ''}`),
          delayed: state.pending?.delayed ?? false,
          failure: state.failure?.kind ?? null,
          turns: state.turns.length,
        })
      })
      return log
    }
    w.e29Keys = () =>
      w.mock
        .agentMockRequests()
        .filter((r: any) => r.method === 'POST' && r.path.endsWith('/turns'))
        .map((r: any) => r.idempotencyKey)
    w.paths = () => w.mock.agentMockRequests().map((r: any) => `${r.method} ${r.path.replace(/[0-9a-f-]{36}/g, ':id')}`)
  })
}

test('SSE 파서: 줄 끝 세 종류, 조각 경계, 주석, 여러 data 줄, 닫히지 않은 마지막 이벤트', async ({ page }) => {
  await setup(page)
  const result = await page.evaluate(() => {
    const w = window as any
    const parser = new w.sse.SseParser()
    const out: any[] = []
    const push = (text: string) => out.push(...parser.push(text))
    push('﻿event: turn\r\ndata: {"turn_id":"t","seq":1}\r\n\r\n')
    push(': keep-alive\n\nevent: st')
    push('ep\ndata: {"step":"understand",')
    push('"state":"current"}\r')
    push('\n\r')
    push('event: delayed\rdata: {}\r\r')
    push('data: 줄1\ndata: 줄2\n\n')
    push('event: result\ndata: {"incomplete":')
    parser.end()
    return out
  })
  expect(result).toEqual([
    { event: 'turn', data: '{"turn_id":"t","seq":1}' },
    { event: 'step', data: '{"step":"understand","state":"current"}' },
    { event: 'delayed', data: '{}' },
    { event: 'message', data: '줄1\n줄2' },
  ])
  const events = await page.evaluate(() => {
    const w = window as any
    return [
      w.sse.toTurnEvent({ event: 'delayed', data: '{}' }),
      w.sse.toTurnEvent({ event: 'error', data: '{"error":{"code":"ai_unavailable","message":"m","request_id":"r"}}' }),
      w.sse.toTurnEvent({ event: 'unknown', data: '{}' }),
    ]
  })
  expect(events).toEqual([{ type: 'delayed' }, { type: 'error', data: { code: 'ai_unavailable', message: 'm', request_id: 'r' } }, null])
})

test('SSE 파서: 스트림이 CR 하나로 끝나도 마지막 이벤트를 낸다', async ({ page }) => {
  await setup(page)
  const result = await page.evaluate(() => {
    const w = window as any
    const parser = new w.sse.SseParser()
    const pushed = parser.push('event: result\rdata: {"a":1}\r\r')
    const ended = parser.end()
    return { pushed, ended }
  })
  expect(result.pushed).toEqual([])
  expect(result.ended).toEqual([{ event: 'result', data: '{"a":1}' }])
})

test('AC-1 step·result가 대화 상태로 바뀐다: 단계 3개를 차례로 보이고 답변 턴을 대화에 넣는다', async ({ page }) => {
  await setup(page)
  const result = await page.evaluate(async (context) => {
    const w = window as any
    const controller = new w.agent.AgentConversationController()
    const log = w.record(controller)
    await controller.ask({ kind: 'free', text: '합성 질문' }, { context })
    const state = controller.getSnapshot()
    return { log, state, paths: w.paths(), keys: w.e29Keys() }
  }, NOTE_CONTEXT)
  const phases = [...new Set(result.log.map((entry: any) => entry.phase))]
  expect(phases).toEqual(['creating', 'sending', 'streaming', null])
  const lastSteps = result.log.filter((entry: any) => entry.phase === 'streaming').at(-1).steps
  expect(lastSteps).toEqual(['understand:done', 'retrieve:done:3:note', 'compose:done'])
  // 앞으로 할 단계는 미리 보이지 않는다(결정 9): 처음 받은 단계 표시는 understand 하나다.
  expect(result.log.find((entry: any) => entry.steps.length > 0).steps).toEqual(['understand:current'])
  expect(result.state.pending).toBeNull()
  expect(result.state.failure).toBeNull()
  expect(result.state.conversation.origin).toBe('note')
  expect(result.state.turns).toHaveLength(1)
  expect(result.state.turns[0]).toMatchObject({ status: 'completed', question: { kind: 'free', text: '합성 질문' }, result: { state: 'answered' } })
  expect(result.state.turns[0].result.sources.map((s: any) => s.ref)).toEqual([1, 2])
  expect(result.paths).toEqual(['POST /api/ai/conversations', 'POST /api/ai/conversations/:id/turns'])
  expect(result.keys).toHaveLength(1)
  expect(result.keys[0]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
})

test('AC-1 delayed가 대화 상태로 바뀐다: 지연 표시가 켜지고 질문을 다시 보내지 않는다', async ({ page }) => {
  await setup(page)
  const result = await page.evaluate(async (context) => {
    const w = window as any
    w.mock.setAgentMockScenario('delayed')
    const controller = new w.agent.AgentConversationController()
    const log = w.record(controller)
    await controller.ask({ kind: 'preset', preset: 'detail' }, { context })
    return { log, state: controller.getSnapshot(), keys: w.e29Keys() }
  }, NOTE_CONTEXT)
  const firstDelayed = result.log.find((entry: any) => entry.delayed)
  expect(firstDelayed.steps).toContain('compose:current')
  expect(result.state.turns[0]).toMatchObject({ status: 'completed', question: { kind: 'preset', preset: 'detail' } })
  expect(result.keys).toHaveLength(1)
})

test('AC-1 error가 대화 상태로 바뀐다: 시스템 실패(S8)와 실행 중 한도 초과(S12)를 구분하고 질문을 남긴다', async ({ page }) => {
  await setup(page)
  const result = await page.evaluate(async (context) => {
    const w = window as any
    const run = async (scenario: string) => {
      w.mock.setAgentMockScenario(scenario)
      const controller = new w.agent.AgentConversationController()
      await controller.ask({ kind: 'free', text: `${scenario} 질문` }, { context })
      const state = controller.getSnapshot()
      return { failure: state.failure, turns: state.turns.length, pending: state.pending, canRetry: w.agent.canRetry(state.failure) }
    }
    return { error: await run('error'), limit: await run('limit_after_start') }
  }, NOTE_CONTEXT)
  expect(result.error.failure).toMatchObject({ kind: 'failed', code: 'ai_unavailable', question: { kind: 'free', text: 'error 질문' } })
  expect(result.error.failure.turnId).toMatch(/^[0-9a-f-]{36}$/)
  expect(result.error.pending).toBeNull()
  expect(result.error.turns).toBe(0)
  expect(result.error.canRetry).toBe(true)
  expect(result.limit.failure).toMatchObject({ kind: 'limit_reached', code: 'ai_limit_reached', question: { text: 'limit_after_start 질문' } })
})

for (const scenario of ['disconnect', 'eof'] as const) {
  test(`AC-2 스트림이 중간에 ${scenario === 'disconnect' ? '끊기면' : '마지막 이벤트 없이 닫히면'} E30으로 결과를 받는다`, async ({ page }) => {
    await setup(page)
    const result = await page.evaluate(
      async ({ context, scenario }) => {
        const w = window as any
        w.mock.setAgentMockScenario(scenario)
        const controller = new w.agent.AgentConversationController()
        const log = w.record(controller)
        const started = Date.now()
        await controller.ask({ kind: 'free', text: '끊김 합성 질문' }, { context })
        return { log, state: controller.getSnapshot(), paths: w.paths(), keys: w.e29Keys(), elapsed: Date.now() - started }
      },
      { context: NOTE_CONTEXT, scenario },
    )
    const recovering = result.log.filter((entry: any) => entry.phase === 'recovering')
    expect(recovering.length).toBeGreaterThan(0)
    // 끊기기 전에 받은 단계와 문단 수는 남고, E30의 지금 단계(compose)가 이어진다.
    expect(recovering[0].steps).toEqual(['understand:done', 'retrieve:done:3:note'])
    expect(recovering.at(-1).steps).toEqual(['understand:done', 'retrieve:done:3:note', 'compose:current'])
    expect(result.state.pending).toBeNull()
    expect(result.state.failure).toBeNull()
    expect(result.state.turns).toHaveLength(1)
    expect(result.state.turns[0]).toMatchObject({ status: 'completed', result: { state: 'answered' } })
    // E29는 한 번만 보냈고, E30을 running → completed 순서로 두 번 이상 불렀다. 두 번째 조회는 retry_after_seconds(1초)를 지켰다.
    expect(result.keys).toHaveLength(1)
    expect(result.paths.filter((path: string) => path === 'GET /api/ai/turns/:id').length).toBeGreaterThanOrEqual(2)
    expect(result.elapsed).toBeGreaterThanOrEqual(1000)
  })
}

test('AC-3 한 동작을 두 번 눌러도 Idempotency-Key는 하나다(진행 중 중복 호출과 429 뒤 다시 보내기)', async ({ page }) => {
  await setup(page)
  const result = await page.evaluate(async (context) => {
    const w = window as any
    const controller = new w.agent.AgentConversationController()
    // 같은 동작을 빠르게 두 번 누른다: 두 번째는 새 요청 없이 진행 중인 요청을 돌려준다.
    const first = controller.ask({ kind: 'free', text: '두 번 누른 질문' }, { context })
    const second = controller.ask({ kind: 'free', text: '두 번 누른 질문' }, { context })
    const same = first === second
    await Promise.all([first, second])
    const afterDouble = w.e29Keys()

    // 429 rate_limited: 기다릴 시간 전에는 retry()가 보내지 않고, 지난 뒤 같은 키로 보낸다.
    w.mock.setAgentMockScenario('rate_limited')
    await controller.ask({ kind: 'free', text: '제한 뒤 질문' })
    const limited = controller.getSnapshot().failure
    const canRetryBefore = w.agent.canRetry(limited)
    await controller.retry()
    const beforeWait = w.e29Keys().length
    // 기다릴 시간이 끝나면 요청 없이도 상태 알림이 한 번 와서 화면이 '다시 시도'를 다시 켤 수 있다.
    let notified = 0
    const unsubscribe = controller.subscribe(() => (notified += 1))
    await new Promise((resolve) => setTimeout(resolve, limited.retryAt - Date.now() + 100))
    unsubscribe()
    const canRetryAfter = w.agent.canRetry(controller.getSnapshot().failure)
    const retryA = controller.retry()
    const retryB = controller.retry()
    await Promise.all([retryA, retryB])
    return { same, afterDouble, limited, beforeWait, notified, canRetryBefore, canRetryAfter, keys: w.e29Keys(), state: controller.getSnapshot() }
  }, NOTE_CONTEXT)
  expect(result.same).toBe(true)
  expect(result.canRetryBefore).toBe(false)
  expect(result.notified).toBe(1)
  expect(result.canRetryAfter).toBe(true)
  expect(result.afterDouble).toHaveLength(1)
  expect(result.limited).toMatchObject({ kind: 'rate_limited', question: { text: '제한 뒤 질문' } })
  expect(result.limited.retryAt).toBeGreaterThan(0)
  expect(result.beforeWait).toBe(2) // 기다리는 동안 retry()는 요청을 보내지 않았다
  expect(result.keys).toHaveLength(3)
  expect(result.keys[2]).toBe(result.keys[1]) // 429 뒤 다시 보낸 요청은 같은 키다
  expect(result.keys[1]).not.toBe(result.keys[0]) // 다른 동작은 다른 키다
  expect(result.state.turns.map((turn: any) => turn.question.text)).toEqual(['두 번 누른 질문', '제한 뒤 질문'])
})

test('S8 다시 시도: E30으로 실패를 확인한 뒤 새 키로 보낸다', async ({ page }) => {
  await setup(page)
  const result = await page.evaluate(async (context) => {
    const w = window as any
    w.mock.setAgentMockScenario('error')
    const controller = new w.agent.AgentConversationController()
    await controller.ask({ kind: 'free', text: '실패할 질문' }, { context })
    const failedTurn = controller.getSnapshot().failure.turnId
    w.mock.setAgentMockScenario('answered')
    await controller.retry()
    return { failedTurn, paths: w.paths(), keys: w.e29Keys(), state: controller.getSnapshot() }
  }, NOTE_CONTEXT)
  expect(result.paths.slice(-2)).toEqual(['GET /api/ai/turns/:id', 'POST /api/ai/conversations/:id/turns'])
  expect(result.keys).toHaveLength(2)
  expect(result.keys[1]).not.toBe(result.keys[0])
  expect(result.state.failure).toBeNull()
  expect(result.state.turns).toHaveLength(1)
  expect(result.state.turns[0]).toMatchObject({ status: 'completed', question: { text: '실패할 질문' } })
})

test('409 turn_in_progress: 진행 중인 다른 턴을 E30으로 이어 보고, 이번 질문은 남겨 둔다', async ({ page }) => {
  await setup(page)
  const result = await page.evaluate(async (context) => {
    const w = window as any
    const controller = new w.agent.AgentConversationController()
    await controller.ask({ kind: 'free', text: '첫 질문' }, { context })
    w.mock.setAgentMockScenario('turn_in_progress')
    const log = w.record(controller)
    await controller.ask({ kind: 'free', text: '겹친 질문' })
    const blocked = controller.getSnapshot()
    w.mock.setAgentMockScenario('answered')
    await controller.retry()
    return { log, blocked, keys: w.e29Keys(), state: controller.getSnapshot() }
  }, NOTE_CONTEXT)
  expect(result.log.some((entry: any) => entry.phase === 'following' && entry.turnId)).toBe(true)
  expect(result.blocked.failure).toMatchObject({ kind: 'turn_in_progress', question: { text: '겹친 질문' } })
  expect(result.blocked.turns.map((turn: any) => turn.question.text)).toEqual(['첫 질문', '다른 곳에서 보낸 합성 질문'])
  expect(result.keys[2]).toBe(result.keys[1]) // 보내지 못한 질문은 같은 키로 다시 보낸다
  expect(result.state.turns.map((turn: any) => turn.question.text)).toEqual(['첫 질문', '다른 곳에서 보낸 합성 질문', '겹친 질문'])
})

test('E31 중단: 받다 만 답변 없이 중단된 턴과 다시 넣을 질문을 남긴다', async ({ page }) => {
  await setup(page)
  const result = await page.evaluate(async (context) => {
    const w = window as any
    w.mock.setAgentMockScenario('answered', { stepMs: 200 })
    const controller = new w.agent.AgentConversationController()
    const asked = controller.ask({ kind: 'free', text: '중단할 질문' }, { context })
    while (!controller.getSnapshot().pending?.steps.length) await new Promise((resolve) => setTimeout(resolve, 10))
    const atCancel = controller.getSnapshot().pending
    await controller.cancel()
    await asked
    while (controller.getSnapshot().pending) await new Promise((resolve) => setTimeout(resolve, 10))
    return { atCancel, paths: w.paths(), state: controller.getSnapshot() }
  }, NOTE_CONTEXT)
  expect(result.atCancel).toMatchObject({ phase: 'streaming', steps: [{ step: 'understand', state: 'current' }] })
  expect(result.atCancel.turnId).toMatch(/^[0-9a-f-]{36}$/)
  expect(result.paths).toContain('POST /api/ai/turns/:id/cancel')
  expect(result.state.pending).toBeNull()
  expect(result.state.failure).toBeNull()
  expect(result.state.cancelled).toMatchObject({ question: { kind: 'free', text: '중단할 질문' } })
  expect(result.state.turns).toHaveLength(1)
  expect(result.state.turns[0].status).toBe('cancelled')
  expect(result.state.turns[0].result).toBeUndefined()
})

test('대화를 만드는 중에 중단하면 E29를 보내지 않는다', async ({ page }) => {
  await setup(page)
  const result = await page.evaluate(async (context) => {
    const w = window as any
    const controller = new w.agent.AgentConversationController()
    const asked = controller.ask({ kind: 'free', text: '바로 멈춘 질문' }, { context })
    const phase = controller.getSnapshot().pending?.phase
    await controller.cancel()
    await asked
    return { phase, keys: w.e29Keys(), state: controller.getSnapshot() }
  }, NOTE_CONTEXT)
  expect(result.phase).toBe('creating')
  expect(result.keys).toHaveLength(0)
  expect(result.state.pending).toBeNull()
  expect(result.state.failure).toBeNull()
})

test('결정 요청 10: 같은 객체 안에서는 대화를 유지하고 refresh()가 E28로 다시 읽는다. E32 출처를 연다', async ({ page }) => {
  await setup(page)
  const result = await page.evaluate(async (context) => {
    const w = window as any
    const api = await import(/* @vite-ignore */ '/src/agent/api.ts' as string)
    const controller = new w.agent.AgentConversationController()
    await controller.ask({ kind: 'free', text: '첫 질문' }, { context })
    await controller.ask({ kind: 'suggested', text: '합성 추천 질문 하나', from_turn_id: controller.getSnapshot().turns[0].turn_id })
    const before = controller.getSnapshot()
    await controller.refresh()
    const after = controller.getSnapshot()
    const source = await api.readSource(after.turns[0].turn_id, 1)
    let missing = null
    try {
      await api.readSource(after.turns[0].turn_id, 9)
    } catch (error: any) {
      missing = error.code
    }
    return { before, after, source, missing, paths: w.paths() }
  }, NOTE_CONTEXT)
  expect(result.paths.filter((path: string) => path === 'POST /api/ai/conversations')).toHaveLength(1) // 두 번째 질문은 같은 대화
  expect(result.after.conversation.conversation_id).toBe(result.before.conversation.conversation_id)
  expect(result.after.turns.map((turn: any) => turn.seq)).toEqual([1, 2])
  expect(result.after.turns.map((turn: any) => turn.question.kind)).toEqual(['free', 'suggested'])
  expect(result.source).toMatchObject({ ref: 1, source_kind: 'note', changed_since_cited: false })
  expect(result.missing).toBe('not_found')
})
