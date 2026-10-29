import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// MEG-64 로그인 화면(F4-1). playwright.config.ts가 VITE_API_MOCK=true로 서버를 띄우므로 가짜 응답과 합성 계정으로 시험한다.
// 합성 계정은 src/api/mocks/handlers.ts에 있다. 실제 계정·비밀번호가 아니다.
const PASSWORD = 'example-password'

async function submit(page: Page, email: string, password: string) {
  await page.getByLabel('이메일').fill(email)
  await page.getByLabel('비밀번호').fill(password)
  await page.getByRole('button', { name: '로그인' }).click()
}

// 로그인 상태를 읽는다. 가짜 로그인 상태는 메모리에만 있어 새로 고치면 사라지므로, 앱 안 링크로만 옮긴다.
// 이동 링크(DevNav)가 있는 임시 화면에서 공통 기반 샘플(/dev/foundation)로 가서 useAuth의 현재 상태 문장을 돌려준다.
async function readAuthState(page: Page) {
  const guestLink = page.getByRole('link', { name: '로그인 없이 노트 보기' })
  if (await guestLink.count()) {
    await guestLink.click()
    await expect(page.getByRole('heading', { level: 1, name: '과목' })).toBeVisible()
  }
  const list = page.getByRole('region', { name: '노트 목록' })
  if (await list.count()) await list.getByRole('link').first().click()
  await page.getByRole('link', { name: '공통 기반 샘플' }).click()
  return page.getByText('현재 상태:')
}

test('로그인 화면이 목업대로 그려지고 가로로 넘치지 않는다', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/login')
  await expect(page.getByRole('heading', { level: 1, name: '로그인' })).toBeVisible()
  await expect(page.getByText('계정은 운영자가 만들어 줘요. 직접 가입하는 기능은 없어요.')).toBeVisible()
  await expect(page.getByLabel('이메일')).toHaveAttribute('autocomplete', 'username')
  await expect(page.getByLabel('비밀번호')).toHaveAttribute('autocomplete', 'current-password')
  await expect(page.getByLabel('비밀번호')).toHaveAttribute('type', 'password')
  await expect(page.getByRole('link', { name: '로그인 없이 노트 보기' })).toHaveAttribute('href', '/')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  expect(errors).toEqual([])
})

test('AC-1·AC-3 사용자 계정으로 로그인하면 로그인 상태가 되고 퀴즈 첫 화면으로 간다', async ({ page }) => {
  await page.goto('/login')
  await submit(page, 'member@example.test', PASSWORD)
  await expect(page).toHaveURL(/\/quiz$/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('F3-3a')
  await expect(await readAuthState(page)).toContainText('사용자')
  await expect(page.getByText('현재 상태:')).toContainText('합성 사용자')
})

test('AC-1·AC-3 운영자 계정으로 로그인하면 과목·노트 목록으로 간다', async ({ page }) => {
  await page.goto('/login')
  await submit(page, 'operator@example.test', PASSWORD)
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('과목')
  await expect(page.getByRole('link', { name: '운영자 메뉴' })).toBeVisible()
  await expect(await readAuthState(page)).toContainText('운영자')
})

test('AC-2 로그인에 실패하면 임시 문구가 보이고 이메일은 남으며 비밀번호는 비워진다', async ({ page }) => {
  await page.goto('/login')
  await submit(page, 'member@example.test', 'wrong-password')
  await expect(page).toHaveURL(/\/login$/)
  const alert = page.getByRole('alert')
  await expect(alert).toContainText('이메일 또는 비밀번호가 맞지 않아요.')
  await expect(page.getByLabel('이메일')).toHaveValue('member@example.test')
  await expect(page.getByLabel('비밀번호')).toHaveValue('')
  await expect(page.getByLabel('비밀번호')).toBeFocused()
  await expect(page.getByLabel('비밀번호')).toHaveAttribute('aria-invalid', 'true')
  // 실패한 뒤에도 방문자 상태 그대로다.
  await expect(await readAuthState(page)).toContainText('방문자')
})

test('AC-2 계정이 없어도 같은 문구다(계정 유무를 알리지 않는다)', async ({ page }) => {
  await page.goto('/login')
  await submit(page, 'nobody@example.test', PASSWORD)
  await expect(page.getByRole('alert')).toContainText('이메일 또는 비밀번호가 맞지 않아요.')
})

test('실패 뒤 올바른 계정으로 다시 로그인할 수 있다', async ({ page }) => {
  await page.goto('/login')
  await submit(page, 'member@example.test', 'wrong-password')
  await expect(page.getByRole('alert')).toBeVisible()
  await page.getByLabel('비밀번호').fill(PASSWORD)
  await page.getByRole('button', { name: '로그인' }).click()
  await expect(page).toHaveURL(/\/quiz$/)
})

test('실패 종류는 서버 message가 아니라 code로 가른다', async ({ page }) => {
  await page.goto('/login')
  const result = await page.evaluate(async () => {
    const { ApiError } = await import('/src/api/client.ts')
    const { classifyLoginFailure } = await import('/src/auth/login.ts')
    const make = (status: number, code: string, message: string, retry?: number) =>
      new ApiError(status, { code, message, request_id: 'r-test', ...(retry ? { retry_after_seconds: retry } : {}) })
    return {
      credentials: classifyLoginFailure(make(401, 'invalid_credentials', '아무 글자나')),
      rateLimited: classifyLoginFailure(make(429, 'rate_limited', 'x', 30)),
      unavailable: classifyLoginFailure(make(503, 'service_unavailable', 'x')),
      network: classifyLoginFailure(make(0, 'network_error', 'x')),
      notAnApiError: classifyLoginFailure(new Error('boom')),
    }
  })
  expect(result.credentials).toEqual({ kind: 'credentials' })
  expect(result.rateLimited).toEqual({ kind: 'rate_limited', retryAfterSeconds: 30 })
  expect(result.unavailable).toEqual({ kind: 'unavailable' })
  expect(result.network).toEqual({ kind: 'unavailable' })
  expect(result.notAnApiError).toEqual({ kind: 'unavailable' })
})

test('로그인 직후 상태가 확인된 경우에만 이동한다(E03 실패·쿠키 미적용이면 이동하지 않는다)', async ({ page }) => {
  await page.goto('/login')
  const result = await page.evaluate(async () => {
    const { confirmLogin } = await import('/src/auth/login.ts')
    const state = (status: string, role: string) => ({ status, role, displayName: null })
    return {
      member: await confirmLogin(async () => state('ready', 'member') as never),
      operator: await confirmLogin(async () => state('ready', 'operator') as never),
      // E03이 네트워크 오류·503으로 실패하면 refresh는 예외 없이 status 'error', role 'visitor'를 돌려준다
      stateError: await confirmLogin(async () => state('error', 'visitor') as never),
      // 쿠키가 적용되지 않아 E03이 authenticated: false를 돌려주면 ready이지만 방문자다
      stillVisitor: await confirmLogin(async () => state('ready', 'visitor') as never),
      stillLoading: await confirmLogin(async () => state('loading', 'visitor') as never),
    }
  })
  expect(result.member).toEqual({ ok: true, role: 'member' })
  expect(result.operator).toEqual({ ok: true, role: 'operator' })
  expect(result.stateError).toEqual({ ok: false })
  expect(result.stillVisitor).toEqual({ ok: false })
  expect(result.stillLoading).toEqual({ ok: false })
})
