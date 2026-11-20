import { expect, test } from '@playwright/test'
import type { Locator, Page, TestInfo } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { goInApp } from './inApp.ts'

// MEG-259(T6e) 'AI에게 질문' 진입점과 503 처리. 노출 중단 플래그를 끈 빌드(playwright.config.ts의 agent-enabled)에서 돈다.
// 가짜 API(src/api/mocks/agent.ts)로 E27·E29의 503을 흉내 낸다. 모델은 부르지 않는다.
// 플래그를 켠 빌드의 시험은 agentDisabled.spec.ts에 있다.

const PC = { width: 1280, height: 800 }
const MOBILE = { width: 390, height: 844 }
const SELECTED = 'UnknownWord 는 사전에 없습니다.'
const CANVAS_LOGIN_BODY = '로그인하면 AI에게 질문, 즐겨찾기, 오늘의 퀴즈를 쓸 수 있어요. 계정은 운영자가 만들어 줘요.'

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
  await goInApp(page, '/notes/11')
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
}

const askButton = (page: Page) => page.getByRole('button', { name: 'AI에게 질문', exact: true })
const explainButton = (page: Page) => page.getByRole('button', { name: 'AI 설명', exact: true })
const agentPanel = (page: Page) => page.getByRole('dialog', { name: 'AI에게 질문' })
const input = (panel: Locator) => panel.getByRole('textbox')

// ENTRY_SHOT_DIR을 주면 같은 스크린샷을 파일로도 저장한다(PR에 붙일 때 쓴다).
async function shot(page: Page, testInfo: TestInfo, name: string) {
  const body = await page.screenshot()
  await testInfo.attach(name, { body, contentType: 'image/png' })
  const dir = process.env.ENTRY_SHOT_DIR
  if (dir) writeFileSync(join(dir, `${name.split(' ')[0]}.png`), body)
}

for (const [device, viewport] of [['PC', PC], ['모바일', MOBILE]] as const) {
  test(`AC-1 ${device}: 플래그를 끈 빌드에서는 노트 선택 버튼이 'AI에게 질문'이고 'AI 설명'은 보이지 않는다`, async ({ page }, testInfo) => {
    await login(page, viewport)
    await selectText(page, SELECTED)
    await expect(askButton(page)).toBeVisible()
    await expect(explainButton(page)).toHaveCount(0)
    await shot(page, testInfo, `off-${device === 'PC' ? 'pc' : 'mobile'}-select 선택 버튼`)
    await askButton(page).click()
    const panel = agentPanel(page)
    await expect(panel).toBeVisible()
    await expect(panel.getByText('선택한 내용으로 질문할 수 있어요.')).toBeVisible()
    // 선택만으로는 요청하지 않고, AI 설명 시트(E09)는 열리지 않는다
    expect(await requests(page)).toEqual([])
    await expect(page.getByRole('dialog', { name: 'UnknownWord' })).toHaveCount(0)
  })
}

test('플래그를 끈 빌드: 방문자 로그인 안내 본문은 캔버스 F2-2b 문구다', async ({ page }, testInfo) => {
  await page.setViewportSize(MOBILE)
  await page.goto('/notes/11')
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
  await selectText(page, SELECTED)
  await askButton(page).click()
  const sheet = page.getByRole('dialog', { name: '로그인이 필요해요' })
  await expect(sheet.getByText(CANVAS_LOGIN_BODY)).toBeVisible()
  await expect(agentPanel(page)).toHaveCount(0)
  await shot(page, testInfo, 'off-login 로그인 안내')
})

test('플래그를 끈 빌드: PC 방문자 로그인 안내 패널도 캔버스 문구다', async ({ page }) => {
  await page.setViewportSize(PC)
  await page.goto('/notes/11')
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
  await selectText(page, SELECTED)
  await askButton(page).click()
  await expect(page.getByRole('dialog', { name: '로그인이 필요해요' }).getByText(CANVAS_LOGIN_BODY)).toBeVisible()
})

for (const [device, viewport] of [['PC', PC], ['모바일', MOBILE]] as const) {
  test(`AC-2 ${device}: 첫 질문이 503이면 질문은 남고 새 질문 입구가 닫힌다. 다시 고르면 'AI 설명'이 열린다`, async ({ page }, testInfo) => {
    await login(page, viewport)
    await selectText(page, SELECTED)
    await askButton(page).click()
    const panel = agentPanel(page)
    await mock(page, 'service_unavailable')
    await input(panel).fill('멱등성이 뭐야?')
    await panel.getByRole('button', { name: '보내기' }).click()

    // 503 카드: 질문 줄은 남고, '다시 확인'(사용 제한 카드)은 없다
    await expect(panel.getByRole('alert').getByText('오류: 지금은 새 질문을 받을 수 없어요.')).toBeVisible()
    await expect(panel.getByText('멱등성이 뭐야?', { exact: true })).toBeVisible()
    await expect(panel.getByRole('button', { name: '다시 확인' })).toHaveCount(0)
    // 새 질문 입구(입력 칸, 보내기, 빠른 질문, 새 대화)가 사라진다
    await expect(panel.getByRole('textbox')).toHaveCount(0)
    await expect(panel.getByRole('button', { name: '보내기' })).toHaveCount(0)
    await expect(panel.getByRole('button', { name: '자세히 설명' })).toHaveCount(0)
    await expect(panel.getByRole('button', { name: '새 대화' })).toHaveCount(0)
    await expect(panel.getByText('지금은 새 질문을 받을 수 없어요. 이 대화와 출처는 계속 볼 수 있어요.')).toBeVisible()
    // 입력 칸이 사라져도 포커스는 패널 안에 남는다(본문 body로 떨어지지 않는다)
    expect(await panel.evaluate((dialog) => dialog.contains(document.activeElement) && document.activeElement !== document.body)).toBe(true)
    await shot(page, testInfo, `503-${device === 'PC' ? 'pc' : 'mobile'}-first 첫 질문 503`)
    // E27이 503이라 E29는 보내지 않았다
    expect(await requests(page)).toEqual(['POST /api/ai/conversations'])

    // 노트로 돌아가 다시 고르면 'AI 설명'이 보이고, 누르면 AI 설명(E09)이 열린다
    await panel.getByRole('button', { name: '노트 계속 읽기' }).click()
    await expect(panel).toBeHidden()
    await selectText(page, 'UnknownWord')
    await expect(explainButton(page)).toBeVisible()
    await expect(askButton(page)).toHaveCount(0)
    await explainButton(page).click()
    const sheet = page.getByRole('dialog', { name: 'UnknownWord' })
    await expect(sheet.getByRole('group', { name: 'AI 생성 설명' }).getByText('합성 AI 설명입니다.')).toBeVisible()
    await expect(agentPanel(page)).toHaveCount(0)
    expect(await requests(page)).toEqual(['POST /api/ai/conversations'])
  })
}

test('AC-2 PC: 답변을 받은 뒤 다음 질문이 503이면 기존 대화와 출처는 계속 읽는다', async ({ page }, testInfo) => {
  await login(page, PC)
  await selectText(page, SELECTED)
  await askButton(page).click()
  const panel = agentPanel(page)
  await mock(page, 'answered', 60)
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(panel.getByRole('group', { name: 'AI 생성' }).getByText('합성 답변 첫 절입니다')).toBeVisible({ timeout: 10_000 })
  await expect(panel.getByRole('button', { name: '합성 추천 질문 하나' })).toBeVisible()

  // E29가 503이 된다(노출 중단을 켠 백엔드)
  await mock(page, 'service_unavailable')
  await input(panel).fill('그럼 멱등성은 뭐야?')
  await panel.getByRole('button', { name: '보내기' }).click()
  await expect(panel.getByRole('alert').getByText('오류: 지금은 새 질문을 받을 수 없어요.')).toBeVisible()
  await expect(panel.getByText('그럼 멱등성은 뭐야?', { exact: true })).toBeVisible()
  await expect(panel.getByRole('textbox')).toHaveCount(0)
  await expect(panel.getByRole('button', { name: '새 대화' })).toHaveCount(0)

  // 이전 대화 보기로 앞 답변을 다시 읽는다(E28은 플래그와 무관). 추천 질문은 새 질문이라 그리지 않는다
  await mock(page, 'answered')
  await panel.getByRole('button', { name: /^이전 대화 보기/ }).click()
  await expect(panel.getByRole('group', { name: 'AI 생성' }).getByText('합성 답변 첫 절입니다')).toBeVisible()
  await expect(panel.getByRole('button', { name: '합성 추천 질문 하나' })).toHaveCount(0)
  await shot(page, testInfo, '503-pc-followup 다음 질문 503 뒤 대화 읽기')

  // 출처 보기도 그대로 열린다(E32)
  await panel.getByRole('button', { name: '[1] 노트 · 예시 노트 · 요청이 서버까지 가는 길 · 요청 흐름' }).click()
  const source = page.getByRole('dialog', { name: '출처 1' })
  await expect(source.getByText('대화는 그대로 있어요')).toBeVisible()
  await source.getByRole('button', { name: '대화로 돌아가기' }).click()
  await expect(panel.getByRole('heading', { name: 'AI에게 질문' })).toBeVisible()
  const calls = await requests(page)
  expect(calls.filter((call) => call === 'POST /api/ai/conversations')).toHaveLength(1)
  expect(calls).toContain('GET /api/ai/conversations/:id')

  // 패널이 열린 채 노트에서 다시 고르면 'AI 설명'이고, 누르면 'AI에게 질문' 패널을 닫고 AI 설명 패널을 연다(두 패널을 함께 두지 않는다)
  await selectText(page, 'UnknownWord')
  await expect(askButton(page)).toHaveCount(0)
  await explainButton(page).click()
  await expect(page.getByRole('dialog', { name: 'UnknownWord' })).toBeVisible()
  await expect(agentPanel(page)).toHaveCount(0)
})

test('503으로 닫은 입구는 같은 탭에서 다른 화면을 다녀와도 닫혀 있다', async ({ page }) => {
  await login(page, PC)
  await selectText(page, SELECTED)
  await askButton(page).click()
  await mock(page, 'service_unavailable')
  await agentPanel(page).getByRole('button', { name: '자세히 설명' }).click()
  await expect(agentPanel(page).getByText('오류: 지금은 새 질문을 받을 수 없어요.')).toBeVisible()
  await goInApp(page, '/')
  await goInApp(page, '/notes/11')
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
  await selectText(page, SELECTED)
  await expect(explainButton(page)).toBeVisible()
  await expect(askButton(page)).toHaveCount(0)
})
