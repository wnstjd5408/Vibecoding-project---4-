import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { goInApp } from './inApp.ts'

// MEG-90 용어 시트 안 즐겨찾기(F3-2)와 로그인 안내 연결. playwright.config.ts가 VITE_API_MOCK=true로 서버를 띄우므로
// 가짜 응답(E05 예시 1, E06 예시 2, E08: 방문자 401·로그인 사용자는 저장)으로 실제 노트 화면에서 시험한다.
// E08 요청 규칙과 오류 분기는 브라우저 fetch 경로가 필요해 notes.spec.ts에서 시험한다. 실제 백엔드의 E08과 서버 저장 방지는 확인하지 못한다.
const term = (page: Page) => page.getByRole('link', { name: 'ExampleTerm' })
const termSheet = (page: Page) => page.getByRole('dialog', { name: 'ExampleTerm' })
const loginSheet = (page: Page) => page.getByRole('dialog', { name: '로그인이 필요해요' })
const favoriteOff = (page: Page) => termSheet(page).getByRole('button', { name: '즐겨찾기', exact: true })
const favoriteOn = (page: Page) => termSheet(page).getByRole('button', { name: '즐겨찾기함' })

async function openTermSheet(page: Page) {
  await term(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
}

async function loginAsMember(page: Page) {
  await page.goto('/login')
  await page.getByLabel('이메일').fill('member@example.test')
  await page.getByLabel('비밀번호').fill('example-password')
  await page.getByRole('button', { name: '로그인' }).click()
  await expect(page).toHaveURL(/\/quiz$/)
  // 가짜 로그인 상태는 메모리에만 있어 새로 고치지 않고 앱 안에서 경로를 옮긴다
  await goInApp(page, '/notes/11')
}

test('AC-2 방문자가 즐겨찾기를 누르면 용어 시트가 닫히고 로그인 안내가 열리며 저장되지 않는다', async ({ page }) => {
  await page.goto('/notes/11')
  await openTermSheet(page)
  await expect(favoriteOff(page)).toHaveAttribute('aria-pressed', 'false')
  await favoriteOff(page).click()
  // 용어 시트는 닫히고 로그인 안내만 열린다(두 모달이 겹쳐 남지 않는다)
  await expect(loginSheet(page)).toBeVisible()
  await expect(termSheet(page)).toBeHidden()
  await expect(page.getByRole('dialog')).toHaveCount(1)
  // 안내를 닫고 용어 시트를 다시 열어도 저장된 것처럼 보이지 않는다
  await page.keyboard.press('Escape')
  await expect(loginSheet(page)).toBeHidden()
  await expect(term(page)).toBeFocused()
  await term(page).press('Enter') // 원래 용어 링크를 키보드로 다시 활성화할 수 있다
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await expect(favoriteOff(page)).toHaveAttribute('aria-pressed', 'false')
  await expect(favoriteOn(page)).toHaveCount(0)
  await expect(page.getByText('즐겨찾기에 저장했어요')).toHaveCount(0)
})

for (const [name, close] of [
  ['Esc', (page: Page) => page.keyboard.press('Escape')],
  ['닫기 버튼', (page: Page) => page.getByRole('button', { name: '닫기' }).click()],
  ['막(스크림) 누르기', (page: Page) => page.mouse.click(195, 20)],
] as const) {
  test(`로그인 안내를 ${name}로 닫으면 노트의 원래 용어 링크로 포커스가 돌아온다`, async ({ page }) => {
    await page.goto('/notes/11')
    await openTermSheet(page)
    await favoriteOff(page).click()
    await expect(loginSheet(page)).toBeVisible()
    // 제거된 즐겨찾기 버튼이나 숨겨진 용어 시트가 아니라 노트 본문 쪽으로 포커스가 있다
    await close(page)
    await expect(loginSheet(page)).toBeHidden()
    await expect(termSheet(page)).toBeHidden()
    await expect(term(page)).toBeFocused()
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })
}

test('로그인 안내의 로그인 버튼은 /login으로 가고 모달·배경 비활성이 남지 않는다', async ({ page }) => {
  await page.goto('/notes/11')
  await openTermSheet(page)
  await favoriteOff(page).click()
  await loginSheet(page).getByRole('link', { name: '로그인' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('body')).not.toHaveCSS('overflow', 'hidden')
  // 배경이 비활성으로 남지 않아 입력할 수 있다
  await page.getByLabel('이메일').fill('x@example.test')
  await expect(page.getByLabel('이메일')).toHaveValue('x@example.test')
})

test('AC-1 로그인 사용자는 즐겨찾기를 켜고 끌 수 있고, 시트를 다시 열어도 상태가 이어진다', async ({ page }) => {
  await loginAsMember(page)
  await openTermSheet(page)
  await expect(favoriteOff(page)).toHaveAttribute('aria-pressed', 'false')

  await favoriteOff(page).click()
  await expect(favoriteOn(page)).toHaveAttribute('aria-pressed', 'true')
  await expect(termSheet(page).getByText('즐겨찾기에 저장했어요')).toBeAttached()
  await expect(loginSheet(page)).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)

  // 닫았다 다시 열면 E06의 is_favorite로 켜진 상태가 보인다
  await page.keyboard.press('Escape')
  await expect(termSheet(page)).toBeHidden()
  await openTermSheet(page)
  await expect(favoriteOn(page)).toHaveAttribute('aria-pressed', 'true')

  await favoriteOn(page).click()
  await expect(favoriteOff(page)).toHaveAttribute('aria-pressed', 'false')
  await expect(termSheet(page).getByText('즐겨찾기를 해제했어요')).toBeAttached()
})
