import { expect, test } from '@playwright/test'
import type { Locator, Page, TestInfo } from '@playwright/test'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { goInApp } from './inApp.ts'

// MEG-285 CS Agent PC 패널 폭 조절(캔버스 F6-21a~e, 2026-11-25 승인).
// 기본 480px, 최소 400px, 최대 720px(노트 영역 480px 이상 유지). 끌기·키보드·두 번 누르기, 폭은 기억하지 않는다.
// 가짜 API(src/api/mocks/agent.ts)를 쓰고 모델은 부르지 않는다. 도우미는 agentViewModes.spec.ts와 같다(파일이 겹치지 않게 따로 둔다).

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

const handle = (page: Page) => page.getByRole('separator', { name: 'AI에게 질문 패널 폭' })
const input = (panel: Locator) => panel.getByRole('textbox')
const widthOf = (locator: Locator) => locator.evaluate((element) => Math.round(element.getBoundingClientRect().width))
const noteMargin = (page: Page) => page.locator('main').first().evaluate((element) => Math.round(parseFloat(getComputedStyle(element).marginRight)))

// 손잡이를 dx만큼 끈다(음수면 왼쪽 = 넓힘). 손잡이 안쪽 가운데를 잡는다.
async function drag(page: Page, dx: number) {
  const box = (await handle(page).boundingBox())!
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + dx / 2, y, { steps: 4 })
  await page.mouse.move(x + dx, y, { steps: 4 })
  await page.mouse.up()
}

async function expectWidth(page: Page, panel: Locator, width: number) {
  await expect(handle(page)).toHaveAttribute('aria-valuenow', String(width))
  await expect(handle(page)).toHaveAttribute('aria-valuetext', `${width}픽셀`)
  expect(await widthOf(panel)).toBe(width)
  // 노트 본문은 패널 폭만큼 비운다(가리지 않음, F6-21b)
  expect(await noteMargin(page)).toBe(width)
}

async function shot(page: Page, testInfo: TestInfo, name: string) {
  const path = join(testInfo.outputDir, `${name}.png`)
  await page.screenshot({ path })
  await testInfo.attach(name, { path, contentType: 'image/png' })
  writeFileSync(join(testInfo.outputDir, `${name}.txt`), name)
}

test('AC-2 왼쪽 경계를 끌면 폭이 바뀌고 400~720px 밖으로는 바뀌지 않으며, 두 번 누르면 480px로 돌아간다', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await expectWidth(page, panel, 480)
  await expect(handle(page)).toHaveAttribute('aria-valuemin', '400')
  await expect(handle(page)).toHaveAttribute('aria-valuemax', '720')
  await shot(page, testInfo, 'F6-21a 기본 480')

  await drag(page, -120)
  await expectWidth(page, panel, 600)
  await drag(page, -400)
  await expectWidth(page, panel, 720)
  await shot(page, testInfo, 'F6-21b 최대 720')
  await drag(page, 600)
  await expectWidth(page, panel, 400)
  await shot(page, testInfo, 'F6-21c 최소 400')

  await handle(page).dblclick()
  await expectWidth(page, panel, 480)
})

test('AC-3 키보드만으로 손잡이에 초점을 두고 폭을 바꾼다(←가 넓힘)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await handle(page).focus()
  await expect(handle(page)).toBeFocused()
  await page.keyboard.press('ArrowLeft')
  await expectWidth(page, panel, 496)
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowRight')
  await expectWidth(page, panel, 464)
  await page.keyboard.press('End')
  await expectWidth(page, panel, 720)
  await page.keyboard.press('Home')
  await expectWidth(page, panel, 400)
  await page.keyboard.press('ArrowLeft')
  await shot(page, testInfo, 'F6-21d 키보드 초점')
  // 방향키는 패널 안 다른 동작(Esc 닫기 등)을 건드리지 않는다
  await expect(panel).toBeVisible()
})

test('AC-4 답변을 받는 중에 폭을 바꿔도 초안·진행 중인 답변이 남고 노트 글자가 선택되지 않는다', async ({ page }) => {
  await login(page)
  const panel = await openPanel(page)
  await mock(page, 'answered', 800)
  await panel.getByRole('button', { name: '자세히 설명' }).click()
  await input(panel).fill('끄는 동안 남아야 할 초안')
  await expect(panel.getByRole('button', { name: '중단', exact: true })).toBeVisible()
  await page.evaluate(() => document.getSelection()?.removeAllRanges())

  await drag(page, -160)
  await expectWidth(page, panel, 640)
  expect(await page.evaluate(() => document.getSelection()?.toString() ?? '')).toBe('')
  await expect(input(panel)).toHaveValue('끄는 동안 남아야 할 초안')
  await expect(panel.getByRole('button', { name: '중단', exact: true })).toBeVisible()
  await expect(panel.getByText('합성 답변 첫 절입니다')).toBeVisible({ timeout: 10_000 })
  await expect(input(panel)).toHaveValue('끄는 동안 남아야 할 초안')
  // 끈 뒤에는 문서의 선택 막기가 풀린다
  expect(await page.evaluate(() => document.documentElement.style.userSelect)).toBe('')
})

test('AC-5 떠 있는 창·전체 화면·모바일은 폭이 그대로이고 손잡이가 없다, 닫았다 열면 480px', async ({ page }) => {
  await login(page)
  let panel = await openPanel(page)
  await drag(page, -160)
  await expectWidth(page, panel, 640)

  await panel.getByRole('button', { name: '창으로 보기' }).click()
  await expect(handle(page)).toHaveCount(0)
  expect(await widthOf(panel)).toBe(420)
  await panel.getByRole('button', { name: '전체 화면' }).click()
  await expect(handle(page)).toHaveCount(0)
  await panel.getByRole('button', { name: '패널로 보기' }).click()
  // 같은 대화 안에서 보기를 바꿔 돌아오면 바꾼 폭이 남는다
  await expectWidth(page, panel, 640)

  // 닫았다 열면 기본 폭(기억하지 않음, 사람 결정)
  await panel.getByRole('button', { name: '닫기' }).click()
  await expect(panel).toBeHidden()
  expect(await noteMargin(page)).toBe(0)
  panel = await openPanel(page)
  await expectWidth(page, panel, 480)

  // 모바일 전체 화면에는 손잡이가 없다
  await page.setViewportSize(MOBILE)
  await expect(handle(page)).toHaveCount(0)
})

test('좁은 화면(1024px)에서는 최대가 줄고, 창을 줄이면 지금 폭이 최대로 맞춰진다(F6-21e)', async ({ page }, testInfo) => {
  await login(page)
  const panel = await openPanel(page)
  await handle(page).focus()
  await page.keyboard.press('End')
  await expectWidth(page, panel, 720)

  await page.setViewportSize({ width: 1024, height: 800 })
  // 노트 영역 480px를 남긴 최대(스크롤 막대를 뺀 화면 폭 기준)
  const max = await page.evaluate(() => Math.max(400, Math.min(720, document.documentElement.clientWidth - 480)))
  expect(max).toBeLessThanOrEqual(544)
  await expectWidth(page, panel, max)
  await expect(handle(page)).toHaveAttribute('aria-valuemax', String(max))
  await shot(page, testInfo, 'F6-21e 1024 최대')
})
