import { expect, test, type Page } from '@playwright/test'

// MEG-63 E01~E03을 배포된 환경에서 실제 브라우저로 확인한다(쿠키·Origin을 브라우저가 직접 붙인다).
// 필요한 값: E2E_BASE_URL, E2E_EMAIL, E2E_PASSWORD. Vercel 보호 배포면 E2E_ACCESS_URL(공유 링크)도 둔다.
// 비밀번호는 출력하지 않는다. 잘못된 비밀번호 시험이 계정 실패 횟수(15분에 5회) 1회를 쓴다.

const { E2E_BASE_URL, E2E_EMAIL, E2E_PASSWORD, E2E_ACCESS_URL } = process.env

test.skip(!E2E_BASE_URL || !E2E_EMAIL || !E2E_PASSWORD, 'E2E_BASE_URL, E2E_EMAIL, E2E_PASSWORD가 필요하다')

type ApiResult = { status: number; body: unknown }

// 페이지 안에서 같은 출처로 부른다. 브라우저가 Origin과 쿠키를 실제 화면과 똑같이 붙인다.
async function api(page: Page, method: string, path: string, body?: unknown): Promise<ApiResult> {
  return page.evaluate(
    async ({ method, path, body }) => {
      const res = await fetch(path, {
        method,
        credentials: 'same-origin',
        headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      const text = await res.text()
      return { status: res.status, body: text ? JSON.parse(text) : null }
    },
    { method, path, body },
  )
}

const sessionCookieNames = ['cs_session', 'cs_refresh']

test('E01~E03: 방문자 → 잘못된 비밀번호 → 로그인 → 내 상태 → 로그아웃', async ({ page, context }) => {
  // 보호된 배포는 공유 링크로 한 번 들어가 접근 쿠키를 받는다.
  await page.goto(E2E_ACCESS_URL ?? '/')
  await api(page, 'POST', '/api/auth/logout')

  await test.step('E03 방문자는 200 authenticated:false', async () => {
    expect(await api(page, 'GET', '/api/me')).toEqual({ status: 200, body: { authenticated: false } })
  })

  await test.step('E01 잘못된 비밀번호는 401 invalid_credentials, 쿠키 없음', async () => {
    const wrong = await api(page, 'POST', '/api/auth/login', { email: E2E_EMAIL, password: `${E2E_PASSWORD}-wrong` })
    expect(wrong.status).toBe(401)
    expect((wrong.body as { error: { code: string } }).error.code).toBe('invalid_credentials')
    const names = (await context.cookies()).map((c) => c.name)
    expect(names.filter((n) => sessionCookieNames.includes(n))).toEqual([])
  })

  let role = ''
  await test.step('AC-1 E01 로그인은 200과 역할, 세션 쿠키 2개(HttpOnly·Secure·Lax)', async () => {
    const ok = await api(page, 'POST', '/api/auth/login', { email: E2E_EMAIL, password: E2E_PASSWORD })
    expect(ok.status).toBe(200)
    role = (ok.body as { user: { role: string } }).user.role
    expect(['member', 'operator']).toContain(role)
    const cookies = (await context.cookies()).filter((c) => sessionCookieNames.includes(c.name))
    expect(cookies.map((c) => c.name).sort()).toEqual([...sessionCookieNames].sort())
    for (const c of cookies) {
      expect({ name: c.name, httpOnly: c.httpOnly, secure: c.secure, sameSite: c.sameSite, path: c.path }).toEqual({
        name: c.name,
        httpOnly: true,
        secure: true,
        sameSite: 'Lax',
        path: '/',
      })
    }
  })

  await test.step('AC-1 E03은 authenticated:true와 같은 역할', async () => {
    const me = await api(page, 'GET', '/api/me')
    expect(me.status).toBe(200)
    expect(me.body).toMatchObject({ authenticated: true, role })
  })

  await test.step('AC-2 E02 로그아웃은 204, 세션 쿠키가 지워진다', async () => {
    expect((await api(page, 'POST', '/api/auth/logout')).status).toBe(204)
    const names = (await context.cookies()).map((c) => c.name)
    expect(names.filter((n) => sessionCookieNames.includes(n))).toEqual([])
  })

  await test.step('AC-2 E03은 다시 authenticated:false', async () => {
    expect(await api(page, 'GET', '/api/me')).toEqual({ status: 200, body: { authenticated: false } })
  })
})
