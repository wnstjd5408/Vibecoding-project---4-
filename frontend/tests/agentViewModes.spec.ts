import { expect, test } from '@playwright/test'
import type { Locator, Page, TestInfo } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { goInApp } from './inApp.ts'

// MEG-261 CS Agent 보기 전환(T6f): 패널(F6-3), 떠 있는 창(F6-3f), 전체 화면(F6-3x).
// 가짜 API(src/api/mocks/agent.ts)를 쓰고 모델은 부르지 않는다. 도우미는 agentPanel.spec.ts와 같다(다른 작업과 파일이 겹치지 않게 따로 둔다).

const PC = { width: 1280, height: 800 }
const MOBILE = { width: 390, height: 844 }
const SELECTED = 'UnknownWord 는 사전에 없습니다.'
const VIEW_KEY = 'cs-agent.view'

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

async function login(page: Page, viewport = PC, path = '/notes/11') {
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

async function openPanel(page: Page): Promise<Locator> {
  await selectText(page, SELECTED)
  await page.getByRole('button', { name: 'AI에게 질문', exact: true }).click()
  const panel = page.getByRole('dialog', { name: 'AI에게 질문' })
  await expect(panel).toBeVisible()
  return panel
}

async function answer(page: Page, panel: Locator) {
  await mock(page, 'answered', 20)
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await expect(panel.getByRole('group', { name: 'AI 생성' }).getByText('합성 답변 첫 절입니다')).toBeVisible({ timeout: 10_000 })
}

const input = (panel: Locator) => panel.getByRole('textbox')
// 전체 화면에서 main 영역이 되는 대화 틀. 노트의 main은 inert로 가린다(Playwright 역할 검색은 inert를 보지 않아 속성으로 확인한다).
const agentMain = (page: Page) => page.locator('dialog [role="main"]')
const noteMain = (page: Page) => page.locator('main')
const title = (page: Page) => page.getByRole('heading', { name: 'AI에게 질문', exact: true })
const headButtons = (panel: Locator) => panel.locator('[class*="headActions"] > button')
const box = (locator: Locator) => locator.evaluate((element) => {
  const rect = element.getBoundingClientRect()
  return { left: rect.left, top: rect.top, right: window.innerWidth - rect.right, bottom: window.innerHeight - rect.bottom, width: rect.width, height: rect.height }
})

async function shot(page: Page, testInfo: TestInfo, name: string) {
  const body = await page.screenshot()
  await testInfo.attach(name, { body, contentType: 'image/png' })
  const dir = process.env.AGENT_SHOT_DIR
  if (dir) writeFileSync(join(dir, `${name.split(' ')[0]}.png`), body)
}

test('AC-1: 세 보기를 오가도 대화와 쓰던 초안이 그대로 남고, 보기를 바꿔도 서버를 부르지 않는다', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await answer(page, panel)
  await input(panel).fill('쓰던 초안 — 그럼 멱등성은 뭐야?')
  const before = await requests(page)

  // 패널(F6-3): 오른쪽 480px, 머리는 [창으로 보기, 전체 화면, 새 대화, 닫기]
  await expect(headButtons(panel)).toHaveText(['창으로 보기', '전체 화면', '새 대화', '닫기'])
  expect((await box(panel)).width).toBe(480)
  await shot(page, testInfo, 'F6-3 패널')

  // 떠 있는 창(F6-3f): 오른쪽 아래 420×620, 본문은 창에 가리지 않는다
  await panel.getByRole('button', { name: '창으로 보기' }).click()
  await expect(headButtons(panel)).toHaveText(['패널로 보기', '전체 화면', '새 대화', '닫기'])
  await expect(title(page)).toBeFocused()
  await expect(title(page)).toHaveJSProperty('tagName', 'H2')
  const floating = await box(panel)
  expect(floating).toMatchObject({ width: 420, height: 620, right: 24, bottom: 24 })
  const article = await box(page.getByRole('heading', { level: 1, name: 'Example Note' }))
  expect(article.right).toBeGreaterThanOrEqual(floating.width + 24)
  await expect(panel.getByRole('group', { name: 'AI 생성' }).getByText('합성 답변 첫 절입니다')).toBeVisible()
  await expect(input(panel)).toHaveValue('쓰던 초안 — 그럼 멱등성은 뭐야?')
  await expect(panel.getByText('현재 주제: UnknownWord 는 사전에 없습', { exact: true })).toBeVisible()
  await shot(page, testInfo, 'F6-3f 떠 있는 창')

  // 전체 화면(F6-3x): 대화만 가운데 720px, 노트는 가린다(inert). 대화 영역이 main이고 제목은 h1이다
  await panel.getByRole('button', { name: '전체 화면' }).click()
  await expect(headButtons(panel)).toHaveText(['창으로 보기', '패널로 보기', '새 대화', '닫기'])
  const main = agentMain(page)
  await expect(main.getByRole('heading', { level: 1, name: 'AI에게 질문' })).toBeFocused()
  await expect(noteMain(page)).toHaveAttribute('inert', '')
  expect((await box(main)).width).toBe(720)
  await expect(main.getByRole('group', { name: 'AI 생성' }).getByText('합성 답변 첫 절입니다')).toBeVisible()
  await expect(input(panel)).toHaveValue('쓰던 초안 — 그럼 멱등성은 뭐야?')
  await expect(panel.getByText('참고 문맥: 현재 노트 · 선택 영역')).toBeVisible()
  await shot(page, testInfo, 'F6-3x 전체 화면')

  // 패널로 돌아오면 노트가 다시 보이고 대화·초안은 그대로다
  await panel.getByRole('button', { name: '패널로 보기' }).click()
  await expect(noteMain(page)).not.toHaveAttribute('inert')
  await expect(title(page)).toBeFocused()
  expect((await box(panel)).width).toBe(480)
  await expect(input(panel)).toHaveValue('쓰던 초안 — 그럼 멱등성은 뭐야?')
  await expect(panel.getByRole('group', { name: 'AI 생성' })).toHaveCount(1)

  // 바꾼 보기에서도 이어서 보낼 수 있다
  await panel.getByRole('button', { name: '창으로 보기' }).click()
  await mock(page, 'answered', 20)
  await input(panel).press('Enter')
  await expect(panel.getByText('쓰던 초안 — 그럼 멱등성은 뭐야?', { exact: true })).toBeVisible()
  await expect(panel.getByRole('group', { name: 'AI 생성' })).toHaveCount(1, { timeout: 10_000 })
  const after = await requests(page)
  // 보기 전환만으로는 요청이 없고, 늘어난 요청은 방금 보낸 질문 하나다
  expect(after.slice(0, before.length)).toEqual(before)
  expect(after.slice(before.length).filter((line) => line === 'POST /api/ai/conversations/:id/turns')).toHaveLength(1)
})

test('생성 중에 보기를 바꿔도 단계와 초안이 남고, 머리 버튼은 모든 상태에서 같다', async ({ page }) => {
  await login(page)
  const panel = await openPanel(page)
  // 질문 준비(F6-1)
  await expect(headButtons(panel)).toHaveText(['창으로 보기', '전체 화면', '새 대화', '닫기'])
  await mock(page, 'answered', 800)
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await input(panel).fill('생성 중 초안')
  // 생성 중(F6-2b): 새 대화만 잠기고 보기 전환은 그대로 쓸 수 있다
  await expect(panel.getByRole('button', { name: '중단', exact: true })).toBeVisible()
  await expect(headButtons(panel)).toHaveText(['창으로 보기', '전체 화면', '새 대화', '닫기'])
  await expect(panel.getByRole('button', { name: '새 대화' })).toHaveAttribute('aria-disabled', 'true')
  await panel.getByRole('button', { name: '전체 화면' }).click()
  await expect(agentMain(page).getByText('답변을 준비하고 있어요').first()).toBeVisible()
  await expect(panel.getByRole('button', { name: '중단', exact: true })).toBeVisible()
  await panel.getByRole('button', { name: '창으로 보기' }).click()
  await expect(panel.getByText('합성 답변 첫 절입니다')).toBeVisible({ timeout: 10_000 })
  await expect(input(panel)).toHaveValue('생성 중 초안')
  // 답변 뒤(F6-3f)
  await expect(headButtons(panel)).toHaveText(['패널로 보기', '전체 화면', '새 대화', '닫기'])
  // 사용 제한(F6-17) 뒤에도 같다
  await mock(page, 'ai_limit_reached')
  await input(panel).press('Enter')
  await expect(panel.getByText('지금은 AI 답변을 요청할 수 없어요', { exact: false })).toBeVisible()
  await expect(headButtons(panel)).toHaveText(['패널로 보기', '전체 화면', '새 대화', '닫기'])
})

test('마지막 보기 방식을 기억해 닫았다 열거나 다른 노트로 가도 그 보기로 연다', async ({ page }) => {
  await login(page)
  let panel = await openPanel(page)
  await panel.getByRole('button', { name: '창으로 보기' }).click()
  expect(await page.evaluate((key) => localStorage.getItem(key), VIEW_KEY)).toBe('floating')
  await panel.getByRole('button', { name: '닫기' }).click()
  await expect(panel).toBeHidden()
  panel = await openPanel(page)
  await expect(headButtons(panel)).toHaveText(['패널로 보기', '전체 화면', '새 대화', '닫기'])
  expect((await box(panel)).width).toBe(420)
  await panel.getByRole('button', { name: '전체 화면' }).click()
  expect(await page.evaluate((key) => localStorage.getItem(key), VIEW_KEY)).toBe('fullscreen')
  // 다른 노트로 갔다가 돌아오면 노트 화면을 새로 만든다. 그래도 전체 화면으로 연다
  // 노트 목록을 거쳐 돌아오면 노트 화면을 새로 만든다. 목록이 그려진 것을 본 뒤에 돌아가야 앞 화면과 헷갈리지 않는다
  await goInApp(page, '/')
  await expect(page.getByText('예시 노트 · 프로세스가 번갈아 실행되는 이유')).toBeVisible()
  await goInApp(page, '/notes/11')
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
  panel = await openPanel(page)
  await expect(agentMain(page).getByRole('heading', { level: 1, name: 'AI에게 질문' })).toBeVisible()
})

test('저장소가 막혀 있어도 보기 전환과 이 탭 안의 기억은 된다', async ({ page }) => {
  await page.addInitScript(() => {
    const blocked = () => { throw new DOMException('blocked', 'SecurityError') }
    Object.defineProperty(window, 'localStorage', { configurable: true, get: blocked })
  })
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await login(page)
  let panel = await openPanel(page)
  await answer(page, panel)
  await panel.getByRole('button', { name: '창으로 보기' }).click()
  expect((await box(panel)).width).toBe(420)
  await panel.getByRole('button', { name: '닫기' }).click()
  panel = await openPanel(page)
  expect((await box(panel)).width).toBe(420)
  await panel.getByRole('button', { name: '전체 화면' }).click()
  await expect(agentMain(page).getByRole('heading', { level: 1, name: 'AI에게 질문' })).toBeVisible()
  expect(errors).toEqual([])
})

test('Esc: 전체 화면은 패널로, 떠 있는 창은 닫고 노트(진입점)로 포커스를 돌린다', async ({ page }) => {
  await login(page)
  const panel = await openPanel(page)
  await input(panel).fill('Esc 초안')
  await panel.getByRole('button', { name: '전체 화면' }).click()
  await input(panel).focus()
  await page.keyboard.press('Escape')
  await expect(headButtons(panel)).toHaveText(['창으로 보기', '전체 화면', '새 대화', '닫기'])
  await expect(title(page)).toBeFocused()
  await expect(noteMain(page)).not.toHaveAttribute('inert')
  expect(await page.evaluate((key) => localStorage.getItem(key), VIEW_KEY)).toBe('panel')
  await panel.getByRole('button', { name: '창으로 보기' }).click()
  await page.keyboard.press('Escape')
  await expect(panel).toBeHidden()
  await expect(page.getByRole('article')).toBeFocused()
  const again = await openPanel(page)
  await expect(input(again)).toHaveValue('Esc 초안')
  await expect(headButtons(again)).toHaveText(['패널로 보기', '전체 화면', '새 대화', '닫기'])
})

test('전체 화면에서는 Tab이 가린 노트로 가지 않고, 휠·키보드로도 노트가 움직이지 않아 패널로 돌아오면 읽던 위치다', async ({ page }) => {
  await login(page, { width: 1280, height: 600 })
  // 가짜 노트는 짧아서 스크롤이 생기지 않는다. 본문 뒤에 빈 공간을 붙여 읽던 위치가 0이 아니게 한다
  await page.locator('article').evaluate((element) => { (element as HTMLElement).style.paddingBottom = '2000px' })
  const panel = await openPanel(page)
  const scrolled = await page.evaluate(() => { window.scrollTo({ top: 300 }); return window.scrollY })
  expect(scrolled).toBe(300)
  await panel.getByRole('button', { name: '전체 화면' }).click()
  await expect(title(page)).toBeFocused()
  // 대화 칸 옆 빈자리에서 굴리고, 제목에 포커스를 둔 채 PageDown·Space를 눌러도 노트가 움직이지 않는다
  await page.mouse.move(100, 400)
  await page.mouse.wheel(0, 600)
  await page.keyboard.press('PageDown')
  await page.keyboard.press('End')
  expect(await page.evaluate(() => window.scrollY)).toBe(scrolled)
  const visited = new Set<string>()
  for (let i = 0; i < 20; i += 1) {
    await page.keyboard.press('Tab')
    // 포커스는 대화 창이나 앱 머리(목록·내 계정)에만 있고, 가린 노트에는 가지 않는다
    const where = await page.evaluate(() => {
      const active = document.activeElement
      if (!active || active === document.body) return 'body'
      if (active.closest('dialog')) return 'dialog'
      if (active.closest('header')) return 'header'
      return active.closest('main') ? 'note' : 'other'
    })
    expect(['dialog', 'header', 'body']).toContain(where)
    visited.add(where)
  }
  // 한 바퀴 도는 동안 대화 창과 앱 머리를 모두 지난다
  expect(visited.has('dialog') && visited.has('header')).toBe(true)
  await panel.getByRole('button', { name: '패널로 보기' }).click()
  await expect(noteMain(page)).not.toHaveAttribute('inert')
  expect(await page.evaluate(() => window.scrollY)).toBe(scrolled)
  expect(await page.evaluate(() => document.documentElement.style.overflow)).toBe('')
})

test('맨 아래를 따라가던 중에 보기를 바꾸면 계속 맨 아래에 있다', async ({ page }) => {
  await login(page, { width: 1280, height: 640 })
  const panel = await openPanel(page)
  await answer(page, panel)
  await panel.getByRole('button', { name: '전체 화면' }).click()
  const body = panel.locator('[class*="body"]').first()
  const gap = () => body.evaluate((element) => element.scrollHeight - element.scrollTop - element.clientHeight)
  await body.evaluate((element) => { element.scrollTop = element.scrollHeight; element.dispatchEvent(new Event('scroll')) })
  expect(await gap()).toBeLessThan(24)
  await panel.getByRole('button', { name: '창으로 보기' }).click()
  expect(await gap()).toBeLessThan(24)
  await expect(panel.getByRole('button', { name: '새 답변 보기' })).toHaveCount(0)
})

test('전체 화면에서 출처를 열면 출처 보기(F6-4)로 보이고, 대화로 돌아오면 다시 전체 화면이다', async ({ page }) => {
  await login(page)
  const panel = await openPanel(page)
  await answer(page, panel)
  await input(panel).fill('출처 초안')
  await panel.getByRole('button', { name: '전체 화면' }).click()
  await panel.getByRole('button', { name: '출처 1 보기: 예시 노트 · 요청이 서버까지 가는 길' }).first().click()
  const source = page.getByRole('dialog', { name: '출처 1' })
  await expect(page.getByRole('article', { name: '출처 1' }).getByText('합성 근거 문단 하나입니다.', { exact: false })).toBeVisible()
  expect((await box(source)).width).toBe(480)
  await source.getByRole('button', { name: '대화로 돌아가기' }).click()
  await expect(agentMain(page).getByRole('heading', { level: 1, name: 'AI에게 질문' })).toBeVisible()
  await expect(input(panel)).toHaveValue('출처 초안')
})

test('모바일은 전체 높이 대화 화면 그대로이고 보기 전환 버튼이 없다', async ({ page }) => {
  await page.addInitScript((key) => localStorage.setItem(key, 'floating'), VIEW_KEY)
  await login(page, MOBILE)
  const panel = await openPanel(page)
  await expect(panel.getByRole('button', { name: '창으로 보기' })).toHaveCount(0)
  await expect(panel.getByRole('button', { name: '전체 화면' })).toHaveCount(0)
  await expect(panel.getByRole('button', { name: '패널로 보기' })).toHaveCount(0)
  expect(await box(panel)).toMatchObject({ width: MOBILE.width, height: MOBILE.height })
  // PC 폭으로 넓히면 기억한 보기(떠 있는 창)로 바뀐다
  await page.setViewportSize(PC)
  await expect(headButtons(panel)).toHaveText(['패널로 보기', '전체 화면', '새 대화', '닫기'])
})
