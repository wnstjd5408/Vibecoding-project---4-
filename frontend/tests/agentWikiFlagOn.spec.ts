import { expect, test } from '@playwright/test'
import { SELECTED, answeredFromWiki, conversationBodies, input, login, mockWiki, panelOf, selectText, send, sheetOf, shot } from './agentWikiSupport.ts'

// MEG-254 화면 위키 플래그를 켠 빌드(agent-wiki, 4187)에서만 도는 시험. 위키 출처에서 연 용어 시트의 'AI에게 질문'이 있어야 하는 경우다.

test('화면 플래그만 켜진 배포: E27 origin wiki가 422면 위키 질문 입구를 닫는다', async ({ page }, testInfo) => {
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
  // 노트 선택 'AI에게 질문'은 그대로 열리고, 실패한 위키 질문이 앞 대화를 지우지 않았다
  await selectText(page, SELECTED)
  await page.getByRole('button', { name: 'AI에게 질문', exact: true }).click()
  await expect(panelOf(page)).toBeVisible()
  await expect(panelOf(page).getByText('합성 답변 첫 절입니다').first()).toBeVisible()
})

test('E27 origin wiki가 503이면 안내를 남기고 노트 선택 입구도 닫는다', async ({ page }) => {
  await login(page)
  const panel = await answeredFromWiki(page)
  await panel.getByRole('button', { name: '[1] ExampleTerm · 정의' }).click()
  await page.getByRole('article', { name: '출처 1' }).getByRole('button', { name: '용어 시트 열기' }).click()
  await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/agent.ts')
    m.setAgentMockScenario('service_unavailable')
  })
  const sheet = sheetOf(page)
  await sheet.getByRole('button', { name: 'AI에게 질문' }).click()
  await expect(sheet.getByRole('alert').filter({ hasText: '지금은 이 용어로 새 질문을 받을 수 없어요.' })).toBeVisible()
  await expect(sheet.getByRole('button', { name: 'AI에게 질문' })).toHaveCount(0)
})

test('질문 없는 위키 대화에서 노트 문장을 고르면 origin note 대화로 새로 시작한다', async ({ page }) => {
  await login(page)
  const panel = await answeredFromWiki(page)
  await panel.getByRole('button', { name: '[1] ExampleTerm · 정의' }).click()
  await page.getByRole('article', { name: '출처 1' }).getByRole('button', { name: '용어 시트 열기' }).click()
  await sheetOf(page).getByRole('button', { name: 'AI에게 질문' }).click()
  await expect(panelOf(page).getByText('현재 주제: ExampleTerm')).toBeVisible()
  // PC 패널은 모달이 아니라 노트에서 바로 문장을 고를 수 있다
  await selectText(page, SELECTED)
  await page.getByRole('button', { name: 'AI에게 질문', exact: true }).click()
  const next = panelOf(page)
  await expect(next.getByText('현재 주제: ExampleTerm')).toHaveCount(0)
  await input(next).fill('이건 뭐야?')
  await send(next).click()
  await expect(next.getByRole('button', { name: /^\[1\]/ }).first()).toBeVisible({ timeout: 10_000 })
  const bodies = await conversationBodies(page)
  expect(bodies.map((body) => body.origin)).toEqual(['note', 'wiki', 'note'])
  expect(bodies.at(-1).selection).toBeDefined()
})
