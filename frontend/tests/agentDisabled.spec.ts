import { expect, test } from '@playwright/test'
import type { Page, TestInfo } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { goInApp } from './inApp.ts'

// MEG-259(T6e) 노출 중단 플래그를 켠 빌드(VITE_CS_AGENT_DISABLED=1, playwright.config.ts의 agent-disabled).
// 노트 선택 버튼은 기존 'AI 설명'(E09)이고 'AI에게 질문'이라는 이름은 어디에도 보이지 않는다. AI 설명의 자세한 동작은 aiExplain.spec.ts가 시험한다.

const PC = { width: 1280, height: 800 }
const MOBILE = { width: 390, height: 844 }
const OLD_LOGIN_BODY = '로그인하면 AI 설명, 즐겨찾기, 오늘의 퀴즈를 쓸 수 있어요. 계정은 운영자가 만들어 줘요.'

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

async function shot(page: Page, testInfo: TestInfo, name: string) {
  const body = await page.screenshot()
  await testInfo.attach(name, { body, contentType: 'image/png' })
  const dir = process.env.ENTRY_SHOT_DIR
  if (dir) writeFileSync(join(dir, `${name.split(' ')[0]}.png`), body)
}

const explainButton = (page: Page) => page.getByRole('button', { name: 'AI 설명', exact: true })

for (const [device, viewport] of [['PC', PC], ['모바일', MOBILE]] as const) {
  test(`AC-3 ${device}: 플래그를 켠 빌드에서는 'AI 설명'만 보이고 지금처럼 E09 설명이 열린다`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport)
    await page.goto('/login')
    await page.getByLabel('이메일').fill('member@example.test')
    await page.getByLabel('비밀번호').fill('example-password')
    await page.getByRole('button', { name: '로그인' }).click()
    await expect(page).toHaveURL(/\/quiz$/)
    await goInApp(page, '/notes/11')
    await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
    await selectText(page, 'UnknownWord')
    await expect(explainButton(page)).toBeVisible()
    await expect(page.getByText('AI에게 질문')).toHaveCount(0)
    await shot(page, testInfo, `on-${device === 'PC' ? 'pc' : 'mobile'}-select 선택 버튼`)
    await explainButton(page).click()
    const sheet = page.getByRole('dialog', { name: 'UnknownWord' })
    await expect(sheet.getByText('AI 생성·검수 전')).toBeVisible()
    await expect(sheet.getByRole('group', { name: 'AI 생성 설명' }).getByText('합성 AI 설명입니다.')).toBeVisible()
    await expect(page.getByRole('dialog', { name: 'AI에게 질문' })).toHaveCount(0)
    await shot(page, testInfo, `on-${device === 'PC' ? 'pc' : 'mobile'}-explain AI 설명`)
  })
}

test('플래그를 켠 빌드: 방문자 로그인 안내 본문에 \'AI에게 질문\'이 없다', async ({ page }, testInfo) => {
  await page.setViewportSize(MOBILE)
  await page.goto('/notes/11')
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
  await selectText(page, 'UnknownWord')
  await explainButton(page).click()
  const sheet = page.getByRole('dialog', { name: '로그인이 필요해요' })
  await expect(sheet.getByText(OLD_LOGIN_BODY)).toBeVisible()
  await expect(page.getByText('AI에게 질문')).toHaveCount(0)
  await shot(page, testInfo, 'on-login 로그인 안내')
})
