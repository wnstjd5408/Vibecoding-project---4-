import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// MEG-108 오늘의 퀴즈(F3-3a·F3-3b). playwright.config.ts가 VITE_API_MOCK=true로 서버를 띄우므로
// 가짜 응답(E11 예시 5: 방문자 401·로그인 사용자는 ready)으로 실제 화면에서 시험한다.
// 여섯 상태, 재조회 간격, 오류별 안내는 브라우저 fetch 경로가 필요해 notes.spec.ts에서 시험한다. 실제 백엔드의 E11은 확인하지 못한다.

const QUIZ_BODY = '오늘의 퀴즈는 로그인한 뒤에 볼 수 있어요. 계정은 운영자가 만들어 줘요.'
const loginSheet = (page: Page) => page.getByRole('dialog', { name: '로그인이 필요해요' })

async function loginAsMember(page: Page) {
  await page.goto('/login')
  await page.getByLabel('이메일').fill('member@example.test')
  await page.getByLabel('비밀번호').fill('example-password')
  await page.getByRole('button', { name: '로그인' }).click()
  await expect(page).toHaveURL(/\/quiz$/)
}

test('AC-1 로그인하면 오늘의 퀴즈 문항 목록이 보인다', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await loginAsMember(page)
  await expect(page.getByRole('heading', { level: 1, name: '오늘의 퀴즈' })).toBeVisible()
  await expect(page.getByText('어제 열어 본·즐겨찾기한 용어로 만들었어요.')).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: '합성 질문 1입니다.' })).toBeVisible()
  await expect(page.getByRole('heading', { level: 2, name: '합성 질문 2입니다.' })).toBeVisible()
  await expect(page.getByRole('main').getByRole('listitem')).toHaveCount(2)
  await expect(page.getByText('난이도 중')).toBeVisible()
  await expect(page.getByText('난이도 하')).toBeVisible()
  await expect(page.getByText('AI 생성')).toHaveCount(2)
  // 이미 답한 둘째 문항은 "답함"만 보이고 정답·해설·내 답은 이 화면에 나오지 않는다. 답 입력칸과 답하기 버튼도 없다.
  await expect(page.getByText('답함', { exact: true })).toHaveCount(1)
  for (const hidden of ['합성 정답', '합성 해설', '합성 답변', '합성 꼬리 질문']) await expect(page.getByText(hidden)).toHaveCount(0)
  await expect(page.getByRole('textbox')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '답하기' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: '노트 보러 가기' })).toHaveAttribute('href', '/')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await testInfo.attach('F3-3a 문항 목록', { body: await page.screenshot(), contentType: 'image/png' })
})

test('로그인한 사용자에게는 계정 메뉴가 보이고 로그인 안내는 열리지 않는다', async ({ page }) => {
  await loginAsMember(page)
  await expect(page.getByRole('button', { name: /^내 계정/ })).toBeVisible()
  await expect(loginSheet(page)).toHaveCount(0)
})

test('방문자가 /quiz로 직접 들어오면 퀴즈 문구의 로그인 안내가 열리고 본문에는 노트 목록 이동만 있다', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/quiz')
  await expect(loginSheet(page)).toBeVisible()
  await expect(loginSheet(page).getByText(QUIZ_BODY)).toBeVisible()
  await testInfo.attach('방문자 /quiz 로그인 안내', { body: await page.screenshot(), contentType: 'image/png' })
  await page.keyboard.press('Escape')
  await expect(loginSheet(page)).toBeHidden()
  await expect(page.getByRole('heading', { level: 2, name: '오늘의 퀴즈는 로그인한 뒤에 볼 수 있어요' })).toBeVisible()
  await expect(page.getByRole('link', { name: '노트 보러 가기' })).toHaveAttribute('href', '/')
  await expect(page.getByRole('heading', { level: 2, name: '합성 질문 1입니다.' })).toHaveCount(0)
})
