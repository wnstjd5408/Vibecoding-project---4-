import { expect, test } from '@playwright/test'
import type { Locator, Page, TestInfo } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { goInApp } from './inApp.ts'

// MEG-263 CS Agent 모바일 보충 보드(T6g). MEG-262에서 새로 그린 모바일 보드 10장(캔버스 Version 102 승인)의 상태를
// 모바일 전체 높이 화면(390×844)에 가짜 API(src/api/mocks/agent.ts)로 띄운다. 모델은 부르지 않는다.
// 보드는 모두 'PC와 같은 규칙'이라 PC 시험(agentPanel·agentExceptions)과 같은 상태를 모바일에서 확인한다.
// 다시 넣기 확인(F6-14bm)과 사용 제한(F6-17m)은 agentPanel.spec.ts의 PC·모바일 공통 시험에서 본다.
// 캔버스는 위키 문구이고 구현은 노트 근거 기간 문구다(디자인 v0.2 14.5).
// AGENT_SHOT_DIR을 주면 스크린샷을 '보드 ID.png'로 저장한다(AC-1, 캔버스 보드와 나란히 PR에 붙인다).

const MOBILE = { width: 390, height: 844 }
const SELECTED = 'UnknownWord 는 사전에 없습니다.'

/* eslint-disable @typescript-eslint/no-explicit-any */
async function mock(page: Page, scenario: string, stepMs = 20) {
  await page.evaluate(async ({ scenario, stepMs }) => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    m.setAgentMockScenario(scenario, { stepMs })
  }, { scenario, stepMs })
}

async function revokeSources(page: Page) {
  await page.evaluate(async () => {
    const m: any = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    m.revokeAgentMockSources()
  })
}

async function turnBodies(page: Page): Promise<any[]> {
  return page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    return m.agentMockRequests()
      .filter((r: any) => /^\/api\/ai\/conversations\/[0-9a-f-]{36}\/turns$/.test(r.path))
      .map((r: any) => r.body)
  })
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

async function login(page: Page) {
  await page.setViewportSize(MOBILE)
  await page.goto('/login')
  await page.getByLabel('이메일').fill('member@example.test')
  await page.getByLabel('비밀번호').fill('example-password')
  await page.getByRole('button', { name: '로그인' }).click()
  await expect(page).toHaveURL(/\/quiz$/)
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    m.resetAgentMock()
  })
  await goInApp(page, '/notes/11')
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
}

async function openPanel(page: Page): Promise<Locator> {
  await selectText(page, SELECTED)
  await page.getByRole('button', { name: 'AI에게 질문', exact: true }).click()
  const panel = page.getByRole('dialog', { name: 'AI에게 질문' })
  await expect(panel).toBeVisible()
  // 모바일 전체 높이 화면(모달)이다
  await expect(panel.getByRole('button', { name: '노트로 돌아가기' }).first()).toBeVisible()
  return panel
}

const input = (panel: Locator) => panel.getByRole('textbox')
const send = (panel: Locator) => panel.getByRole('button', { name: '보내기' })
const stop = (panel: Locator) => panel.getByRole('button', { name: '중단', exact: true })
const aiBox = (panel: Locator) => panel.getByRole('group', { name: 'AI 생성' })

async function sendFree(panel: Locator, text: string) {
  await input(panel).fill(text)
  await send(panel).click()
}

async function shot(page: Page, testInfo: TestInfo, name: string) {
  const body = await page.screenshot()
  await testInfo.attach(name, { body, contentType: 'image/png' })
  const dir = process.env.AGENT_SHOT_DIR
  if (dir) writeFileSync(join(dir, `${name.split(' ')[0]}.png`), body)
}

// 페이지 전체가 옆으로 넘치지 않는다(4절)
async function noHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
}

test('모바일: 단계 이벤트 전에는 \'답변을 준비하고 있어요.\'를 보이고 보내기를 잠근다(F6-2m)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'answered', 3000)
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(aiBox(panel).getByRole('status').filter({ hasText: '답변을 준비하고 있어요.' })).toBeVisible()
  await expect(panel.getByText('질문 이해하기', { exact: true })).toHaveCount(0)
  await input(panel).fill('그럼 멱등성은 뭐야?')
  await expect(panel.getByLabel('이어서 질문하기 · 입력한 내용은 그대로 남아요')).toBeVisible()
  await expect(stop(panel)).toBeVisible()
  await expect(send(panel)).toHaveAttribute('aria-disabled', 'true')
  await shot(page, testInfo, 'F6-2m 준비 중')
})

test('모바일: 오래 걸리면 단계 아래에 안내만 더하고 질문을 다시 보내지 않는다(F6-19m)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'delayed', 800)
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(panel.getByText('평소보다 오래 걸리고 있어요.', { exact: true })).toBeVisible({ timeout: 10_000 })
  await expect(panel.getByText('계속 기다리거나 입력 칸의 중단 버튼으로 멈출 수 있어요.')).toBeVisible()
  await expect(panel.getByRole('status').filter({ hasText: '지금 단계: 설명 정리하기. 평소보다 오래 걸리고 있어요.' })).toHaveCount(1)
  // 노트 근거 기간 문구(14.5)
  await expect(panel.getByText('노트에서 자료 찾기')).toBeVisible()
  await expect(panel.getByText('위키에서 자료 찾기')).toHaveCount(0)
  await expect(stop(panel)).toBeVisible()
  await input(panel).fill('그럼 멱등성은 뭐야?')
  await shot(page, testInfo, 'F6-19m 응답 지연')
  await expect(aiBox(panel)).toBeVisible({ timeout: 10_000 })
  expect(await turnBodies(page)).toHaveLength(1)
})

test('모바일: 긴 대화에서 위를 읽는 중이면 끌어내리지 않고 \'새 답변 보기\'를 띄운다(F6-10m)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'answered', 20)
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(aiBox(panel)).toBeVisible({ timeout: 10_000 })
  await sendFree(panel, '그럼 멱등성은 뭐야?')
  await expect(aiBox(panel)).toHaveCount(1, { timeout: 10_000 })
  await expect(panel.getByText('그럼 멱등성은 뭐야?', { exact: true })).toBeVisible()
  await panel.getByRole('button', { name: /^이전 대화 보기/ }).click()
  const log = panel.getByRole('log', { name: '대화' })
  await expect(log.getByRole('group', { name: 'AI 생성' })).toHaveCount(2)
  await mock(page, 'answered', 1500)
  await sendFree(panel, '같은 키를 다시 쓰면 안 되는 때도 있나요?')
  await expect(panel.getByText('질문 이해하기', { exact: true })).toBeVisible()
  await log.evaluate((element) => { element.scrollTop = 0 })
  const newAnswer = panel.getByRole('button', { name: '새 답변 보기' })
  await expect(newAnswer).toBeVisible()
  await input(panel).fill('같은 키를 다시 쓰면 안 되는 때도 있나요?')
  await shot(page, testInfo, 'F6-10m 긴 대화')
  // 답변이 와도 읽던 위치를 옮기지 않는다
  await expect(log.getByRole('group', { name: 'AI 생성' })).toHaveCount(3, { timeout: 10_000 })
  expect(await log.evaluate((element) => element.scrollTop)).toBe(0)
  await newAnswer.click()
  await expect(log.getByText('같은 키를 다시 쓰면 안 되는 때도 있나요?', { exact: true })).toBeInViewport()
  await expect(newAnswer).toHaveCount(0)
})

test('모바일: 주제 전환 확인은 고르기 전에 보내기를 잠그고, 이 대화에서 계속하면 같은 질문을 보낸다(F6-20m)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'answered')
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(aiBox(panel)).toBeVisible({ timeout: 10_000 })
  await mock(page, 'topic_check')
  await sendFree(panel, '운영체제의 교착 상태는 뭐야?')
  const card = panel.getByRole('group', { name: /와 다른 질문 같아요\. 새 대화로 질문할까요\?$/ })
  await expect(card).toBeVisible({ timeout: 10_000 })
  await expect(card.getByText(/^지금 주제\(UnknownWord 는 사전에 없습\)와 다른 질문 같아요/)).toBeFocused()
  await expect(card.getByRole('button', { name: '새 대화로 질문' })).toBeVisible()
  await expect(panel.getByRole('button', { name: /^이전 대화 보기/ })).toBeVisible()
  await expect(panel.getByRole('button', { name: '노트로 돌아가기' })).toHaveCount(2)
  await expect(panel.getByLabel('이어서 질문하기', { exact: true })).toBeVisible()
  await shot(page, testInfo, 'F6-20m 주제 전환 확인')
  // 고르기 전에는 보내기를 잠근다(결정 38)
  await input(panel).fill('다른 초안')
  await expect(send(panel)).toHaveAttribute('aria-disabled', 'true')
  await send(panel).click({ force: true })
  expect(await turnBodies(page)).toHaveLength(2)

  await mock(page, 'answered')
  await card.getByRole('button', { name: '이 대화에서 계속' }).click()
  await expect(aiBox(panel)).toHaveCount(1, { timeout: 10_000 })
  await expect(card).toBeHidden()
  const bodies = await turnBodies(page)
  expect(bodies).toHaveLength(3)
  expect(bodies[2].question).toEqual({ kind: 'free', text: '운영체제의 교착 상태는 뭐야?' })
  expect(bodies[2].reply).toMatchObject({ topic_choice: 'continue' })
  await expect(input(panel)).toHaveValue('다른 초안')
})

test('모바일: 근거 일부만 확인은 확인하지 못한 부분을 따로 보인다(F6-12m)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'partial')
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  const box = aiBox(panel)
  await expect(box.getByText('합성 부분 답변 문장입니다')).toBeVisible({ timeout: 10_000 })
  await expect(box.getByRole('heading', { name: '확인하지 못한 부분' })).toBeVisible()
  await expect(box.getByText('합성 한계 문장입니다.')).toBeVisible()
  await expect(panel.getByText('참고 자료')).toBeVisible()
  await expect(panel.getByRole('button', { name: /^\[1\] 노트 · / })).toBeVisible()
  await expect(panel.getByLabel('이어서 질문하기 · 더 구체적으로 물어볼 수 있어요')).toBeVisible()
  await expect(panel.getByRole('button', { name: '노트로 돌아가기' })).toHaveCount(2)
  await shot(page, testInfo, 'F6-12m 근거 일부만 확인')
  await noHorizontalOverflow(page)
})

test('모바일: 근거가 없으면 AI 생성 표시 없이 서버 고정 안내(노트 근거 문구, 문장 A)만 보인다(F6-12bm)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'no_evidence')
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  const notice = panel.getByRole('status').filter({ hasText: '참고할 수 있는 노트 자료를 찾지 못했어요.' })
  await expect(notice).toBeVisible({ timeout: 10_000 })
  await expect(notice.getByText('그래서 이 질문에는 설명을 확정해 드릴 수 없어요. 선택한 문장과 가까운 내용으로 질문을 좁히거나 노트로 돌아갈 수 있어요.')).toBeVisible()
  await expect(panel.getByText('위키 자료')).toHaveCount(0)
  await expect(aiBox(panel)).toHaveCount(0)
  await expect(panel.getByText('AI 생성')).toHaveCount(0)
  await expect(panel.getByLabel('이어서 질문하기 · 질문을 바꿔 다시 물어볼 수 있어요')).toBeVisible()
  await expect(panel.getByRole('button', { name: '노트로 돌아가기' })).toHaveCount(2)
  await shot(page, testInfo, 'F6-12bm 근거 없음')
  // 안내 아래 '노트로 돌아가기'는 노트로 돌아간다(대화는 남는다)
  await panel.getByRole('button', { name: '노트로 돌아가기' }).last().click()
  await expect(panel).toBeHidden()
})

test('모바일: 출처가 회수되면 그 답변 뒤쪽까지 가리고, 같은 질문 다시 하기는 질문 없이 대상 턴만 보낸다(F6-15bm)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'answered')
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(aiBox(panel)).toBeVisible({ timeout: 10_000 })
  await sendFree(panel, '그럼 멱등성은 뭐야?')
  await expect(panel.getByRole('button', { name: /^이전 대화 보기/ })).toBeVisible()
  await expect(aiBox(panel)).toHaveCount(1, { timeout: 10_000 })
  await revokeSources(page)
  // 출처를 열면 서버가 404를 준다. 출처 보기를 닫고 대화를 다시 읽어 가린 턴을 보인다
  await panel.getByRole('button', { name: /^\[1\] 노트/ }).click()
  const notice = panel.getByRole('status').filter({ hasText: '이 답변에 쓴 자료를 더 이상 볼 수 없어요.' })
  await expect(notice).toBeVisible({ timeout: 10_000 })
  await expect(notice.getByText('그래서 이 답변과 출처, 그리고 이 답변을 바탕으로 한 뒤쪽 답변과 추천 질문을 함께 가렸어요. 가린 내용은 다음 질문에 쓰지 않아요.')).toBeVisible()
  await expect(notice.getByText('노트와 내 질문은 그대로 있어요. 같은 질문을 다시 하면 지금 볼 수 있는 자료로 다시 찾아봐요.')).toBeVisible()
  // 가린 턴의 답변·출처·추천 질문은 보이지 않는다. 노트와 질문은 남는다
  await expect(aiBox(panel)).toHaveCount(0)
  await expect(panel.getByText('이어서 궁금할 수 있는 질문')).toHaveCount(0)
  await expect(panel.getByRole('button', { name: /^\[1\]/ })).toHaveCount(0)
  await expect(panel.getByText('이 부분을 자세히 설명해 줘.')).toBeVisible()
  await expect(panel.getByText('그럼 멱등성은 뭐야?', { exact: true })).toBeVisible()
  await expect(panel.getByText('앞 답변을 바탕으로 한 답변이라 함께 가렸어요. 필요하면 이 질문을 다시 보내 주세요.')).toBeVisible()
  await expect(panel.getByRole('button', { name: '같은 질문 다시 하기' })).toHaveCount(1)
  await shot(page, testInfo, 'F6-15bm 출처만 권한 회수')

  await mock(page, 'answered')
  await notice.getByRole('button', { name: '같은 질문 다시 하기' }).click()
  await expect(aiBox(panel)).toHaveCount(1, { timeout: 10_000 })
  const last = (await turnBodies(page)).at(-1)
  expect(last.question).toBeUndefined()
  expect(typeof last.retry_of_turn_id).toBe('string')
  await expect(panel.getByRole('button', { name: '같은 질문 다시 하기' })).toHaveCount(0)
})

test('모바일: 그림을 그리지 못해도 본문과 출처는 남는다(F6-16m, T6b 실패 카드)', async ({ page }, testInfo) => {
  await login(page)
  await page.route(/mermaid/, (route) => route.abort())
  const panel = await openPanel(page)
  await mock(page, 'answered')
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  const answer = aiBox(panel)
  await expect(answer.getByText('오류: 그림을 표시하지 못했어요')).toBeVisible({ timeout: 10_000 })
  await expect(answer.getByText('합성 답변 첫 절입니다')).toBeVisible()
  await expect(answer.getByText('합성 답변 둘째 절입니다')).toBeVisible()
  await expect(panel.getByRole('button', { name: /^\[1\] 노트 · / })).toBeVisible()
  await answer.getByText('오류: 그림을 표시하지 못했어요').scrollIntoViewIfNeeded()
  await shot(page, testInfo, 'F6-16m 그림 표시 실패')
  await noHorizontalOverflow(page)
})

// --- 노출 중단(MEG-259·MEG-260 규칙을 모바일에서도 그대로) ---

test('모바일: 새 질문 입구가 닫히면 마지막 주제 전환 카드의 선택지와 입력 칸을 숨긴다', async ({ page }) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'answered')
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(aiBox(panel)).toBeVisible({ timeout: 10_000 })
  await mock(page, 'topic_check')
  await sendFree(panel, '운영체제의 교착 상태는 뭐야?')
  const card = panel.getByRole('group', { name: /와 다른 질문 같아요\. 새 대화로 질문할까요\?$/ })
  await expect(card.getByRole('button', { name: '이 대화에서 계속' })).toBeVisible({ timeout: 10_000 })
  // 카드가 마지막 항목인 채로 입구를 닫는다(다른 화면에서 받은 503과 같다, agent/availability.ts)
  await page.evaluate(async () => {
    const a = await import(/* @vite-ignore */ '/src/agent/availability.ts')
    a.closeAgentEntry()
  })
  await expect(panel.getByText('지금은 새 질문을 받을 수 없어요. 이 대화와 출처는 계속 볼 수 있어요.')).toBeVisible()
  await expect(card).toBeVisible()
  await expect(card.getByRole('button', { name: '이 대화에서 계속' })).toHaveCount(0)
  await expect(card.getByRole('button', { name: '새 대화로 질문' })).toHaveCount(0)
  await expect(panel.getByRole('textbox')).toHaveCount(0)
})

test('모바일: 503을 받으면 주제 전환 카드 뒤에 안내를 보이고 입력 칸을 숨긴다', async ({ page }) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'answered')
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(aiBox(panel)).toBeVisible({ timeout: 10_000 })
  await mock(page, 'topic_check')
  await sendFree(panel, '운영체제의 교착 상태는 뭐야?')
  await expect(panel.getByRole('button', { name: '이 대화에서 계속' })).toBeVisible({ timeout: 10_000 })
  await mock(page, 'service_unavailable')
  await panel.getByRole('button', { name: '이 대화에서 계속' }).click()
  await expect(panel.getByText('오류: 지금은 새 질문을 받을 수 없어요.')).toBeVisible({ timeout: 10_000 })
  await expect(panel.getByRole('button', { name: '이 대화에서 계속' })).toHaveCount(0)
  await expect(panel.getByRole('button', { name: '새 대화로 질문' })).toHaveCount(0)
  await expect(panel.getByRole('textbox')).toHaveCount(0)
})

test('모바일: 503 뒤에는 출처 회수 안내에 같은 질문 다시 하기를 두지 않는다', async ({ page }) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'answered')
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(aiBox(panel)).toBeVisible({ timeout: 10_000 })
  await mock(page, 'service_unavailable')
  await sendFree(panel, '닫힌 뒤 보낸 질문')
  await expect(panel.getByText('오류: 지금은 새 질문을 받을 수 없어요.')).toBeVisible({ timeout: 10_000 })
  await revokeSources(page)
  // '이전 대화 보기'는 대화를 다시 읽는다(E28). 출처가 회수됐으면 가린 턴이 온다
  await panel.getByRole('button', { name: /^이전 대화 보기/ }).click()
  const notice = panel.getByRole('status').filter({ hasText: '이 답변에 쓴 자료를 더 이상 볼 수 없어요.' })
  await expect(notice).toBeVisible({ timeout: 10_000 })
  await expect(notice.getByText('노트와 내 질문은 그대로 있어요.', { exact: true })).toBeVisible()
  await expect(panel.getByRole('button', { name: '같은 질문 다시 하기' })).toHaveCount(0)
  await expect(panel.getByRole('textbox')).toHaveCount(0)
})

test('모바일: 다시 넣기 확인 카드가 열려 있으면 뒤로(Esc)는 카드만 닫는다(F6-14bm)', async ({ page }) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'answered', 1500)
  await sendFree(panel, '중단할 질문')
  await stop(panel).click()
  await expect(panel.getByText('응답을 중단했어요.')).toBeVisible()
  await input(panel).fill('쓰던 초안')
  await panel.getByRole('button', { name: '중단한 질문 다시 넣기' }).click()
  const confirm = panel.getByRole('group', { name: '쓰던 내용을 중단한 질문으로 바꿀까요?' })
  await expect(confirm).toBeVisible()
  await expect(confirm.getByText('쓰던 내용을 중단한 질문으로 바꿀까요?')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(panel).toBeVisible()
  await expect(confirm).toHaveCount(0)
  await expect(input(panel)).toHaveValue('쓰던 초안')
  // Android 뒤로 버튼·제스처는 keydown 없이 dialog에 닫기 요청(cancel)만 보낸다. 이때도 카드만 닫는다
  await panel.getByRole('button', { name: '중단한 질문 다시 넣기' }).click()
  await expect(confirm).toBeVisible()
  await page.evaluate(() => (document.querySelector('dialog:modal') as any).requestClose())
  await expect(confirm).toHaveCount(0)
  await expect(panel).toBeVisible()
  await expect(input(panel)).toHaveValue('쓰던 초안')
  // 카드가 없으면 뒤로 가기는 노트로 돌아간다(대화와 초안은 남는다)
  await page.evaluate(() => (document.querySelector('dialog:modal') as any).requestClose())
  await expect(panel).toBeHidden()
})
