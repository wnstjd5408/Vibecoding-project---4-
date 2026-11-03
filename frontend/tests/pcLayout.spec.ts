import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

// MEG-144 PC 배치(1024px 이상). playwright.config.ts가 VITE_API_MOCK=true로 서버를 띄우므로 가짜 응답(방문자, E05 예시 1)으로 시험한다.
// 기본 뷰포트는 390×844(설정)라, PC 시험은 폭을 따로 지정한다. 실제 Windows 브라우저와의 대조(AC-6)는 구현 뒤에 따로 한다.
const PC = { width: 1280, height: 800 }
const appName = (page: Page) => page.getByRole('banner').getByText('CS 학습 노트', { exact: true })
const backLink = (page: Page) => page.getByRole('banner').getByRole('link', { name: '목록' })

// 스크롤바가 자리를 차지하는 환경에서도 맞도록 화면의 실제 가용 폭을 기준으로 한다
const clientWidth = (page: Page) => page.evaluate(() => document.documentElement.clientWidth)

async function box(locator: Locator) {
  const result = await locator.boundingBox()
  if (!result) throw new Error('보이지 않는 요소다')
  return result
}

test.describe('1280px(PC)', () => {
  test.use({ viewport: PC })

  test('AC-1 노트 읽기: 본문 열이 최대 720px로 화면 가운데에 놓인다', async ({ page }) => {
    await page.goto('/notes/11')
    const article = page.locator('article')
    await expect(article).toBeVisible()
    const rect = await box(article)
    expect(Math.round(rect.width)).toBeLessThanOrEqual(720)
    expect(Math.round(rect.width)).toBeGreaterThanOrEqual(690) // 스크롤바가 있어도 거의 720px
    expect(Math.abs(rect.x - ((await clientWidth(page)) - rect.width) / 2)).toBeLessThanOrEqual(2) // 가운데(1280px 화면에서 x 280~1000)
  })

  test('노트 읽기 헤더는 화면 전체 폭이고 왼쪽에 앱 이름과 "목록"을 함께 둔다', async ({ page }) => {
    await page.goto('/notes/11')
    await expect(appName(page)).toBeVisible()
    await expect(backLink(page)).toBeVisible()
    const header = await box(page.getByRole('banner'))
    expect(Math.round(header.width)).toBe(await clientWidth(page))
    expect(Math.round((await box(appName(page))).x)).toBeLessThan(40)
    // 앱 이름이 "목록"보다 왼쪽에 있다
    expect((await box(appName(page))).x).toBeLessThan((await box(backLink(page))).x)
    await expect(page.getByRole('banner').getByRole('link', { name: '로그인' })).toBeVisible()
  })

  test('노트 목록: 헤더는 앱 이름만, 본문 열은 720px 가운데이고 과목 칩과 "오늘의 퀴즈"가 한 줄에 있다', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1, name: '과목' })).toBeVisible()
    await expect(appName(page)).toBeVisible()
    await expect(backLink(page)).toHaveCount(0)
    const header = await box(page.getByRole('banner'))
    expect(Math.round(header.width)).toBe(await clientWidth(page))
    const column = await box(page.getByRole('main'))
    expect(Math.round(column.width)).toBeLessThanOrEqual(720)
    expect(Math.abs(column.x - ((await clientWidth(page)) - column.width) / 2)).toBeLessThanOrEqual(2)
    const chip = await box(page.getByRole('group', { name: '과목 선택' }).getByRole('button', { name: '전체' }))
    const quiz = await box(page.getByRole('button', { name: '오늘의 퀴즈' }).or(page.getByRole('link', { name: '오늘의 퀴즈' })).first())
    expect(Math.abs((chip.y + chip.height / 2) - (quiz.y + quiz.height / 2))).toBeLessThanOrEqual(6) // 같은 줄
    expect(quiz.x).toBeGreaterThan(chip.x + chip.width) // 오른쪽 끝 쪽
  })
})

test.describe('1023px(모바일 경계)와 1024px(PC 시작)', () => {
  test('1023px에서는 기존 모바일 배치다(헤더에 "목록"만, 본문 열이 화면을 채움)', async ({ page }) => {
    await page.setViewportSize({ width: 1023, height: 800 })
    await page.goto('/notes/11')
    await expect(page.locator('article')).toBeVisible()
    await expect(backLink(page)).toBeVisible()
    await expect(appName(page)).toBeHidden()
    const article = await box(page.locator('article'))
    expect(Math.round(article.width)).toBeLessThanOrEqual(560 - 32) // 기존 560px 열에서 좌우 여백 16px씩
  })

  test('1024px부터 PC 배치다(헤더에 앱 이름과 "목록", 본문 열 720px)', async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 800 })
    await page.goto('/notes/11')
    await expect(page.locator('article')).toBeVisible()
    await expect(appName(page)).toBeVisible()
    await expect(backLink(page)).toBeVisible()
    const article = await box(page.locator('article'))
    expect(Math.round(article.width)).toBeLessThanOrEqual(720)
    expect(Math.round(article.width)).toBeGreaterThan(560)
  })
})

test.describe('다른 화면은 PC 폭에서도 기존 헤더를 유지한다', () => {
  test.use({ viewport: PC })

  test('로그인 화면의 헤더는 PC 폭에서도 560px 열 안의 기존 앱 이름 헤더 그대로다', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByRole('banner').getByText('CS 학습 노트', { exact: true })).toBeVisible() // 로그인 화면은 앱 이름 헤더 그대로
    const header = await box(page.getByRole('banner'))
    expect(Math.round(header.width)).toBeLessThanOrEqual(560) // 로그인 화면은 560px 열 안에 머문다
  })
})
