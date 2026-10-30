import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// MEG-77 로그인 안내 시트(F1-1c·F2-2b). playwright.config.ts가 VITE_API_MOCK=true로 서버를 띄우므로 가짜 응답(E08·E09는 방문자에게 401 login_required)으로 시험한다.
// 실제 백엔드의 401과 실제 즐겨찾기·AI 설명 화면 연결은 이 시험이 확인하지 못한다(MEG-76·90·106이 맡는다).
const TITLE = '로그인이 필요해요'
const DEFAULT_BODY = '로그인하면 AI 설명, 즐겨찾기, 오늘의 퀴즈를 쓸 수 있어요. 계정은 운영자가 만들어 줘요.'
const QUIZ_BODY = '오늘의 퀴즈는 로그인한 뒤에 볼 수 있어요. 계정은 운영자가 만들어 줘요.'

// 쇼케이스에는 같은 이름의 버튼이 여러 개라 이 데모 구역 안에서만 찾는다
const demo = (page: Page) => page.getByRole('region', { name: '로그인 안내 시트 (MEG-77)' })
const sheet = (page: Page) => page.getByRole('dialog', { name: TITLE })

test('AC-1 방문자가 즐겨찾기를 누르면 로그인 안내 시트가 뜨고 저장되지 않는다', async ({ page }) => {
  await page.goto('/dev/components')
  const toggle = demo(page).getByRole('button', { name: '즐겨찾기', exact: true })
  await expect(toggle).toHaveAttribute('aria-pressed', 'false')
  await toggle.click()
  await expect(sheet(page)).toBeVisible()
  await expect(sheet(page).getByText(DEFAULT_BODY)).toBeVisible()
  // 저장되지 않았다: 눌림 상태·저장 성공 표시가 없다
  await page.keyboard.press('Escape')
  await expect(sheet(page)).toBeHidden()
  await expect(toggle).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByTestId('favorite-status')).toHaveText('')
  await expect(demo(page).getByRole('button', { name: '즐겨찾기함' })).toHaveCount(0)
})

test('AC-2 AI 설명 버튼도 같은 공통 처리로 같은 시트를 띄운다', async ({ page }) => {
  await page.goto('/dev/components')
  const button = demo(page).getByRole('button', { name: 'AI 설명', exact: true })
  await button.click()
  await expect(sheet(page)).toBeVisible()
  await expect(sheet(page).getByText(DEFAULT_BODY)).toBeVisible()
  await expect(page.getByTestId('ai-status')).toHaveText('')
  await page.getByRole('button', { name: '닫기' }).click()
  await expect(sheet(page)).toBeHidden()
  await expect(button).toBeFocused()
})

test('로그인한 사용자가 즐겨찾기를 하면 시트 없이 저장된다', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('이메일').fill('member@example.test')
  await page.getByLabel('비밀번호').fill('example-password')
  await page.getByRole('button', { name: '로그인' }).click()
  await expect(page).toHaveURL(/\/quiz$/)
  // 가짜 로그인 상태는 메모리에만 있어 새로 고치지 않고 임시 화면(/quiz)의 이동 링크로 옮긴다
  await page.getByRole('link', { name: '공통 컴포넌트' }).click()
  const toggle = demo(page).getByRole('button', { name: '즐겨찾기', exact: true })
  await toggle.click()
  await expect(page.getByTestId('favorite-status')).toHaveText('즐겨찾기에 저장했어요')
  await expect(demo(page).getByRole('button', { name: '즐겨찾기함' })).toHaveAttribute('aria-pressed', 'true')
  await expect(sheet(page)).toHaveCount(0)
})

test('퀴즈 문구로 열었다 닫은 뒤 기본으로 열면 이전 문구가 남지 않는다', async ({ page }) => {
  await page.goto('/dev/components')
  await demo(page).getByRole('button', { name: '퀴즈 문구로 열기' }).click()
  await expect(sheet(page).getByText(QUIZ_BODY)).toBeVisible()
  await expect(sheet(page).getByText(DEFAULT_BODY)).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(sheet(page)).toBeHidden()
  await demo(page).getByRole('button', { name: '기본 문구로 열기' }).click()
  await expect(sheet(page).getByText(DEFAULT_BODY)).toBeVisible()
  await expect(sheet(page).getByText(QUIZ_BODY)).toHaveCount(0)
  // 제목은 두 경우 모두 같다
  await expect(sheet(page).getByRole('heading', { name: TITLE })).toBeVisible()
})

test.describe('F1-1c 노트 목록의 방문자 "오늘의 퀴즈"', () => {
  test('누르면 퀴즈 문구 시트가 뜨고, 닫으면 누른 버튼으로 포커스가 돌아온다', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('region', { name: '노트 목록' }).getByRole('link').first()).toBeVisible()
    const quiz = page.getByRole('button', { name: '오늘의 퀴즈' })
    await quiz.click()
    await expect(sheet(page)).toBeVisible()
    await expect(sheet(page).getByText(QUIZ_BODY)).toBeVisible()
    // 시트가 열리면 제목으로 포커스가 간다
    await expect(sheet(page).getByRole('heading', { name: TITLE })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(sheet(page)).toBeHidden()
    await expect(quiz).toBeFocused()
    await expect(page).toHaveURL(/\/$/)
  })

  test('닫기 버튼과 막(스크림) 누르기로도 닫히고 포커스가 돌아온다', async ({ page }) => {
    await page.goto('/')
    const quiz = page.getByRole('button', { name: '오늘의 퀴즈' })
    await quiz.click()
    await page.getByRole('button', { name: '닫기' }).click()
    await expect(sheet(page)).toBeHidden()
    await expect(quiz).toBeFocused()
    await quiz.click()
    await expect(sheet(page)).toBeVisible()
    await page.mouse.click(195, 20) // 시트 위쪽 막
    await expect(sheet(page)).toBeHidden()
    await expect(quiz).toBeFocused()
  })

  test('시트의 로그인 버튼은 /login으로 가고 시트는 닫힌다', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '오늘의 퀴즈' }).click()
    await sheet(page).getByRole('link', { name: '로그인' }).click()
    await expect(page).toHaveURL(/\/login$/)
    await expect(sheet(page)).toHaveCount(0)
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })

  // PR #56 Codex 리뷰 P2: 경로를 떠나며 숨겨진 시트가 원래 경로로 돌아왔을 때 되살아나면 안 된다.
  test('시트를 연 채 뒤로 갔다 앞으로 돌아와도 닫힌 시트가 다시 열리지 않는다', async ({ page }) => {
    await page.goto('/dev/foundation')
    // 새로 고치지 않고 앱 안 링크로 옮겨야 히스토리 이동이 앱 안에서 일어난다
    await page.getByRole('link', { name: 'F1-1 과목·노트 목록' }).click()
    await expect(page).toHaveURL(/\/$/)
    const quiz = page.getByRole('button', { name: '오늘의 퀴즈' })
    await quiz.click()
    await expect(sheet(page)).toBeVisible()
    // 시트를 닫지 않은 채 뒤로
    await page.goBack()
    await expect(page).toHaveURL(/\/dev\/foundation$/)
    await expect(sheet(page)).toHaveCount(0)
    // 앞으로: 퀴즈 버튼을 다시 누르지 않았으므로 시트는 닫혀 있어야 한다
    await page.goForward()
    await expect(page).toHaveURL(/\/$/)
    await expect(quiz).toBeVisible()
    await expect(sheet(page)).toBeHidden()
    // 새로 누르면 정상으로 열리고, 퀴즈 문구다
    await quiz.click()
    await expect(sheet(page)).toBeVisible()
    await expect(sheet(page).getByText(QUIZ_BODY)).toBeVisible()
  })

  test('로그인한 사용자에게는 시트가 아니라 /quiz 링크다', async ({ page }) => {
    await page.goto('/login')
    await page.getByLabel('이메일').fill('member@example.test')
    await page.getByLabel('비밀번호').fill('example-password')
    await page.getByRole('button', { name: '로그인' }).click()
    await expect(page).toHaveURL(/\/quiz$/)
    await page.getByRole('link', { name: 'F1-1 과목·노트 목록' }).click()
    await expect(page.getByRole('link', { name: '오늘의 퀴즈' })).toHaveAttribute('href', '/quiz')
    await expect(page.getByRole('button', { name: '오늘의 퀴즈' })).toHaveCount(0)
  })
})
