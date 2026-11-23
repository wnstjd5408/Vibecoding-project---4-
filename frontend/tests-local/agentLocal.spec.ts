import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { test, expect } from '@playwright/test'
import type { Browser, Locator, Page, TestInfo } from '@playwright/test'

// CS Agent 'AI에게 질문'의 실패 경로 3가지를 로컬 실제 백엔드·DB·Auth로 확인한다(MEG-240, API spec v0.2 9절, PRD AG08·AG09).
// 모델(Bedrock)만 시험용 가짜다(backend/scripts/local_agent_e2e.py). 가짜 모델의 호출 기록은 백엔드의 /__e2e/model-calls로 센다.
// 합성 계정과 비밀번호는 backend/scripts/local_backend.py가 만든 .local-backend/.env에 있다. 값은 출력하지 않는다.
const API = 'http://127.0.0.1:8188'
const WEB = 'http://127.0.0.1:4188'
const NOTE_OPEN = 132110
const NOTE_CITED = 132111
const SELECTED = '이 문장은 시험이 골라서 질문하는 합성 선택 문장이며 실제 학습 자료가 아닙니다.'
const HIDDEN_NOTICE = '이 답변에 쓴 자료를 더 이상 볼 수 없어요.'
const TURNS_PATH = /\/api\/ai\/conversations\/([0-9a-f-]{36})\/turns$/
const TURN_READ_PATH = /\/api\/ai\/turns\/([0-9a-f-]{36})$/

function localPassword(): string {
  const text = readFileSync(new URL('../../.local-backend/.env', import.meta.url), 'utf-8')
  const line = text.split(/\r?\n/).find((l) => l.startsWith('LOCAL_TEST_PASSWORD='))
  if (!line) throw new Error('.local-backend/.env에 LOCAL_TEST_PASSWORD가 없습니다. local_backend fixture를 먼저 실행하세요.')
  return line.slice('LOCAL_TEST_PASSWORD='.length)
}

async function login(page: Page, account: string) {
  await page.goto('/login')
  await page.getByLabel('이메일').fill(`${account}@example.test`)
  await page.getByLabel('비밀번호').fill(localPassword())
  await page.getByRole('button', { name: '로그인' }).click()
  await expect(page.getByLabel('이메일')).toHaveCount(0)
}

async function agentCalls(): Promise<number> {
  const response = await fetch(`${API}/__e2e/model-calls`)
  return ((await response.json()) as { agent: number }).agent
}

async function selectText(page: Page, needle: string) {
  await page.evaluate((text) => {
    const root = document.querySelector('[data-note-body]')!
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const at = node.textContent?.indexOf(text) ?? -1
      if (at < 0) continue
      const range = document.createRange()
      range.setStart(node, at)
      range.setEnd(node, at + text.length)
      const selection = document.getSelection()!
      selection.removeAllRanges()
      selection.addRange(range)
      return
    }
    throw new Error(`글자를 찾지 못했어요: ${text}`)
  }, needle)
}

// member-a로 로그인해 열기용 노트에서 문장을 골라 패널을 연다.
async function openPanel(page: Page): Promise<Locator> {
  await login(page, 'member-a')
  await page.goto(`/notes/${NOTE_OPEN}`)
  await expect(page.getByRole('heading', { level: 1, name: '합성 에이전트 노트' })).toBeVisible()
  await selectText(page, SELECTED)
  await page.getByRole('button', { name: 'AI에게 질문', exact: true }).click()
  const panel = page.getByRole('dialog', { name: 'AI에게 질문' })
  await expect(panel).toBeVisible()
  return panel
}

const aiBox = (panel: Locator) => panel.getByRole('group', { name: 'AI 생성' })

// 브라우저가 보낸 CS Agent 요청을 센다(E29 POST, E30 GET).
function watchRequests(page: Page) {
  const asks: string[] = []
  const reads: string[] = []
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (request.method() === 'POST' && TURNS_PATH.test(path)) asks.push(path)
    if (request.method() === 'GET' && TURN_READ_PATH.test(path)) reads.push(path)
  })
  return { asks, reads }
}

async function shot(page: Page, testInfo: TestInfo, name: string) {
  const body = await page.screenshot()
  await testInfo.attach(name, { body, contentType: 'image/png' })
  // AGENT_SHOT_DIR을 주면 '이름.png'로도 저장한다(PR에 붙일 때 쓴다).
  const dir = process.env.AGENT_SHOT_DIR
  if (dir) {
    mkdirSync(dir, { recursive: true })
    writeFileSync(join(dir, `${name}.png`), body)
  }
}

test.beforeEach(() => {
  execFileSync('uv', ['run', '--frozen', 'python', '-m', 'scripts.local_agent_e2e', 'seed'], { cwd: '../backend', stdio: 'pipe' })
})

test('AC-1: 질문을 보낸 뒤 스트림이 끊겨도 서버가 턴을 끝내고, 화면은 E30으로 결과를 받아 보여 준다', async ({ page }, testInfo) => {
  // E29 응답 본문을 turn 이벤트 바로 뒤에서 끊는다. 본문 읽기를 취소하므로 브라우저가 연결을 닫는다(서버에는 클라이언트 끊김).
  // 같은 read에서 오류를 내면 그 조각이 버려져 turn_id를 잃는다. 그래서 turn 이벤트 조각을 넘긴 다음 read에서 오류를 낸다.
  await page.addInitScript(() => {
    const original = window.fetch.bind(window)
    const w = window as unknown as { __e2eCut: boolean; __e2eCutDone: boolean }
    w.__e2eCut = true
    w.__e2eCutDone = false
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const response = await original(input, init)
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
      const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase()
      if (!w.__e2eCut || method !== 'POST' || !/\/api\/ai\/conversations\/[^/]+\/turns$/.test(url) || !response.body) return response
      w.__e2eCut = false
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let seen = ''
      let cut = false
      const body = new ReadableStream<Uint8Array>({
        async pull(controller) {
          if (cut) {
            await reader.cancel()
            w.__e2eCutDone = true
            controller.error(new TypeError('network error (e2e cut)'))
            return
          }
          const { done, value } = await reader.read()
          if (done) {
            controller.close()
            return
          }
          controller.enqueue(value)
          seen += decoder.decode(value, { stream: true })
          const at = seen.indexOf('event: turn')
          if (at >= 0 && seen.indexOf('\n\n', at) >= 0) cut = true
        },
        cancel(reason) {
          return reader.cancel(reason)
        },
      })
      return new Response(body, { status: response.status, statusText: response.statusText, headers: response.headers })
    }
  })
  const seen = watchRequests(page)
  // E30 응답의 턴 id와 상태를 순서대로 모은다.
  const polled: { turnId: string; status: string }[] = []
  page.on('response', async (response) => {
    const path = new URL(response.url()).pathname
    const match = TURN_READ_PATH.exec(path)
    if (!match || response.request().method() !== 'GET' || response.status() !== 200) return
    const body = await response.json().catch(() => null)
    if (body) polled.push({ turnId: match[1], status: body.status })
  })
  const panel = await openPanel(page)
  const before = await agentCalls()

  // '천천히'가 든 질문은 가짜 모델이 3초 기다린 뒤 답한다. 그 사이 스트림이 끊긴다.
  await panel.getByRole('textbox').fill('합성체이닝은 천천히 설명해 줘')
  await panel.getByRole('button', { name: '보내기' }).click()
  await expect.poll(() => page.evaluate(() => (window as unknown as { __e2eCutDone: boolean }).__e2eCutDone)).toBe(true)
  // 끊긴 직후에는 아직 답이 없다(서버가 모델 응답을 기다리는 중이다).
  await expect(aiBox(panel)).toHaveCount(0)

  await expect(aiBox(panel).getByText('합성 가짜 답변')).toBeVisible({ timeout: 20_000 })
  await expect(panel.getByRole('alert')).toHaveCount(0)
  await expect(panel.getByRole('button', { name: /^\[1\] 노트 · 합성 출처 노트/ })).toBeVisible()
  expect(seen.asks).toHaveLength(1)
  // E30은 끊긴 뒤 아직 실행 중인 턴(running)을 읽었고, 서버가 끝까지 실행해 completed를 받았다.
  await expect.poll(() => polled.at(-1)?.status).toBe('completed')
  expect(polled[0].status).toBe('running')
  // E30이 조회한 턴은 E29가 만든 그 턴 하나다(대화의 유일한 턴).
  const conversationId = TURNS_PATH.exec(seen.asks[0])![1]
  const turnIds = await page.evaluate(async (id) => {
    const conversation = await (await fetch(`/api/ai/conversations/${id}`)).json()
    return conversation.turns.map((t: { turn_id: string }) => t.turn_id) as string[]
  }, conversationId)
  expect(turnIds).toHaveLength(1)
  expect(new Set(polled.map((p) => p.turnId))).toEqual(new Set(turnIds))
  // 모델은 한 번만 불렸다(화면이 다시 보내지 않았다).
  expect(await agentCalls()).toBe(before + 1)
  await shot(page, testInfo, 'AC-1 끊긴 뒤 E30으로 받은 답변')
})

test('AC-2: 추천 질문을 연속으로 눌러도, 같은 멱등 키로 다시 보내도 모델 호출은 1회다', async ({ page }, testInfo) => {
  const seen = watchRequests(page)
  const panel = await openPanel(page)
  await panel.getByRole('textbox').fill('합성체이닝은 무엇인가요?')
  await panel.getByRole('button', { name: '보내기' }).click()
  await expect(aiBox(panel).getByText('합성 가짜 답변')).toBeVisible({ timeout: 20_000 })
  const afterFirst = await agentCalls()

  // 추천 질문 버튼을 연달아 세 번 누른다(두 번은 더블클릭).
  const suggestion = panel.getByRole('button', { name: '합성체이닝을 예시로 보여 줘' })
  await expect(suggestion).toBeVisible()
  await suggestion.evaluate((button: HTMLElement) => {
    button.click()
    button.click()
    button.click()
  })
  await expect(aiBox(panel)).toHaveCount(1, { timeout: 20_000 })
  await expect(aiBox(panel).getByText('합성 가짜 답변')).toBeVisible({ timeout: 20_000 })
  await expect(panel.getByRole('alert')).toHaveCount(0)
  // 답이 끝난 뒤 조금 더 기다려도 늦게 도착한 호출이 없다.
  await page.waitForTimeout(1_000)
  expect(await agentCalls()).toBe(afterFirst + 1)
  expect(seen.asks).toHaveLength(2)
  await shot(page, testInfo, 'AC-2 추천 질문 연속 클릭 뒤 답변')

  // 서버 쪽 중복 방지(E29 2단계): 같은 Idempotency-Key로 두 번 동시에 보내도 모델 호출은 1회다.
  const conversationId = TURNS_PATH.exec(seen.asks[0])![1]
  const beforeResend = await agentCalls()
  const statuses = await page.evaluate(async (id) => {
    const key = crypto.randomUUID()
    const send = () => fetch(`/api/ai/conversations/${id}/turns`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key, Accept: 'text/event-stream' },
      body: JSON.stringify({ question: { kind: 'free', text: '합성체이닝의 단점은 뭐야?' } }),
    }).then(async (response) => ({ status: response.status, body: await response.text() }))
    const [first, second] = await Promise.all([send(), send()])
    // 끝난 뒤 같은 키로 한 번 더 보내면 저장된 결과를 다시 돌려준다.
    const third = await send()
    return [first, second, third].map((r) => ({ status: r.status, result: r.body.includes('event: result') }))
  }, conversationId)
  // 하나는 실행 스트림, 다른 하나는 실행 중 409(in_progress)이거나 같은 결과의 재생이다. 셋째는 재생이다.
  expect(statuses.filter((s) => s.status === 200 && s.result).length).toBeGreaterThanOrEqual(2)
  expect(statuses.every((s) => s.status === 200 || s.status === 409)).toBe(true)
  expect(await agentCalls()).toBe(beforeResend + 1)
})

async function operatorPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ baseURL: WEB })
  const page = await context.newPage()
  await login(page, 'operator')
  return page
}

test('AC-3: 인용한 노트를 비공개로 바꾸면 그 턴이 가려지고, 출처(E32)는 404다', async ({ page, browser }, testInfo) => {
  const seen = watchRequests(page)
  const panel = await openPanel(page)
  await panel.getByRole('textbox').fill('합성체이닝은 무엇인가요?')
  await panel.getByRole('button', { name: '보내기' }).click()
  await expect(aiBox(panel).getByText('합성 가짜 답변')).toBeVisible({ timeout: 20_000 })
  const conversationId = TURNS_PATH.exec(seen.asks[0])![1]

  // 가리기 전: 턴이 보이고 출처 1이 열린다.
  const before = await page.evaluate(async (id) => {
    const conversation = await (await fetch(`/api/ai/conversations/${id}`)).json()
    const turn = conversation.turns.at(-1)
    const source = await fetch(`/api/ai/turns/${turn.turn_id}/sources/1`)
    return { turnId: turn.turn_id as string, hidden: Boolean(turn.hidden), sourceStatus: source.status }
  }, conversationId)
  expect(before).toEqual({ turnId: before.turnId, hidden: false, sourceStatus: 200 })

  // 운영자가 인용된 노트를 비공개로 바꾼다(E17, 실제 API).
  const operator = await operatorPage(browser)
  const patched = await operator.evaluate(async (noteId) => {
    const response = await fetch(`/api/admin/notes/${noteId}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_published: false }),
    })
    return { status: response.status, body: await response.json() }
  }, NOTE_CITED)
  expect(patched.status).toBe(200)
  expect(patched.body.is_published).toBe(false)
  await operator.context().close()

  // 화면: 출처를 열면 서버가 404를 주고, 화면이 대화를 다시 읽어 가린 턴을 보인다.
  await panel.getByRole('button', { name: /^\[1\] 노트 · 합성 출처 노트/ }).click()
  const notice = panel.getByRole('status').filter({ hasText: HIDDEN_NOTICE })
  await expect(notice).toBeVisible({ timeout: 15_000 })
  await expect(aiBox(panel)).toHaveCount(0)
  await expect(panel.getByRole('button', { name: /^\[1\]/ })).toHaveCount(0)
  await expect(panel.getByRole('button', { name: '합성체이닝을 예시로 보여 줘' })).toHaveCount(0)
  // 열어 둔 노트는 그대로 공개라 남는다.
  await expect(page.getByRole('heading', { level: 1, name: '합성 에이전트 노트' })).toBeVisible()
  await shot(page, testInfo, 'AC-3 인용 노트 비공개 뒤 가린 턴')

  // API: 같은 턴의 출처는 404이고, E28·E30은 그 턴을 가린 채 돌려준다(답변 본문이 없다).
  const after = await page.evaluate(async ({ id, turnId }) => {
    const source = await fetch(`/api/ai/turns/${turnId}/sources/1`)
    const conversation = await (await fetch(`/api/ai/conversations/${id}`)).json()
    const turn = conversation.turns.find((t: { turn_id: string }) => t.turn_id === turnId)
    const read = await (await fetch(`/api/ai/turns/${turnId}`)).json()
    return {
      sourceStatus: source.status,
      listed: { hidden: Boolean(turn.hidden), hasResult: JSON.stringify(turn).includes('합성 가짜 답변') },
      read: { hidden: Boolean(read.hidden), hasResult: JSON.stringify(read).includes('합성 가짜 답변') },
    }
  }, { id: conversationId, turnId: before.turnId })
  expect(after).toEqual({ sourceStatus: 404, listed: { hidden: true, hasResult: false }, read: { hidden: true, hasResult: false } })
})
