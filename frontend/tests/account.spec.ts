import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// MEG-65 계정 메뉴(F4-4)와 내 정보(F4-5). playwright.config.ts가 VITE_API_MOCK=true로 서버를 띄우므로 가짜 응답과 합성 계정으로 시험한다.
// 합성 계정은 src/api/mocks/handlers.ts에 있다. 실제 계정·비밀번호가 아니다.
const PASSWORD = 'example-password'

async function loginAs(page: Page, email: string) {
  await page.goto('/login')
  await page.getByLabel('이메일').fill(email)
  await page.getByLabel('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
}

const trigger = (page: Page) => page.getByRole('button', { name: /^내 계정/ })

test('방문자에게는 계정 메뉴가 아니라 로그인 버튼이 보인다', async ({ page }) => {
  await page.goto('/quiz')
  await expect(page.getByRole('banner').getByRole('link', { name: '로그인' })).toBeVisible()
  await expect(trigger(page)).toHaveCount(0)
})

test('F4-4 로그인한 사용자는 계정 아이콘을 눌러 메뉴를 열고 Esc로 닫으면 아이콘으로 포커스가 돌아온다', async ({ page }) => {
  await loginAs(page, 'member@example.test')
  await expect(page).toHaveURL(/\/quiz$/)
  const button = trigger(page)
  await expect(button).toHaveAttribute('aria-haspopup', 'menu')
  await expect(button).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByRole('menu')).toHaveCount(0)

  await button.click()
  await expect(button).toHaveAttribute('aria-expanded', 'true')
  await expect(button).toHaveAccessibleName('내 계정 메뉴 닫기')
  const menu = page.getByRole('menu', { name: '내 계정' })
  await expect(menu.getByRole('menuitem')).toHaveText(['내 정보', '로그아웃'])
  // 열리면 첫 항목으로 포커스가 간다
  await expect(page.getByRole('menuitem', { name: '내 정보' })).toBeFocused()

  await page.keyboard.press('Escape')
  await expect(page.getByRole('menu')).toHaveCount(0)
  await expect(button).toHaveAttribute('aria-expanded', 'false')
  await expect(button).toBeFocused()
})

test('메뉴 안에서 화살표·Home·End로 항목을 옮기고 바깥을 누르면 닫힌다', async ({ page }) => {
  await loginAs(page, 'member@example.test')
  await trigger(page).click()
  await page.keyboard.press('ArrowDown')
  await expect(page.getByRole('menuitem', { name: '로그아웃' })).toBeFocused()
  await page.keyboard.press('ArrowDown') // 끝에서 처음으로
  await expect(page.getByRole('menuitem', { name: '내 정보' })).toBeFocused()
  await page.keyboard.press('End')
  await expect(page.getByRole('menuitem', { name: '로그아웃' })).toBeFocused()
  await page.keyboard.press('Home')
  await expect(page.getByRole('menuitem', { name: '내 정보' })).toBeFocused()

  await page.getByRole('heading', { level: 1 }).click()
  await expect(page.getByRole('menu')).toHaveCount(0)
})

test('AC-1 내 정보에는 표시 이름과 역할만 보이고 이메일은 보이지 않는다', async ({ page }) => {
  await loginAs(page, 'member@example.test')
  await trigger(page).click()
  await page.getByRole('menuitem', { name: '내 정보' }).click()
  await expect(page).toHaveURL(/\/me$/)
  await expect(page.getByRole('heading', { level: 1, name: '내 정보' })).toBeVisible()
  const terms = page.locator('dt')
  await expect(terms).toHaveText(['표시 이름', '역할'])
  await expect(page.locator('dd')).toHaveText(['합성 사용자', '일반 사용자'])
  const text = await page.locator('main').innerText()
  expect(text).not.toContain('이메일')
  expect(text).not.toContain('@')
  // 돌아가기는 메뉴를 연 화면으로 간다
  await page.getByRole('link', { name: '돌아가기' }).click()
  await expect(page).toHaveURL(/\/quiz$/)
})

test('AC-1 운영자 계정이면 역할이 운영자로 보이고 돌아가기는 연 화면으로 간다', async ({ page }) => {
  await loginAs(page, 'operator@example.test')
  await expect(page).toHaveURL(/\/$/)
  await trigger(page).click()
  await page.getByRole('menuitem', { name: '내 정보' }).click()
  await expect(page.locator('dd')).toHaveText(['합성 운영자', '운영자'])
  await page.getByRole('link', { name: '돌아가기' }).click()
  await expect(page).toHaveURL(/\/$/)
})

test('AC-2 로그아웃하면 방문자 상태가 되고 과목·노트 목록으로 간다', async ({ page }) => {
  await loginAs(page, 'member@example.test')
  await trigger(page).click()
  await page.getByRole('menuitem', { name: '로그아웃' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('F1-1')
  // 헤더가 로그인 버튼으로 바뀌었다
  await expect(page.getByRole('banner').getByRole('link', { name: '로그인' })).toBeVisible()
  await expect(trigger(page)).toHaveCount(0)
  // useAuth 상태도 방문자다(앱 안 링크로만 옮겨 상태를 이어서 읽는다)
  await page.getByRole('link', { name: '공통 기반 샘플' }).click()
  await expect(page.getByText('현재 상태:')).toContainText('방문자')
})

test('방문자가 내 정보를 직접 열면 로그인 화면으로 간다', async ({ page }) => {
  await page.goto('/me')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { level: 1, name: '로그인' })).toBeVisible()
})

test('로그아웃 확인은 E03 결과를 세 가지로 가르고, 방문자로 확인한 상태를 함께 돌려준다', async ({ page }) => {
  await page.goto('/login')
  const result = await page.evaluate(async () => {
    const { checkLoggedOut } = await import('/src/account/logout.ts')
    const state = (status: string, role: string) => ({ status, role, displayName: null })
    const run = async (status: string, role: string) => {
      const check = await checkLoggedOut(async () => state(status, role) as never)
      return { result: check.result, state: check.state }
    }
    return {
      // 방문자로 확인됐다. 이 상태를 전역에 그대로 반영하므로 E03을 한 번 더 부르지 않는다
      loggedOut: await run('ready', 'visitor'),
      // 아직 로그인 상태로 읽혔다
      stillMember: await run('ready', 'member'),
      stillOperator: await run('ready', 'operator'),
      // E03을 받지 못하면 loadAuthState는 예외 없이 status 'error', role 'visitor'를 돌려준다. 이때 로그아웃됐다고도, 안 됐다고도 단정하지 않는다.
      stateError: await run('error', 'visitor'),
      loading: await run('loading', 'visitor'),
    }
  })
  expect(result.loggedOut).toEqual({ result: 'logged_out', state: { status: 'ready', role: 'visitor', displayName: null } })
  expect(result.stillMember.result).toBe('still_logged_in')
  expect(result.stillOperator.result).toBe('still_logged_in')
  expect(result.stateError.result).toBe('unknown')
  expect(result.loading.result).toBe('unknown')
})
