import { expect, test } from '@playwright/test'
import type { Locator, Page, TestInfo } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { goInApp } from './inApp.ts'

// MEG-258 CS Agent 'AI에게 질문' 기본 흐름 화면(T6c). playwright.config.ts가 VITE_API_MOCK=true로 개발 서버를 띄우므로
// 가짜 API(src/api/mocks/agent.ts)가 E27~E32와 E29의 SSE를 흉내 낸다. 모델은 부르지 않는다.
// 진입점은 T6e(MEG-259) 전까지 개발 서버의 ?cs-agent=1에서만 열린다(src/agent/preview.ts).
// 각 상태의 스크린샷은 시험 결과에 붙인다(AC-1, 캔버스 보드와 나란히 PR에 올린다).

const PC = { width: 1280, height: 800 }
const MOBILE = { width: 390, height: 844 }
const SELECTED = 'UnknownWord 는 사전에 없습니다.'

/* eslint-disable @typescript-eslint/no-explicit-any */
async function mock(page: Page, scenario: string, stepMs?: number) {
  await page.evaluate(async ({ scenario, stepMs }) => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    m.setAgentMockScenario(scenario, stepMs === undefined ? {} : { stepMs })
  }, { scenario, stepMs })
}

async function requests(page: Page): Promise<string[]> {
  return page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    return m.agentMockRequests().map((r: any) => `${r.method} ${r.path.replace(/[0-9a-f-]{36}/g, ':id')}`)
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

async function login(page: Page, viewport = PC, path = '/notes/11?cs-agent=1') {
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
  await goInApp(page, path)
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
}

// 선택 → 'AI에게 질문' → 질문 준비 화면(F6-1·F6-1m)
async function openPanel(page: Page): Promise<Locator> {
  await selectText(page, SELECTED)
  await page.getByRole('button', { name: 'AI에게 질문', exact: true }).click()
  const panel = page.getByRole('dialog', { name: 'AI에게 질문' })
  await expect(panel).toBeVisible()
  return panel
}

const input = (panel: Locator) => panel.getByRole('textbox')
const send = (panel: Locator) => panel.getByRole('button', { name: '보내기' })
const stop = (panel: Locator) => panel.getByRole('button', { name: '중단', exact: true })

// AGENT_SHOT_DIR을 주면 같은 스크린샷을 '보드 ID.png'로도 저장한다(PR에 목업 보드와 나란히 붙일 때 쓴다).
async function shot(page: Page, testInfo: TestInfo, name: string) {
  const body = await page.screenshot()
  await testInfo.attach(name, { body, contentType: 'image/png' })
  const dir = process.env.AGENT_SHOT_DIR
  if (dir) writeFileSync(join(dir, `${name.split(' ')[0]}.png`), body)
}

async function sendFree(panel: Locator, text: string) {
  await input(panel).fill(text)
  await send(panel).click()
}

test('플래그가 없으면(기본) 노트 선택 버튼은 그대로 \'AI 설명\'이고 새 입구가 보이지 않는다', async ({ page }) => {
  await login(page, PC, '/notes/11')
  await selectText(page, SELECTED)
  await expect(page.getByRole('button', { name: 'AI 설명', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'AI에게 질문', exact: true })).toHaveCount(0)
})

for (const [device, viewport] of [['PC', PC], ['모바일', MOBILE]] as const) {
  test(`${device}: 질문 준비 → 추론 단계(노트 근거 문구) → 답변·출처·추천 질문 → 그림`, async ({ page }, testInfo) => {
    await login(page, viewport)
    const panel = await openPanel(page)
    // F6-1: 선택만으로는 아무 요청도 보내지 않는다
    expect(await requests(page)).toEqual([])
    // 주제는 서버 규칙(topic_label_of)대로 선택 문장 앞 20자다
    await expect(panel.getByText('현재 주제: UnknownWord 는 사전에 없습', { exact: true })).toBeVisible()
    await expect(panel.getByText('선택한 내용으로 질문할 수 있어요.')).toBeVisible()
    await expect(panel.getByRole('group', { name: '빠른 질문' }).getByRole('button')).toHaveText(['자세히 설명', '쉽게 풀어 줘', '예시로 보여 줘'])
    await expect(panel.getByText(`선택: ‘${SELECTED}’`)).toBeVisible()
    await expect(panel.getByLabel('질문하기')).toBeVisible()
    await expect(send(panel)).toHaveAttribute('aria-disabled', 'true')
    await shot(page, testInfo, `${device === 'PC' ? 'F6-1' : 'F6-1m'} 질문 준비`)

    // F6-2b·F6-2bm: 끝낸 단계와 지금 단계만, 노트 근거 기간 문구(AC-2)
    await mock(page, 'answered', 700)
    await panel.getByRole('button', { name: '자세히 설명' }).click()
    await expect(panel.getByText('이 부분을 자세히 설명해 줘.')).toBeVisible()
    await expect(panel.getByText('완료 · 노트 문단 3개를 확인했어요')).toBeVisible()
    await expect(panel.getByText('노트에서 자료 찾기')).toBeVisible()
    await expect(panel.getByText('위키에서 자료 찾기')).toHaveCount(0)
    await expect(stop(panel)).toBeVisible()
    await expect(send(panel)).toHaveAttribute('aria-disabled', 'true')
    // 생성 중에 쓰는 초안은 그대로 남는다
    await input(panel).fill('그럼 멱등성은 뭐야?')
    await expect(panel.getByLabel('이어서 질문하기 · 입력한 내용은 그대로 남아요')).toBeVisible()
    await shot(page, testInfo, `${device === 'PC' ? 'F6-2b' : 'F6-2bm'} 추론 단계`)

    // F6-3·F6-5: 답변, 참고 자료(노트 근거 기간 출처 카드), 추천 질문. F6-18·F6-18m: 그림은 관련 절 바로 아래
    const answer = panel.getByRole('group', { name: 'AI 생성' })
    await expect(answer.getByText('합성 답변 첫 절입니다')).toBeVisible({ timeout: 10_000 })
    await expect(panel.getByRole('button', { name: '[1] 노트 · 예시 노트 · 요청이 서버까지 가는 길 · 요청 흐름' })).toBeVisible()
    await expect(panel.getByText('이어서 궁금할 수 있는 질문')).toBeVisible()
    await expect(panel.getByRole('button', { name: '합성 추천 질문 하나' })).toBeVisible()
    await expect(answer.locator('figure img')).toBeVisible()
    await expect(answer.getByText('노트 문단')).toBeVisible()
    await expect(panel.getByRole('button', { name: '다시 답하기' })).toHaveCount(0)
    await expect(input(panel)).toHaveValue('그럼 멱등성은 뭐야?')
    await expect(send(panel)).not.toHaveAttribute('aria-disabled', 'true')
    await shot(page, testInfo, `${device === 'PC' ? 'F6-3·F6-18' : 'F6-5·F6-18m'} 답변과 그림`)
    // 패널 아래쪽(참고 자료·추천 질문)
    await panel.getByRole('button', { name: '합성 추천 질문 하나' }).scrollIntoViewIfNeeded()
    await shot(page, testInfo, `${device === 'PC' ? 'F6-3-bottom' : 'F6-5-bottom'} 답변 아래쪽`)
    // 모바일: 그림 영역만 옆으로 스크롤하고 페이지 전체는 넘치지 않는다
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)

    // F6-7·F6-7m: 후속 답변. 앞 턴은 '이전 대화 보기' 뒤로 접힌다
    await mock(page, 'answered', 60)
    await panel.getByRole('button', { name: '합성 추천 질문 하나' }).click()
    await expect(panel.getByRole('button', { name: /^이전 대화 보기 · ‘UnknownWord 는 사전에 없습’ 자세히 설명$/ })).toBeVisible()
    await expect(panel.getByText('합성 추천 질문 하나', { exact: true })).toBeVisible()
    await expect(panel.getByRole('group', { name: 'AI 생성' })).toHaveCount(1, { timeout: 10_000 })
    await expect(panel.getByLabel('이어서 질문하기')).toBeVisible()
    await shot(page, testInfo, `${device === 'PC' ? 'F6-7' : 'F6-7m'} 후속 답변`)
    const e29 = (await requests(page)).filter((line) => line === 'POST /api/ai/conversations/:id/turns')
    expect(e29).toHaveLength(2)
  })

  test(`${device}: 출처 보기와 대화로 돌아가기(초안·대화 유지)`, async ({ page }, testInfo) => {
    await login(page, viewport)
    const panel = await openPanel(page)
    await mock(page, 'answered', 30)
    await panel.getByRole('button', { name: '자세히 설명' }).click()
    await expect(panel.getByRole('group', { name: 'AI 생성' }).getByText('합성 답변 첫 절입니다')).toBeVisible({ timeout: 10_000 })
    await input(panel).fill('그럼 멱등성은 뭐야?')
    await panel.getByRole('button', { name: '출처 1 보기: 예시 노트 · 요청이 서버까지 가는 길' }).first().click()
    const source = page.getByRole('dialog', { name: '출처 1' })
    await expect(source).toBeVisible()
    if (device === 'PC') {
      // F6-4: 노트 자리에 인용 당시 문단, 패널에는 출처 카드와 노트 근거 안내(14.5 노트 근거 기간). '노트 열기'는 없다
      const doc = page.getByRole('article', { name: '출처 1' })
      await expect(doc.getByRole('heading', { level: 1, name: '예시 노트 · 요청이 서버까지 가는 길' })).toBeVisible()
      await expect(doc.getByText('CS 노트')).toBeVisible()
      await expect(doc.getByRole('heading', { name: '요청 흐름' })).toBeVisible()
      await expect(doc.getByText('합성 근거 문단 하나입니다.', { exact: false })).toBeVisible()
      await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeHidden()
      await expect(source.getByText('왼쪽에 인용한 노트 문단을 표시했어요. 질문할 때 선택한 문장은 근거로 쓰지 않았어요.')).toBeVisible()
      await expect(source.getByText('대화는 그대로 있어요')).toBeVisible()
      await expect(source.getByText('질문: 이 부분을 자세히 설명해 줘.')).toBeVisible()
      await expect(source.getByText('답변에서 인용한 부분: “합성 답변 첫 절입니다 [1]”')).toBeVisible()
    } else {
      // F6-9: 대화 화면 대신 인용 문단. 돌아가면 답변 위치와 초안이 그대로다
      await expect(source.getByRole('heading', { level: 2, name: '예시 노트 · 요청이 서버까지 가는 길' })).toBeVisible()
      await expect(source.getByText('돌아가면 읽던 답변 위치와 입력 초안이 그대로 있어요.')).toBeVisible()
    }
    await expect(page.getByRole('button', { name: '노트 열기' })).toHaveCount(0)
    await expect(input(source)).toHaveValue('그럼 멱등성은 뭐야?')
    await shot(page, testInfo, `${device === 'PC' ? 'F6-4' : 'F6-9'} 출처 보기`)
    expect(await requests(page)).toContain('GET /api/ai/turns/:id/sources/1')
    await source.getByRole('button', { name: '대화로 돌아가기' }).click()
    const back = page.getByRole('dialog', { name: 'AI에게 질문' })
    await expect(back.getByRole('group', { name: 'AI 생성' })).toBeVisible()
    await expect(input(back)).toHaveValue('그럼 멱등성은 뭐야?')
    if (device === 'PC') await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
  })

  test(`${device}: 중단하면 받다 만 답변은 숨기고 질문을 다시 넣을 수 있다`, async ({ page }, testInfo) => {
    await login(page, viewport)
    const panel = await openPanel(page)
    await mock(page, 'answered', 1500)
    await sendFree(panel, '재시도하면 안 되는 오류도 있나요?')
    await expect(stop(panel)).toBeVisible()
    await expect(panel.getByText('질문 이해하기', { exact: true })).toBeVisible()
    // 생성 중에는 '새 대화'를 잠근다(결정 11, PC 머리에만 있다)
    if (device === 'PC') await expect(panel.getByRole('button', { name: '새 대화' })).toHaveAttribute('aria-disabled', 'true')
    await stop(panel).click()
    await expect(panel.getByText('응답을 중단했어요.')).toBeVisible()
    await expect(panel.getByText('중단한 답변은 보여 주지 않아요.')).toBeVisible()
    await expect(panel.getByRole('group', { name: 'AI 생성' })).toHaveCount(0)
    await expect(stop(panel)).toHaveCount(0)
    if (device === 'PC') await expect(panel.getByRole('button', { name: '새 대화' })).not.toHaveAttribute('aria-disabled', 'true')
    await shot(page, testInfo, `${device === 'PC' ? 'F6-14' : 'F6-14m'} 중단`)
    // 입력 칸이 비어 있으면 확인 없이 넣는다
    await panel.getByRole('button', { name: '중단한 질문 다시 넣기' }).click()
    await expect(input(panel)).toHaveValue('재시도하면 안 되는 오류도 있나요?')
    if (device === 'PC') {
      // 쓰던 초안이 있으면 바꾸기 전에 묻는다(F6-14b). 취소하면 초안을 그대로 둔다
      await input(panel).fill('그럼 멱등성은 뭐야?')
      await panel.getByRole('button', { name: '중단한 질문 다시 넣기' }).click()
      const confirm = panel.getByRole('group', { name: '쓰던 내용을 중단한 질문으로 바꿀까요?' })
      await expect(confirm).toBeVisible()
      await expect(confirm.getByText('‘그럼 멱등성은 뭐야?’')).toBeVisible()
      await expect(confirm.getByText('‘재시도하면 안 되는 오류도 있나요?’')).toBeVisible()
      await shot(page, testInfo, 'F6-14b 다시 넣기 확인')
      await confirm.getByRole('button', { name: '취소' }).click()
      await expect(input(panel)).toHaveValue('그럼 멱등성은 뭐야?')
      await panel.getByRole('button', { name: '중단한 질문 다시 넣기' }).click()
      await panel.getByRole('button', { name: '바꾸기' }).click()
      await expect(input(panel)).toHaveValue('재시도하면 안 되는 오류도 있나요?')
    }
    expect(await requests(page)).toContain('POST /api/ai/turns/:id/cancel')
  })

  test(`${device}: 요청 실패 뒤 질문과 초안이 남고, 다시 시도는 같은 질문으로 확인 뒤 보낸다`, async ({ page }, testInfo) => {
    await login(page, viewport)
    const panel = await openPanel(page)
    await mock(page, 'error', 300)
    await sendFree(panel, '재시도하면 안 되는 오류도 있나요?')
    await input(panel).fill('쓰던 초안')
    const alert = panel.getByRole('alert')
    await expect(alert.getByText('오류: 답변을 가져오지 못했어요. 질문은 보관했어요.')).toBeVisible({ timeout: 10_000 })
    // AC-3: 질문과 쓰던 초안이 남는다. 다시 시도 전에는 보내기를 쓸 수 없다
    await expect(panel.getByText('재시도하면 안 되는 오류도 있나요?', { exact: true })).toBeVisible()
    await expect(input(panel)).toHaveValue('쓰던 초안')
    await expect(panel.getByLabel('이어서 질문하기 · 다시 시도하기 전에는 보내기를 쓸 수 없어요')).toBeVisible()
    await expect(send(panel)).toHaveAttribute('aria-disabled', 'true')
    await shot(page, testInfo, `${device === 'PC' ? 'F6-6p' : 'F6-6'} 요청 실패`)
    // 다시 시도: E30으로 앞 턴을 먼저 확인하고, failed면 새 키로 같은 질문을 보낸다(결정 41, 추론 단계 화면 재사용)
    await mock(page, 'answered', 200)
    await alert.getByRole('button', { name: '다시 시도' }).click()
    await expect(panel.getByText('질문 이해하기', { exact: true })).toBeVisible()
    await expect(panel.getByRole('group', { name: 'AI 생성' })).toBeVisible({ timeout: 10_000 })
    await expect(input(panel)).toHaveValue('쓰던 초안')
    const lines = await requests(page)
    expect(lines.filter((line) => line === 'POST /api/ai/conversations/:id/turns')).toHaveLength(2)
    expect(lines).toContain('GET /api/ai/turns/:id')
  })

  test(`${device}: 사용 제한 뒤 질문을 입력 칸에 남기고, 다시 확인은 서버를 부르지 않고 잠금만 푼다`, async ({ page }, testInfo) => {
    await login(page, viewport)
    const panel = await openPanel(page)
    await mock(page, 'ai_limit_reached')
    await sendFree(panel, '재시도 간격은 어떻게 정하나요?')
    // AC-3: 보내려던 질문이 입력 칸에 돌아온다(F6-17 '쓰던 내용은 아래 칸에 남겨 두었어요')
    await expect(input(panel)).toHaveValue('재시도 간격은 어떻게 정하나요?')
    if (device === 'PC') {
      const alert = panel.getByRole('alert')
      await expect(alert.getByText('오류: 지금은 AI 답변을 요청할 수 없어요.')).toBeVisible()
      await expect(alert.getByText('쓰던 내용은 아래 칸에 남겨 두었어요. 노트는 계속 읽을 수 있어요.')).toBeVisible()
      await expect(panel.getByLabel('이어서 질문하기 · 다시 확인하기 전에는 보내기를 쓸 수 없어요')).toBeVisible()
      await expect(send(panel)).toHaveAttribute('aria-disabled', 'true')
      await shot(page, testInfo, 'F6-17 사용 제한')
      const before = (await requests(page)).length
      await alert.getByRole('button', { name: '다시 확인' }).click()
      await expect(panel.getByRole('alert')).toHaveCount(0)
      await expect(send(panel)).not.toHaveAttribute('aria-disabled', 'true')
      expect((await requests(page)).length).toBe(before)
    } else {
      // 모바일 사용 제한 보드가 없어(결정 8) 안내 카드는 그리지 않는다(MEG-263). 질문은 입력 칸에 남는다.
      await expect(panel.getByText('오류: 지금은 AI 답변을 요청할 수 없어요.')).toHaveCount(0)
      await shot(page, testInfo, 'mobile-limit 모바일 사용 제한(보드 없음, 카드 미표시)')
    }
  })
}

test('PC: 오래 걸리면 안내만 더하고 질문을 다시 보내지 않는다(F6-19)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'delayed', 800)
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(panel.getByText('평소보다 오래 걸리고 있어요.', { exact: true })).toBeVisible({ timeout: 10_000 })
  await expect(panel.getByText('계속 기다리거나 입력 칸의 중단 버튼으로 멈출 수 있어요.')).toBeVisible()
  await expect(panel.getByRole('status').filter({ hasText: '지금 단계: 설명 정리하기. 평소보다 오래 걸리고 있어요.' })).toHaveCount(1)
  await expect(stop(panel)).toBeVisible()
  await shot(page, testInfo, 'F6-19 응답 지연')
  await expect(panel.getByRole('group', { name: 'AI 생성' })).toBeVisible({ timeout: 10_000 })
  expect((await requests(page)).filter((line) => line === 'POST /api/ai/conversations/:id/turns')).toHaveLength(1)
})

test('PC: 단계 이벤트 전에는 \'답변을 준비하고 있어요.\'를 보인다(F6-2)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'answered', 3000)
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(panel.getByRole('group', { name: 'AI 생성' }).getByText('답변을 준비하고 있어요.')).toBeVisible()
  await shot(page, testInfo, 'F6-2 준비 중')
})

test('연결이 끊겨도 단계 화면을 유지하다가 E30으로 결과를 받는다(화면 목록 5번)', async ({ page }) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'disconnect', 100)
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(panel.getByText('완료 · 노트 문단 3개를 확인했어요')).toBeVisible()
  await expect(panel.getByRole('group', { name: 'AI 생성' }).getByText('합성 답변 첫 절입니다')).toBeVisible({ timeout: 10_000 })
  await expect(panel.getByRole('alert')).toHaveCount(0)
  const lines = await requests(page)
  expect(lines.filter((line) => line === 'POST /api/ai/conversations/:id/turns')).toHaveLength(1)
  expect(lines).toContain('GET /api/ai/turns/:id')
})

test('PC: 긴 대화에서 위를 읽는 중이면 끌어내리지 않고 \'새 답변 보기\'를 띄운다(F6-10)', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 640 })
  await login(page, { width: 1280, height: 640 })
  const panel = await openPanel(page)
  await mock(page, 'answered', 20)
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(panel.getByRole('group', { name: 'AI 생성' })).toBeVisible({ timeout: 10_000 })
  await sendFree(panel, '두 번째 질문')
  await expect(panel.getByRole('button', { name: /^이전 대화 보기/ })).toBeVisible()
  await expect(panel.getByRole('group', { name: 'AI 생성' })).toHaveCount(1, { timeout: 10_000 })
  await expect(panel.getByText('두 번째 질문', { exact: true })).toBeVisible()
  await panel.getByRole('button', { name: /^이전 대화 보기/ }).click()
  const log = panel.getByRole('log', { name: '대화' })
  await expect(log.getByRole('group', { name: 'AI 생성' })).toHaveCount(2)
  await mock(page, 'answered', 1200)
  await sendFree(panel, '세 번째 질문')
  await expect(panel.getByText('질문 이해하기', { exact: true })).toBeVisible()
  await log.evaluate((element) => { element.scrollTop = 0 })
  const newAnswer = panel.getByRole('button', { name: '새 답변 보기' })
  await expect(newAnswer).toBeVisible()
  await shot(page, testInfo, 'F6-10 긴 대화')
  // 답변이 와도 읽던 위치를 옮기지 않는다
  await expect(log.getByRole('group', { name: 'AI 생성' })).toHaveCount(3, { timeout: 10_000 })
  expect(await log.evaluate((element) => element.scrollTop)).toBe(0)
  await newAnswer.click()
  await expect(panel.getByText('세 번째 질문', { exact: true })).toBeInViewport()
})

test('PC: 그림을 그리지 못해도 본문과 출처는 남는다(F6-16, T6b 실패 카드)', async ({ page }, testInfo) => {
  await login(page)
  await page.route(/mermaid/, (route) => route.abort())
  const panel = await openPanel(page)
  await mock(page, 'answered', 20)
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  const answer = panel.getByRole('group', { name: 'AI 생성' })
  await expect(answer.getByText('오류: 그림을 표시하지 못했어요')).toBeVisible({ timeout: 10_000 })
  await expect(answer.getByText('합성 답변 첫 절입니다')).toBeVisible()
  await expect(answer.getByText('합성 답변 둘째 절입니다')).toBeVisible()
  await shot(page, testInfo, 'F6-16 그림 표시 실패')
})

test('PC: 선택을 제외하면 빠른 질문이 잠기고 다음 질문은 선택 없이 보낸다', async ({ page }) => {
  await login(page)
  const panel = await openPanel(page)
  await panel.getByRole('button', { name: '제외' }).click()
  await expect(panel.getByText(`선택: ‘${SELECTED}’`)).toHaveCount(0)
  await expect(panel.getByText('참고 문맥: 현재 노트', { exact: true })).toBeVisible()
  await expect(panel.getByRole('button', { name: '자세히 설명' })).toHaveAttribute('aria-disabled', 'true')
  await mock(page, 'answered', 20)
  await sendFree(panel, '직접 쓴 질문')
  await expect(panel.getByRole('group', { name: 'AI 생성' })).toBeVisible({ timeout: 10_000 })
  // 가짜 E27은 문맥이 없으면(origin none) 첫 질문 앞부분을 주제로 쓴다. 선택 문장 주제가 아니면 선택 없이 만든 대화다.
  await expect(panel.getByText('현재 주제: 직접 쓴 질문')).toBeVisible()
})

test('PC: Esc로 닫으면 노트로 돌아가고, 다시 열면 대화와 초안이 남아 있다', async ({ page }) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'answered', 20)
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(panel.getByRole('group', { name: 'AI 생성' })).toBeVisible({ timeout: 10_000 })
  await input(panel).fill('남겨 둘 초안')
  await page.keyboard.press('Escape')
  await expect(panel).toBeHidden()
  const again = await openPanel(page)
  await expect(again.getByRole('group', { name: 'AI 생성' })).toBeVisible()
  await expect(input(again)).toHaveValue('남겨 둘 초안')
  // PC는 Enter로 보낸다
  await mock(page, 'answered', 20)
  await input(again).press('Enter')
  await expect(again.getByText('남겨 둘 초안', { exact: true })).toBeVisible()
  await expect(input(again)).toHaveValue('')
})
