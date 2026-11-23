import { expect, test } from '@playwright/test'
import type { Locator, Page, TestInfo } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { goInApp } from './inApp.ts'

// MEG-254 위키 출처 보기와 위키 질문 입구(T4e). 가짜 API(src/api/mocks/agent.ts)가 서버의 위키 플래그와 위키 근거를 흉내 낸다. 모델은 부르지 않는다.
// 이 파일은 두 빌드에서 돈다(playwright.config.ts).
//  - agent-wiki(4187): 위키 플래그를 켠 빌드(VITE_CS_AGENT_WIKI_ENABLED=1)
//  - agent-enabled(4185): 위키 플래그를 끈 빌드(지금 운영 값과 같다)
// 결정(사용자 2026-11-23, MEG-254 댓글): 위키 출처의 '용어 시트 열기'로 연 시트에만 'AI에게 질문'을 두고 플래그를 따른다.
// 노트 강조에서 연 시트에는 버튼이 없고, 노트 선택 'AI에게 질문'은 플래그와 관계없이 origin note다(2026-11-19 결정, T3c 퀴즈 자료 경로).

const PC = { width: 1280, height: 800 }
const MOBILE = { width: 390, height: 844 }
const SELECTED = 'UnknownWord 는 사전에 없습니다.'

const wikiBuild = () => test.info().project.name === 'agent-wiki'

/* eslint-disable @typescript-eslint/no-explicit-any */
async function mockWiki(page: Page, options: { enabled?: boolean; sources?: boolean; changed?: boolean }) {
  await page.evaluate(async (options) => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    m.setAgentMockWiki(options)
  }, options)
}

// 단계 문구를 놓치지 않도록 가짜 단계 간격을 늘린다
async function slowSteps(page: Page) {
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    m.setAgentMockScenario('answered', { stepMs: 400 })
  })
}

async function revokeSources(page: Page) {
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    m.revokeAgentMockSources()
  })
}

type Sent = { method: string; path: string; body?: any }
async function sent(page: Page): Promise<Sent[]> {
  return page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    return m.agentMockRequests().map((r: any) => ({ method: r.method, path: r.path.replace(/[0-9a-f-]{36}/g, ':id'), body: r.body }))
  })
}
const conversationBodies = async (page: Page) => (await sent(page)).filter((r) => r.method === 'POST' && r.path === '/api/ai/conversations').map((r) => r.body)

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

const panelOf = (page: Page) => page.getByRole('dialog', { name: 'AI에게 질문' })
const input = (panel: Locator) => panel.getByRole('textbox')
const send = (panel: Locator) => panel.getByRole('button', { name: '보내기' })
const sheetOf = (page: Page) => page.getByRole('dialog', { name: 'ExampleTerm' })

async function shot(page: Page, testInfo: TestInfo, name: string) {
  const body = await page.screenshot()
  await testInfo.attach(name, { body, contentType: 'image/png' })
  const dir = process.env.AGENT_SHOT_DIR
  if (dir) writeFileSync(join(dir, `${testInfo.project.name}-${name}.png`), body)
}

// 노트에서 문장을 골라 질문하고, 위키 문단을 근거로 한 답(서버 플래그를 켠 뒤의 노트 대화)을 받는다.
async function answeredFromWiki(page: Page): Promise<Locator> {
  await mockWiki(page, { sources: true })
  await slowSteps(page)
  await selectText(page, SELECTED)
  await page.getByRole('button', { name: 'AI에게 질문', exact: true }).click()
  const panel = panelOf(page)
  await expect(panel).toBeVisible()
  await input(panel).fill('이게 뭐야?')
  await send(panel).click()
  // 단계 문구와 출처 카드는 source_kind로 고른다(14.5 현재 문구)
  await expect(panel.getByText('위키에서 자료 찾기').first()).toBeVisible({ timeout: 10_000 })
  await expect(panel.getByText('완료 · 위키 문단 3개를 확인했어요')).toBeVisible({ timeout: 10_000 })
  await expect(panel.getByRole('button', { name: '[1] ExampleTerm · 정의' })).toBeVisible({ timeout: 10_000 })
  return panel
}

for (const [device, viewport] of [['PC', PC], ['모바일', MOBILE]] as const) {
  test(`${device}: 위키 출처 보기(F6-4 위키) → 용어 시트 열기 → 플래그에 따른 'AI에게 질문'`, async ({ page }, testInfo) => {
    await login(page, viewport)
    const panel = await answeredFromWiki(page)
    await panel.getByRole('button', { name: '[1] ExampleTerm · 정의' }).click()
    const source = page.getByRole('dialog', { name: '출처 1' })
    await expect(source).toBeVisible()
    // 인용 당시 문단과 '용어 시트 열기'(AC-3). PC는 노트 자리, 모바일은 출처 화면에 있다.
    const doc = device === 'PC' ? page.getByRole('article', { name: '출처 1' }) : source
    await expect(doc.getByText('합성 위키 문단 하나입니다. 인용 당시의 합성 문단 원문입니다.')).toBeVisible()
    await expect(doc.getByRole('heading', { name: '정의' })).toBeVisible()
    if (device === 'PC') {
      await expect(doc.getByText('내부 위키')).toBeVisible()
      await expect(source.getByText('왼쪽 위키에서 인용된 문단을 표시했어요. 질문할 때 선택한 노트 문장은 질문 문맥으로만 쓰였어요.')).toBeVisible()
    }
    await expect(doc.getByText('인용한 뒤 위키 문단이 바뀌었어요.', { exact: false })).toHaveCount(0)
    await shot(page, testInfo, `${device}-F6-4-wiki-source`)

    await doc.getByRole('button', { name: '용어 시트 열기' }).click()
    // 대화 패널을 닫고 그 용어 시트(E06)를 연다(결정 4)
    await expect(panelOf(page)).toHaveCount(0)
    await expect(source).toHaveCount(0)
    const sheet = sheetOf(page)
    await expect(sheet).toBeVisible()
    await expect(sheet.getByText('합성 설명 문장입니다.')).toBeVisible()
    const ask = sheet.getByRole('button', { name: 'AI에게 질문' })
    if (!wikiBuild()) {
      // 플래그가 꺼져 있으면 버튼이 없다(AC-2 끔)
      await expect(ask).toHaveCount(0)
      await shot(page, testInfo, `${device}-term-sheet-flag-off`)
      expect((await conversationBodies(page)).map((body) => body.origin)).toEqual(['note'])
      return
    }
    await expect(ask).toBeVisible()
    await shot(page, testInfo, `${device}-term-sheet-flag-on`)
    await ask.click()
    // E27 origin wiki, wiki_ref glossary:{term_id}(AC-2 켬)
    await expect(panelOf(page)).toBeVisible()
    expect((await conversationBodies(page)).at(-1)).toEqual({ origin: 'wiki', wiki_ref: 'glossary:7' })
    await expect(sheet).toHaveCount(0)
    const wikiPanel = panelOf(page)
    // 현재 주제는 용어 제목이고 노트 선택 문맥 표시가 없다
    await expect(wikiPanel.getByText('현재 주제: ExampleTerm')).toBeVisible()
    await expect(wikiPanel.getByText('참고 문맥', { exact: false })).toHaveCount(0)
    await expect(wikiPanel.getByRole('button', { name: '선택 내용 보기' })).toHaveCount(0)
    await input(wikiPanel).fill('멱등성과 무슨 관계야?')
    await send(wikiPanel).click()
    await expect(wikiPanel.getByText('위키에서 자료 찾기').first()).toBeVisible({ timeout: 10_000 })
    await expect(wikiPanel.getByRole('button', { name: '[1] ExampleTerm · 정의' })).toBeVisible({ timeout: 10_000 })
    await shot(page, testInfo, `${device}-wiki-conversation`)
  })
}

test('PC: 인용 뒤 위키 문단이 바뀌면 노트 출처와 같은 규칙으로 안내한다', async ({ page }, testInfo) => {
  await login(page)
  const panel = await answeredFromWiki(page)
  await mockWiki(page, { changed: true })
  await panel.getByRole('button', { name: '[1] ExampleTerm · 정의' }).click()
  const doc = page.getByRole('article', { name: '출처 1' })
  await expect(doc.getByText('인용한 뒤 위키 문단이 바뀌었어요. 인용할 때의 문단을 보여 드려요.')).toBeVisible()
  await expect(doc.getByText('합성 위키 문단 하나입니다. 인용 당시의 합성 문단 원문입니다.')).toBeVisible()
  await shot(page, testInfo, 'PC-wiki-source-changed')
})

test('모바일: 인용 뒤 위키 문단이 바뀐 안내', async ({ page }) => {
  await login(page, MOBILE)
  const panel = await answeredFromWiki(page)
  await mockWiki(page, { changed: true })
  await panel.getByRole('button', { name: '[1] ExampleTerm · 정의' }).click()
  await expect(page.getByRole('dialog', { name: '출처 1' }).getByText('인용한 뒤 위키 문단이 바뀌었어요. 인용할 때의 문단을 보여 드려요.')).toBeVisible()
})

test('PC: 위키 출처가 404면 노트 출처와 같이 출처 보기를 닫고 가린 턴을 보인다(AC-3)', async ({ page }) => {
  await login(page)
  const panel = await answeredFromWiki(page)
  await revokeSources(page)
  await panel.getByRole('button', { name: '[1] ExampleTerm · 정의' }).click()
  await expect(panel.getByRole('status').filter({ hasText: '이 답변에 쓴 자료를 더 이상 볼 수 없어요.' })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('dialog', { name: '출처 1' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '용어 시트 열기' })).toHaveCount(0)
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
})

test('노트 출처에는 용어 시트 열기가 없고, 바뀜 안내는 노트 문구다', async ({ page }) => {
  await login(page)
  await mockWiki(page, { changed: true })
  await selectText(page, SELECTED)
  await page.getByRole('button', { name: 'AI에게 질문', exact: true }).click()
  const panel = panelOf(page)
  await input(panel).fill('이게 뭐야?')
  await send(panel).click()
  await panel.getByRole('button', { name: /^\[1\] 노트/ }).click({ timeout: 10_000 })
  const doc = page.getByRole('article', { name: '출처 1' })
  await expect(doc.getByText('인용한 뒤 노트가 바뀌었어요. 인용할 때의 문단을 보여 드려요.')).toBeVisible()
  await expect(page.getByRole('button', { name: '용어 시트 열기' })).toHaveCount(0)
})

test('노트 강조에서 연 용어 시트에는 플래그와 관계없이 AI에게 질문이 없다', async ({ page }) => {
  await login(page, MOBILE)
  await page.getByRole('link', { name: 'ExampleTerm' }).first().click()
  const sheet = sheetOf(page)
  await expect(sheet.getByText('합성 설명 문장입니다.')).toBeVisible()
  await expect(sheet.getByRole('button', { name: 'AI에게 질문' })).toHaveCount(0)
})

test('노트 선택 AI에게 질문은 플래그와 관계없이 origin note와 용어 하나다(AC-4, T3c 퀴즈 자료 경로)', async ({ page }) => {
  await login(page)
  await selectText(page, 'ExampleTerm')
  await page.getByRole('button', { name: 'AI에게 질문', exact: true }).click()
  const panel = panelOf(page)
  await input(panel).fill('이 용어가 뭐야?')
  await send(panel).click()
  await expect(panel.getByRole('button', { name: /^\[1\]/ }).first()).toBeVisible({ timeout: 10_000 })
  const [body] = await conversationBodies(page)
  expect(body.origin).toBe('note')
  expect(body.note_id).toBe(11)
  expect(body.wiki_ref).toBeUndefined()
  // 고른 글이 강조 용어 하나와 정확히 겹친다(가짜 E05 glossary_spans의 위치)
  const spans = await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/handlers.ts')
    return (m.handleMock({ method: 'GET', path: '/api/notes/11', query: new URLSearchParams(), body: undefined }).body as any).glossary_spans
  })
  expect(spans).toContainEqual({ term_id: 7, ...body.selection })
})

test('화면 플래그만 켜진 배포: E27 origin wiki가 422면 위키 질문 입구를 닫는다', async ({ page }, testInfo) => {
  test.skip(!wikiBuild(), '위키 플래그를 켠 빌드에서만 버튼이 있다')
  await login(page)
  const panel = await answeredFromWiki(page)
  await mockWiki(page, { enabled: false })
  await panel.getByRole('button', { name: '[1] ExampleTerm · 정의' }).click()
  await page.getByRole('article', { name: '출처 1' }).getByRole('button', { name: '용어 시트 열기' }).click()
  const sheet = sheetOf(page)
  await sheet.getByRole('button', { name: 'AI에게 질문' }).click()
  await expect(sheet.getByRole('alert').filter({ hasText: '지금은 이 용어로 새 질문을 받을 수 없어요.' })).toBeVisible()
  await expect(sheet.getByRole('button', { name: 'AI에게 질문' })).toHaveCount(0)
  // 노트 접근 변경(F6-15)으로 읽지 않는다
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
  await shot(page, testInfo, 'PC-wiki-ask-422')
  // 노트 선택 'AI에게 질문'은 그대로 열린다(위키 입구만 닫았다)
  await selectText(page, SELECTED)
  await page.getByRole('button', { name: 'AI에게 질문', exact: true }).click()
  await expect(panelOf(page)).toBeVisible()
})
