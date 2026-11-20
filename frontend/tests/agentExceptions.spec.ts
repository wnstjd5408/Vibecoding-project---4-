import { expect, test } from '@playwright/test'
import type { Locator, Page, TestInfo } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { goInApp } from './inApp.ts'

// MEG-260 CS Agent 예외 상태 화면(T6d). 화면 목록 13~20번을 가짜 API(src/api/mocks/agent.ts)로 띄운다. 모델은 부르지 않는다.
// 모바일은 기존 보드가 있던 상태(F6-8m·F6-11m·F6-13m·F6-15m)만 본다. MEG-262에서 새로 그린 모바일 보드의 상태는 T6g(MEG-263)다.
// AGENT_SHOT_DIR을 주면 스크린샷을 '보드 ID.png'로 저장한다(AC-1, 캔버스 보드와 나란히 PR에 붙인다).

const PC = { width: 1280, height: 800 }
const MOBILE = { width: 390, height: 844 }
const SELECTED = 'UnknownWord 는 사전에 없습니다.'
const OTHER = '을 설명합니다.'

/* eslint-disable @typescript-eslint/no-explicit-any */
async function mock(page: Page, scenario: string, stepMs = 20) {
  await page.evaluate(async ({ scenario, stepMs }) => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    m.setAgentMockScenario(scenario, { stepMs })
  }, { scenario, stepMs })
}

async function callMock(page: Page, name: 'revokeAgentMockSources' | 'revokeAgentMockNote') {
  await page.evaluate(async (name) => {
    const m: any = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    m[name]()
  }, name)
}

type Sent = { method: string; path: string; body?: any }
async function sent(page: Page): Promise<Sent[]> {
  return page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    return m.agentMockRequests().map((r: any) => ({ method: r.method, path: r.path.replace(/[0-9a-f-]{36}/g, ':id'), body: r.body }))
  })
}
const turnBodies = async (page: Page) => (await sent(page)).filter((r) => r.path === '/api/ai/conversations/:id/turns').map((r) => r.body)

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

async function login(page: Page, viewport = PC) {
  await page.setViewportSize(viewport)
  await page.goto('/login')
  await page.getByLabel('이메일').fill('member@example.test')
  await page.getByLabel('비밀번호').fill('example-password')
  await page.getByRole('button', { name: '로그인' }).click()
  await expect(page).toHaveURL(/\/quiz$/)
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    m.resetAgentMock()
  })
  await goInApp(page, '/notes/11?cs-agent=1')
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
}

async function openPanel(page: Page, needle = SELECTED): Promise<Locator> {
  await selectText(page, needle)
  await page.getByRole('button', { name: 'AI에게 질문', exact: true }).click()
  const panel = page.getByRole('dialog', { name: 'AI에게 질문' })
  await expect(panel).toBeVisible()
  return panel
}

const input = (panel: Locator) => panel.getByRole('textbox')
const send = (panel: Locator) => panel.getByRole('button', { name: '보내기' })
const aiBox = (panel: Locator) => panel.getByRole('group', { name: 'AI 생성' })

async function shot(page: Page, testInfo: TestInfo, name: string) {
  const body = await page.screenshot()
  await testInfo.attach(name, { body, contentType: 'image/png' })
  const dir = process.env.AGENT_SHOT_DIR
  if (dir) writeFileSync(join(dir, `${name.split(' ')[0]}.png`), body)
}

// 빠른 질문 '자세히 설명'으로 첫 답을 받는다.
async function firstAnswer(page: Page, panel: Locator, scenario = 'answered') {
  await mock(page, scenario)
  await panel.getByRole('button', { name: '자세히 설명' }).click()
}

for (const [device, viewport] of [['PC', PC], ['모바일', MOBILE]] as const) {
  const id = (pc: string, mobile: string) => (device === 'PC' ? pc : mobile)

  test(`${device}: 의미 확인은 후보를 고르면 같은 질문을 그 후보로 보낸다(F6-11)`, async ({ page }, testInfo) => {
    await login(page, viewport)
    const panel = await openPanel(page)
    await firstAnswer(page, panel, 'clarify')
    await expect(aiBox(panel).getByText('어느 뜻으로 물어보셨나요?')).toBeVisible({ timeout: 10_000 })
    const options = aiBox(panel).getByRole('group', { name: '어느 뜻으로 물어보셨나요?' }).getByRole('button')
    await expect(options).toHaveText(['합성 뜻 하나', '합성 뜻 둘'])
    await expect(panel.getByText('고르면 그 내용으로 이어서 질문해요. 둘 다 아니면 아래 칸에 직접 적어 주세요.')).toBeVisible()
    await expect(panel.getByLabel('이어서 질문하기 · 직접 보충해도 돼요')).toBeVisible()
    // 고르기 전에는 답변(본문 절)을 만들지 않는다
    await expect(panel.getByText('합성 답변 첫 절입니다')).toHaveCount(0)
    await shot(page, testInfo, `${id('F6-11', 'F6-11m')} 의미 확인`)

    await options.first().click()
    await expect(aiBox(panel).getByText('합성 답변 첫 절입니다')).toBeVisible({ timeout: 10_000 })
    const bodies = await turnBodies(page)
    expect(bodies).toHaveLength(2)
    expect(bodies[1].question).toEqual({ kind: 'preset', preset: 'detail' })
    expect(bodies[1].reply).toEqual({ turn_id: bodies[1].reply.turn_id, clarify_option_id: 'o-1' })
  })

  test(`${device}: 확인된 교정은 노트 문장과 근거 기준, 확인하지 못한 부분을 나눠 보인다(F6-13)`, async ({ page }, testInfo) => {
    await login(page, viewport)
    const panel = await openPanel(page)
    await firstAnswer(page, panel, 'correction')
    const box = aiBox(panel)
    await expect(box.getByRole('heading', { name: '노트에서 확인할 부분' })).toBeVisible({ timeout: 10_000 })
    await expect(box.getByText('노트 문장', { exact: true })).toBeVisible()
    await expect(box.getByText('“합성 노트 문장”')).toBeVisible()
    await expect(box.getByText('노트 문단 기준')).toBeVisible()
    await expect(box.getByText('합성 고친 내용')).toBeVisible()
    await expect(box.getByRole('heading', { name: '확인하지 못한 부분' })).toBeVisible()
    await expect(box.getByText('노트는 자동으로 고치지 않아요.')).toBeVisible()
    await shot(page, testInfo, `${id('F6-13', 'F6-13m')} 확인된 교정`)
  })

  test(`${device}: 대화 중 다른 문장을 고르면 고르기 전까지 보내기를 잠그고, 현재 대화에 추가하면 다음 질문에 붙인다(F6-8)`, async ({ page }, testInfo) => {
    await login(page, viewport)
    let panel = await openPanel(page)
    await firstAnswer(page, panel)
    await expect(aiBox(panel)).toBeVisible({ timeout: 10_000 })
    await input(panel).fill('이어서 쓴 질문')
    if (device === '모바일') {
      await panel.getByRole('button', { name: '노트로 돌아가기' }).click()
      await expect(panel).toBeHidden()
    }
    panel = await openPanel(page, OTHER)
    const card = panel.getByRole('group', { name: '새로 선택한 내용을 어떻게 쓸까요?' })
    await expect(card).toBeVisible()
    await expect(card.getByText(`‘${OTHER}’`)).toBeVisible()
    await expect(card.getByRole('heading', { name: '새로 선택한 내용을 어떻게 쓸까요?' })).toBeFocused()
    await expect(panel.getByRole('button', { name: /^이전 대화 보기/ })).toBeVisible()
    // 고르기 전에는 보내기를 잠근다(AC-3). 초안은 그대로다
    await expect(send(panel)).toHaveAttribute('aria-disabled', 'true')
    await expect(input(panel)).toHaveValue('이어서 쓴 질문')
    await shot(page, testInfo, `${id('F6-8', 'F6-8m')} 다른 영역 선택`)
    await send(panel).click({ force: true })
    expect(await turnBodies(page)).toHaveLength(1)

    await card.getByRole('button', { name: '현재 대화에 추가' }).click()
    await expect(card).toBeHidden()
    await expect(panel.getByText(`선택: ‘${OTHER}’`)).toBeVisible()
    await expect(panel.getByText(`선택: ‘${SELECTED}’`)).toBeVisible()
    await expect(send(panel)).not.toHaveAttribute('aria-disabled', 'true')
    await send(panel).click()
    await expect(aiBox(panel)).toHaveCount(1, { timeout: 10_000 })
    await expect(panel.getByText('이어서 쓴 질문', { exact: true })).toBeVisible()
    const bodies = await turnBodies(page)
    expect(bodies).toHaveLength(2)
    expect(bodies[1].add_selections).toHaveLength(1)
    expect(bodies[1].add_selections[0]).toMatchObject({ note_id: 11 })
  })

  test(`${device}: 노트를 더 볼 수 없으면 대화와 출처를 닫고 노트 목록으로 가는 길만 둔다(F6-15)`, async ({ page }, testInfo) => {
    await login(page, viewport)
    const panel = await openPanel(page)
    await firstAnswer(page, panel)
    await expect(aiBox(panel)).toBeVisible({ timeout: 10_000 })
    await callMock(page, 'revokeAgentMockNote')
    await input(panel).fill('다음 질문')
    await send(panel).click()
    await expect(panel.getByText('이 자료로 나눈 대화와 출처를 함께 닫았어요.')).toBeVisible({ timeout: 10_000 })
    await expect(aiBox(panel)).toHaveCount(0)
    await expect(panel.getByRole('textbox')).toHaveCount(0)
    if (device === 'PC') {
      await expect(page.getByRole('heading', { level: 1, name: '이 자료를 더 이상 볼 수 없어요' })).toBeVisible()
      await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeHidden()
      await expect(page.getByRole('link', { name: '노트 목록으로 가기' })).toBeVisible()
    } else {
      await expect(panel.getByRole('heading', { name: '이 자료를 더 이상 볼 수 없어요' })).toBeVisible()
      await expect(panel.getByRole('link', { name: '노트 목록으로 가기' })).toBeVisible()
    }
    await shot(page, testInfo, `${id('F6-15', 'F6-15m')} 노트 접근 변경`)
    await panel.getByRole('link', { name: device === 'PC' ? '닫기' : '노트 목록', exact: true }).click()
    await expect(page).toHaveURL(/127\.0\.0\.1:4183\/$/)
  })
}

test('PC: 근거 일부만 확인은 확인하지 못한 부분을 따로 보인다(F6-12)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await firstAnswer(page, panel, 'partial')
  const box = aiBox(panel)
  await expect(box.getByText('합성 부분 답변 문장입니다')).toBeVisible({ timeout: 10_000 })
  await expect(box.getByRole('heading', { name: '확인하지 못한 부분' })).toBeVisible()
  await expect(box.getByText('합성 한계 문장입니다.')).toBeVisible()
  await expect(panel.getByLabel('이어서 질문하기 · 더 구체적으로 물어볼 수 있어요')).toBeVisible()
  await expect(panel.getByRole('button', { name: '노트로 돌아가기' })).toBeVisible()
  await shot(page, testInfo, 'F6-12 근거 일부만 확인')
})

test('PC: 근거가 없으면 AI 생성 표시 없이 서버 고정 안내(노트 근거 문구, 문장 A)만 보인다(F6-12b)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await firstAnswer(page, panel, 'no_evidence')
  const notice = panel.getByRole('status').filter({ hasText: '참고할 수 있는 노트 자료를 찾지 못했어요.' })
  await expect(notice).toBeVisible({ timeout: 10_000 })
  await expect(notice.getByText('그래서 이 질문에는 설명을 확정해 드릴 수 없어요. 선택한 문장과 가까운 내용으로 질문을 좁히거나 노트로 돌아갈 수 있어요.')).toBeVisible()
  await expect(panel.getByText('위키 자료')).toHaveCount(0)
  await expect(aiBox(panel)).toHaveCount(0)
  await expect(panel.getByText('AI 생성')).toHaveCount(0)
  await expect(panel.getByLabel('이어서 질문하기 · 질문을 바꿔 다시 물어볼 수 있어요')).toBeVisible()
  await shot(page, testInfo, 'F6-12b 근거 없음')
})

test('PC: 주제 전환 확인은 고르기 전에 보내기를 잠그고, 이 대화에서 계속하면 같은 질문을 확인 없이 보낸다(F6-20)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await firstAnswer(page, panel)
  await expect(aiBox(panel)).toBeVisible({ timeout: 10_000 })
  await mock(page, 'topic_check')
  await input(panel).fill('운영체제의 교착 상태는 뭐야?')
  await send(panel).click()
  const card = panel.getByRole('group', { name: /와 다른 질문 같아요\. 새 대화로 질문할까요\?$/ })
  await expect(card).toBeVisible({ timeout: 10_000 })
  await expect(card.getByText(/^지금 주제\(UnknownWord 는 사전에 없습\)와 다른 질문 같아요/)).toBeFocused()
  // 고르기 전에는 보내기를 잠근다(AC-3)
  await input(panel).fill('다른 초안')
  await expect(send(panel)).toHaveAttribute('aria-disabled', 'true')
  await input(panel).press('Enter')
  expect(await turnBodies(page)).toHaveLength(2)
  await shot(page, testInfo, 'F6-20 주제 전환 확인')

  await card.getByRole('button', { name: '이 대화에서 계속' }).click()
  await expect(aiBox(panel)).toHaveCount(1, { timeout: 10_000 })
  await expect(card).toBeHidden()
  const bodies = await turnBodies(page)
  expect(bodies).toHaveLength(3)
  expect(bodies[2].question).toEqual({ kind: 'free', text: '운영체제의 교착 상태는 뭐야?' })
  expect(bodies[2].reply).toMatchObject({ topic_choice: 'continue' })
  // 잠긴 동안 누른 Enter는 초안에 줄을 바꿨다(생성 중과 같은 규칙)
  await expect(input(panel)).toHaveValue('다른 초안\n')
})

test('PC: 주제 전환 확인에서 새 대화로 질문하면 앞 대화와 선택 문장을 빼고 이 질문만으로 시작한다(결정 40)', async ({ page }) => {
  await login(page)
  const panel = await openPanel(page)
  await firstAnswer(page, panel)
  await expect(aiBox(panel)).toBeVisible({ timeout: 10_000 })
  await mock(page, 'topic_check')
  await input(panel).fill('운영체제의 교착 상태는 뭐야?')
  await send(panel).click()
  await expect(panel.getByRole('button', { name: '새 대화로 질문' })).toBeVisible({ timeout: 10_000 })
  await mock(page, 'answered')
  await panel.getByRole('button', { name: '새 대화로 질문' }).click()
  await expect(aiBox(panel)).toHaveCount(1, { timeout: 10_000 })
  await expect(panel.getByText(`선택: ‘${SELECTED}’`)).toHaveCount(0)
  await expect(panel.getByRole('button', { name: /^이전 대화 보기/ })).toHaveCount(0)
  const all = await sent(page)
  const created = all.filter((r) => r.method === 'POST' && r.path === '/api/ai/conversations')
  expect(created).toHaveLength(2)
  const last = (await turnBodies(page)).at(-1)
  expect(last.question).toEqual({ kind: 'free', text: '운영체제의 교착 상태는 뭐야?' })
  expect(last.reply).toBeUndefined()
})

test('PC: 출처가 회수되면 그 답변 뒤쪽까지 가리고, 같은 질문 다시 하기는 질문 없이 대상 턴만 보낸다(F6-15b)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await firstAnswer(page, panel)
  await expect(aiBox(panel)).toBeVisible({ timeout: 10_000 })
  await panel.getByRole('button', { name: '합성 추천 질문 하나' }).click()
  await expect(panel.getByRole('button', { name: /^이전 대화 보기/ })).toBeVisible()
  await expect(aiBox(panel)).toHaveCount(1, { timeout: 10_000 })
  await callMock(page, 'revokeAgentMockSources')
  // 출처를 열면 서버가 404를 준다. 출처 보기를 닫고 대화를 다시 읽어 가린 턴을 보인다.
  await panel.getByRole('button', { name: /^\[1\] 노트/ }).click()
  const notice = panel.getByRole('status').filter({ hasText: '이 답변에 쓴 자료를 더 이상 볼 수 없어요.' })
  await expect(notice).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
  // 가린 턴의 답변·출처·추천 질문은 보이지 않는다(AC-2). 노트와 질문은 남는다
  await expect(aiBox(panel)).toHaveCount(0)
  await expect(panel.getByText('이어서 궁금할 수 있는 질문')).toHaveCount(0)
  await expect(panel.getByRole('button', { name: '합성 추천 질문 하나' })).toHaveCount(0)
  await expect(panel.getByRole('button', { name: /^\[1\]/ })).toHaveCount(0)
  await expect(panel.getByText('이 부분을 자세히 설명해 줘.')).toBeVisible()
  await expect(panel.getByText('앞 답변을 바탕으로 한 답변이라 함께 가렸어요. 필요하면 이 질문을 다시 보내 주세요.')).toBeVisible()
  // 뒤쪽 턴은 추천 질문이라 서버가 질문 글을 뺐다
  await expect(panel.getByText('가린 답변에서 고른 추천 질문이라 질문 글도 함께 가렸어요.')).toBeVisible()
  await expect(panel.getByRole('button', { name: '같은 질문 다시 하기' })).toHaveCount(1)
  await shot(page, testInfo, 'F6-15b 출처만 권한 회수')

  await notice.getByRole('button', { name: '같은 질문 다시 하기' }).click()
  await expect(aiBox(panel)).toHaveCount(1, { timeout: 10_000 })
  const last = (await turnBodies(page)).at(-1)
  expect(last.question).toBeUndefined()
  expect(typeof last.retry_of_turn_id).toBe('string')
  // 다시 묻기는 대상 턴마다 한 번이다
  await expect(panel.getByRole('button', { name: '같은 질문 다시 하기' })).toHaveCount(0)
})

test('PC: 이미 문맥에 있는 문장을 다시 고르면 묻지 않고 대화를 연다', async ({ page }) => {
  await login(page)
  const panel = await openPanel(page)
  await firstAnswer(page, panel)
  await expect(aiBox(panel)).toBeVisible({ timeout: 10_000 })
  await page.keyboard.press('Escape')
  await expect(panel).toBeHidden()
  const again = await openPanel(page)
  await expect(again.getByRole('group', { name: '새로 선택한 내용을 어떻게 쓸까요?' })).toHaveCount(0)
  await expect(aiBox(again)).toBeVisible()
})

test('PC: 다른 문장으로 새 대화를 고르면 질문 준비 화면이 그 문장으로 열린다(결정 20·36)', async ({ page }) => {
  await login(page)
  const panel = await openPanel(page)
  await firstAnswer(page, panel)
  await expect(aiBox(panel)).toBeVisible({ timeout: 10_000 })
  await openPanel(page, OTHER)
  await panel.getByRole('button', { name: '이 내용으로 새 대화' }).click()
  await expect(panel.getByText('선택한 내용으로 질문할 수 있어요.')).toBeVisible()
  await expect(panel.getByText(`선택: ‘${OTHER}’`)).toBeVisible()
  await expect(panel.getByText(`선택: ‘${SELECTED}’`)).toHaveCount(0)
  await expect(aiBox(panel)).toHaveCount(0)
})

test('모바일: 근거 일부·근거 없음·주제 전환·출처 회수는 T6g 전까지 카드 없이 질문만 보이고 보내기를 잠그지 않는다', async ({ page }) => {
  await login(page, MOBILE)
  const panel = await openPanel(page)
  await firstAnswer(page, panel, 'no_evidence')
  await expect(panel.getByText('이 부분을 자세히 설명해 줘.')).toBeVisible()
  await expect.poll(async () => (await turnBodies(page)).length).toBe(1)
  await expect(panel.getByText('참고할 수 있는 노트 자료를 찾지 못했어요.')).toHaveCount(0)
  await expect(panel.getByRole('button', { name: '중단', exact: true })).toHaveCount(0, { timeout: 10_000 })
  await mock(page, 'topic_check')
  await input(panel).fill('다른 주제 질문')
  await send(panel).click()
  await expect(panel.getByText('다른 주제 질문', { exact: true })).toBeVisible()
  await expect(panel.getByRole('button', { name: '중단', exact: true })).toHaveCount(0, { timeout: 10_000 })
  await expect(panel.getByRole('button', { name: '새 대화로 질문' })).toHaveCount(0)
  await input(panel).fill('또 다른 질문')
  await expect(send(panel)).not.toHaveAttribute('aria-disabled', 'true')
})
