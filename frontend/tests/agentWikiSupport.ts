import { expect, test } from '@playwright/test'
import type { Locator, Page, TestInfo } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { goInApp } from './inApp.ts'

// MEG-254 위키 시험(agentWiki.spec.ts, agentWikiFlagOn.spec.ts)이 함께 쓰는 도우미. 시험 파일이 아니다(이름이 .spec.ts가 아니다).
// MEG-254 위키 출처 보기와 위키 질문 입구(T4e). 가짜 API(src/api/mocks/agent.ts)가 서버의 위키 플래그와 위키 근거를 흉내 낸다. 모델은 부르지 않는다.
// 이 파일은 두 빌드에서 돈다(playwright.config.ts).
//  - agent-wiki(4187): 위키 플래그를 켠 빌드(VITE_CS_AGENT_WIKI_ENABLED=1)
//  - agent-enabled(4185): 위키 플래그를 끈 빌드(지금 운영 값과 같다)
// 결정(사용자 2026-11-23, MEG-254 댓글): 위키 출처의 '용어 시트 열기'로 연 시트에만 'AI에게 질문'을 두고 플래그를 따른다.
// 노트 강조에서 연 시트에는 버튼이 없고, 노트 선택 'AI에게 질문'은 플래그와 관계없이 origin note다(2026-11-19 결정, T3c 퀴즈 자료 경로).

export const PC = { width: 1280, height: 800 }
export const MOBILE = { width: 390, height: 844 }
export const SELECTED = 'UnknownWord 는 사전에 없습니다.'

export const wikiBuild = () => test.info().project.name === 'agent-wiki'

/* eslint-disable @typescript-eslint/no-explicit-any */
export async function mockWiki(page: Page, options: { enabled?: boolean; sources?: boolean; changed?: boolean }) {
  await page.evaluate(async (options) => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    m.setAgentMockWiki(options)
  }, options)
}

// 단계 문구를 놓치지 않도록 가짜 단계 간격을 늘린다
export async function slowSteps(page: Page) {
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    m.setAgentMockScenario('answered', { stepMs: 400 })
  })
}

export async function revokeSources(page: Page) {
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    m.revokeAgentMockSources()
  })
}

export type Sent = { method: string; path: string; body?: any }
export async function sent(page: Page): Promise<Sent[]> {
  return page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    return m.agentMockRequests().map((r: any) => ({ method: r.method, path: r.path.replace(/[0-9a-f-]{36}/g, ':id'), body: r.body }))
  })
}
export const conversationBodies = async (page: Page) => (await sent(page)).filter((r) => r.method === 'POST' && r.path === '/api/ai/conversations').map((r) => r.body)

export async function selectText(page: Page, needle: string) {
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

export async function login(page: Page, viewport = PC) {
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

export const panelOf = (page: Page) => page.getByRole('dialog', { name: 'AI에게 질문' })
export const input = (panel: Locator) => panel.getByRole('textbox')
export const send = (panel: Locator) => panel.getByRole('button', { name: '보내기' })
export const sheetOf = (page: Page) => page.getByRole('dialog', { name: 'ExampleTerm' })

export async function shot(page: Page, testInfo: TestInfo, name: string) {
  const body = await page.screenshot()
  await testInfo.attach(name, { body, contentType: 'image/png' })
  const dir = process.env.AGENT_SHOT_DIR
  if (dir) writeFileSync(join(dir, `${testInfo.project.name}-${name}.png`), body)
}

// 노트에서 문장을 골라 질문하고, 위키 문단을 근거로 한 답(서버 플래그를 켠 뒤의 노트 대화)을 받는다.
export async function answeredFromWiki(page: Page): Promise<Locator> {
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

