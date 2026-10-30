import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const subjects = [{ id: 1, name: '네트워크', note_count: 2 }, { id: 2, name: 'AI', note_count: 1 }]
const notes = [
  { id: 11, title: '네트워크 기초', studied_on: '2026-10-14', subjects: [subjects[0]], parent_note_id: null },
  { id: 12, title: '연결과 학습', studied_on: null, subjects, parent_note_id: null },
]
async function setup(page: Page, operator = false) {
  await page.route('**/api/me', (route) => route.fulfill({ json: operator ? { authenticated: true, role: 'operator' } : { authenticated: false } }))
  await page.route('**/api/notes?*', (route) => {
    const subject = new URL(route.request().url()).searchParams.get('subject_id')
    return route.fulfill({ json: { subjects, notes: notes.filter((note) => note.subjects.some((s) => String(s.id) === subject)) } })
  })
  await page.route('**/api/notes', (route) => route.fulfill({ json: { subjects, notes } }))
}

test('AC-1·AC-2 과목 선택, 노트 열기, 뒤로 돌아오기', async ({ page }, testInfo) => {
  await setup(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('region', { name: '노트 목록' }).getByRole('link')).toHaveCount(2)
  await testInfo.attach('목록 기본', { body: await page.screenshot(), contentType: 'image/png' })
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page).toHaveURL(/subject_id=2$/)
  await expect(page.getByRole('button', { name: 'AI', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('link', { name: /네트워크 기초/ })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /연결과 학습/ })).toBeVisible()
  await expect(page.getByText('null')).toHaveCount(0)
  await testInfo.attach('과목 선택', { body: await page.screenshot(), contentType: 'image/png' })
  await page.route('**/api/notes/12', (route) => route.fulfill({ json: { id: 12, revision: 1, title: '연결과 학습 노트', studied_on: null, subjects: [], sources: [], body_markdown: '본문', images: {}, glossary_terms: [], glossary_spans: [] } }))
  await page.getByRole('link', { name: /연결과 학습/ }).click()
  await expect(page).toHaveURL(/\/notes\/12$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('연결과 학습 노트')
  await testInfo.attach('노트 읽기 경로', { body: await page.screenshot(), contentType: 'image/png' })
  await page.goBack()
  await expect(page.getByRole('button', { name: 'AI', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('region', { name: '노트 목록' }).getByRole('link')).toHaveCount(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('빈 전체 목록과 빈 과목은 안내를 표시한다', async ({ page }) => {
  await setup(page)
  await page.route('**/api/notes', (route) => route.fulfill({ json: { subjects: [], notes: [] } }))
  await page.goto('/')
  await expect(page.getByText('아직 볼 수 있는 노트가 없어요.')).toBeVisible()
  await page.goto('/?subject_id=999')
  await expect(page.getByText('이 과목에는 노트가 없어요.')).toBeVisible()
  await page.getByRole('button', { name: '전체', exact: true }).click()
  await expect(page).toHaveURL(/\/$/)
})

test('조회 실패 안내 후 선택한 과목을 재시도한다', async ({ page }) => {
  await setup(page)
  let failed = true
  await page.route('**/api/notes?*', (route) => failed
    ? route.fulfill({ status: 503, json: { error: { code: 'service_unavailable', message: 'secret server detail', request_id: 'synthetic' } } })
    : route.fulfill({ json: { subjects, notes: [notes[1]] } }))
  await page.goto('/')
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('노트를 불러오지 못했어요')
  await expect(page.getByText('secret server detail')).toHaveCount(0)
  await expect(page.getByRole('region', { name: '노트 목록' }).getByRole('link')).toHaveCount(0)
  failed = false
  await page.getByRole('button', { name: '다시 시도' }).click()
  await expect(page.getByRole('link', { name: /연결과 학습/ })).toBeVisible()
  await expect(page).toHaveURL(/subject_id=2$/)
})

test('늦은 과목 응답이 최신 선택을 덮어쓰지 않는다', async ({ page }) => {
  await setup(page)
  let release: () => void = () => {}
  let started: () => void = () => {}
  const held = new Promise<void>((resolve) => { release = resolve })
  const requested = new Promise<void>((resolve) => { started = resolve })
  await page.route('**/api/notes?subject_id=1', async (route) => {
    started()
    await held
    await route.fulfill({ json: { subjects, notes: [notes[0]] } }).catch(() => {})
  })
  await page.goto('/')
  await page.getByRole('button', { name: '네트워크', exact: true }).click()
  await requested
  await expect(page.getByRole('status')).toContainText('불러오는 중')
  await page.getByRole('button', { name: 'AI', exact: true }).click()
  await expect(page.getByRole('link', { name: /연결과 학습/ })).toBeVisible()
  release()
  await expect(page.getByRole('button', { name: 'AI', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('link', { name: /네트워크 기초/ })).toHaveCount(0)
})

test('운영자 헤더와 서버가 반환한 비공개 노트를 표시한다', async ({ page }, testInfo) => {
  await setup(page, true)
  await page.route('**/api/notes', (route) => route.fulfill({ json: { subjects, notes: [{ ...notes[0], title: '운영자 비공개 노트', is_published: false, revision: 1, needs_review: true }] } }))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('link', { name: '운영자 메뉴' })).toHaveAttribute('href', '/admin')
  await expect(page.getByRole('button', { name: '내 계정', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: /운영자 비공개 노트/ })).toBeVisible()
  await testInfo.attach('운영자 목록', { body: await page.screenshot(), contentType: 'image/png' })
})

test('일반 사용자와 좁은 화면에서 목록·키보드 조작을 제공한다', async ({ page }) => {
  await setup(page)
  await page.route('**/api/me', (route) => route.fulfill({ json: { authenticated: true, role: 'member' } }))
  await page.setViewportSize({ width: 320, height: 700 })
  await page.goto('/')
  await expect(page.getByRole('button', { name: '내 계정', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '운영자 메뉴' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: '오늘의 퀴즈' })).toHaveAttribute('href', '/quiz')
  const ai = page.getByRole('button', { name: 'AI', exact: true })
  await ai.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('region', { name: '노트 목록' }).getByRole('link')).toHaveCount(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('네트워크 오류와 잘못된 과목을 복구할 수 있다', async ({ page }) => {
  await setup(page)
  await page.route('**/api/notes', (route) => route.abort('failed'))
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('노트를 불러오지 못했어요')
  await page.unroute('**/api/notes')
  await page.route('**/api/notes', (route) => route.fulfill({ json: { subjects, notes } }))
  await page.getByRole('button', { name: '다시 시도' }).click()
  await expect(page.getByRole('region', { name: '노트 목록' }).getByRole('link')).toHaveCount(2)
  await page.route('**/api/notes?subject_id=bad', (route) => route.fulfill({ status: 422, json: { error: { code: 'validation_failed', message: 'invalid', request_id: 'synthetic' } } }))
  await page.goto('/?subject_id=bad')
  await expect(page.getByRole('alert')).toContainText('과목을 확인할 수 없어요')
  await page.getByRole('button', { name: '전체', exact: true }).click()
  await expect(page.getByRole('region', { name: '노트 목록' }).getByRole('link')).toHaveCount(2)
})

// MEG-74 노트 읽기(F1-2). 브라우저의 실제 fetch 경로로 E05 응답을 합성해 시험한다. 실제 백엔드의 E05는 아직 없어 확인하지 못한다.
test('이미지가 열리지 않으면 E05를 다시 부르고, 새 URL도 실패하면 대체 글로 보인다', async ({ page }) => {
  await page.route('**/api/me', (route) => route.fulfill({ json: { authenticated: false } }))
  // 실제 E05 모양(note-image 토큰)의 응답을 가로채 이미지 URL을 깨뜨린다. 응답 횟수를 센다.
  let calls = 0
  const failedImages: string[] = []
  page.on('requestfailed', (request) => { if (request.url().includes('/broken-')) failedImages.push(request.url()) })
  await page.route('**/api/notes/99', (route) => {
    calls += 1
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        id: 99, revision: 1, title: '이미지 시험', studied_on: null, subjects: [], sources: [],
        body_markdown: '앞 ![그림](note-image:blk-1) 뒤',
        images: { 'blk-1': { url: `http://127.0.0.1:1/broken-${calls}.png`, alt: '그림', expires_at: '2026-10-23T05:35:00Z' } },
        glossary_terms: [], glossary_spans: [],
      }),
    })
  })
  await page.goto('/notes/99')
  await expect(page.getByText('이미지를 불러오지 못했어요')).toBeVisible()
  // 처음 URL과 다시 받은 URL이 각각 한 번씩만 실패하고 더 되풀이하지 않는다(개발 서버의 StrictMode가 E05를 한 번 더 부를 수 있어 호출 수로는 세지 않는다)
  await page.waitForTimeout(500)
  expect(failedImages).toHaveLength(2)
  expect(new Set(failedImages).size).toBe(2)
  expect(calls).toBeGreaterThanOrEqual(2)
})

test('본문 속 HTML은 해석하지 않고 글자 그대로 보인다', async ({ page }) => {
  await page.route('**/api/me', (route) => route.fulfill({ json: { authenticated: false } }))
  await page.route('**/api/notes/98', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      id: 98, revision: 1, title: 'HTML 시험', studied_on: null, subjects: [], sources: [],
      body_markdown: '<b>굵게 아님</b> <img src=x onerror="window.__xss=1">\n\n[나쁜 링크](javascript:window.__xss=1)',
      images: {}, glossary_terms: [], glossary_spans: [],
    }),
  }))
  await page.goto('/notes/98')
  await expect(page.getByText('<b>굵게 아님</b>')).toBeVisible()
  await expect(page.locator('[data-note-body] b')).toHaveCount(0)
  await expect(page.locator('[data-note-body] img')).toHaveCount(0)
  await expect(page.getByRole('link', { name: '나쁜 링크' })).toHaveCount(0)
  expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined()
})


// AC-3 안 되는 경우: 위치를 계산하지 못하는 글자(들여쓴 코드 블록, 지원하지 않는 이름 엔티티)에 걸친 선택은 추정하지 않고 null이다.
test('위치를 계산하지 못하는 글자에 걸친 선택은 null이다', async ({ page }) => {
  await page.route('**/api/me', (route) => route.fulfill({ json: { authenticated: false } }))
  await page.route('**/api/notes/97', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      id: 97, revision: 1, title: '위치 시험', studied_on: null, subjects: [], sources: [],
      body_markdown: '앞 글자\n\n    들여쓴 코드\n\n&eacute; 뒤 글자\n\n정상 글자',
      images: {}, glossary_terms: [], glossary_spans: [],
    }),
  }))
  await page.goto('/notes/97')
  await expect(page.getByText('들여쓴 코드')).toBeVisible()
  const result = (from: string, to: string) => page.evaluate(async ({ from, to }) => {
    const { sourceRangeOfSelection } = await import('/src/notes/selection.ts')
    const root = document.querySelector('[data-note-body]')!
    const find = (needle: string) => {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
      for (let node = walker.nextNode(); node; node = walker.nextNode()) if (node.textContent?.includes(needle)) return node as Text
      throw new Error(needle)
    }
    const a = find(from)
    const b = find(to)
    const range = document.createRange()
    range.setStart(a, 0)
    range.setEnd(b, b.textContent!.length)
    return sourceRangeOfSelection(root, range)
  }, { from, to })
  expect(await result('들여쓴 코드', '들여쓴 코드')).toBeNull()
  expect(await result('앞 글자', '들여쓴 코드')).toBeNull() // 위치를 모르는 글자가 범위 안에 끼어 있다
  expect(await result('뒤 글자', '뒤 글자')).toBeNull() // 지원하지 않는 엔티티가 든 글 덩어리(문단) 전체가 계산 불가다
  expect(await result('정상 글자', '정상 글자')).not.toBeNull() // 다른 문단은 그대로 계산된다
})

// PR #55 AI 리뷰 P2 ① E05를 다시 불러도 이미지 URL이 같으면 img의 src가 그대로라 다시 불러오지 않는다. 실패로 닫고 대체 글을 보여야 한다.
test('E05를 다시 불러도 이미지 URL이 같으면 대체 글로 닫는다', async ({ page }) => {
  await page.route('**/api/me', (route) => route.fulfill({ json: { authenticated: false } }))
  let calls = 0
  await page.route('**/api/notes/96', (route) => {
    calls += 1
    return route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        id: 96, revision: 1, title: '같은 URL 시험', studied_on: null, subjects: [], sources: [],
        body_markdown: '앞 ![그림](note-image:blk-1) 뒤',
        images: { 'blk-1': { url: 'http://127.0.0.1:1/same.png', alt: '그림', expires_at: '2026-10-23T05:35:00Z' } },
        glossary_terms: [], glossary_spans: [],
      }),
    })
  })
  await page.goto('/notes/96')
  await expect(page.getByText('이미지를 불러오지 못했어요')).toBeVisible()
  await page.waitForTimeout(300)
  expect(calls).toBeGreaterThanOrEqual(2)
  expect(calls).toBeLessThanOrEqual(3) // StrictMode의 첫 호출 한 번이 더 있을 수 있다
})

// PR #55 AI 리뷰 P2 ② 선택이 본문 밖이나 위치 없는 글자(이미지 대체 문구)에 걸치면 본문 부분만 잘라 돌려주지 않고 null이어야 한다.
test('선택이 본문 밖이나 이미지 대체 문구에 걸치면 null이다', async ({ page }) => {
  await page.route('**/api/me', (route) => route.fulfill({ json: { authenticated: false } }))
  await page.route('**/api/notes/95', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      id: 95, revision: 1, title: '선택 시험', studied_on: null, subjects: [], sources: [],
      body_markdown: 'abc ![그림](note-image:blk-1)',
      images: { 'blk-1': { url: 'http://127.0.0.1:1/x.png', alt: '그림', expires_at: '2026-10-23T05:35:00Z' } },
      glossary_terms: [], glossary_spans: [],
    }),
  }))
  await page.goto('/notes/95')
  await expect(page.getByText('이미지를 불러오지 못했어요')).toBeVisible()
  const select = (from: { selector: string; offset: number }, to: { selector: string; offset: number }) => page.evaluate(async ({ from, to }) => {
    const { sourceRangeOfSelection } = await import('/src/notes/selection.ts')
    const root = document.querySelector('[data-note-body]')!
    const textOf = (selector: string) => {
      const walker = document.createTreeWalker(document.querySelector(selector)!, NodeFilter.SHOW_TEXT)
      return walker.nextNode() as Text
    }
    const a = textOf(from.selector)
    const b = textOf(to.selector)
    const range = document.createRange()
    range.setStart(a, from.offset)
    range.setEnd(b, to.offset)
    return sourceRangeOfSelection(root, range)
  }, { from, to })
  const bodyText = '[data-note-body] [data-src]'
  const fallback = '[data-note-body] [role="img"]'
  // 본문 글자만 고르면 계산된다
  expect(await select({ selector: bodyText, offset: 1 }, { selector: bodyText, offset: 3 })).toEqual({ start: 1, end: 3 })
  // 본문에서 이미지 대체 문구까지 걸치면 null
  expect(await select({ selector: bodyText, offset: 1 }, { selector: fallback, offset: 5 })).toBeNull()
  // 제목에서 본문까지 걸치면 null
  expect(await select({ selector: 'h1', offset: 0 }, { selector: bodyText, offset: 3 })).toBeNull()
})

// MEG-77 로그인 안내 시트의 오류 분기. 브라우저의 실제 fetch 경로로 서버 응답을 합성한다.
// handleLoginRequired는 HTTP 401이면서 code가 login_required일 때만 시트를 연다. 그 밖은 호출한 화면의 기존 오류 처리다.
// 실제 백엔드의 401은 이 시험이 확인하지 못한다.
const errorBody = (code: string, message: string) => ({ error: { code, message, request_id: 'r-test-0001' } })

for (const [name, status, code, message, opens] of [
  ['401 login_required는 시트를 연다', 401, 'login_required', 'Login is required', true],
  ['403 login_required(상태가 다름)는 시트를 열지 않는다', 403, 'login_required', 'Login is required', false],
  ['401 invalid_credentials(code가 다름)는 시트를 열지 않는다', 401, 'invalid_credentials', 'Invalid email or password', false],
  ['401이어도 message만 같고 code가 다르면 시트를 열지 않는다', 401, 'something_else', 'Login is required', false],
  ['500 서버 오류는 시트를 열지 않는다', 500, 'internal_error', 'Internal server error', false],
  ['429 요청 과다는 시트를 열지 않는다', 429, 'rate_limited', 'Too many requests', false],
] as const) {
  test(`즐겨찾기 ${name}`, async ({ page }) => {
    await page.route('**/api/me', (route) => route.fulfill({ json: { authenticated: false } }))
    await page.route('**/api/favorites/7', (route) => route.fulfill({ status, json: errorBody(code, message) }))
    await page.goto('/dev/components')
    const demo = page.getByRole('region', { name: '로그인 안내 시트 (MEG-77)' })
    await demo.getByRole('button', { name: '즐겨찾기', exact: true }).click()
    const sheet = page.getByRole('dialog', { name: '로그인이 필요해요' })
    if (opens) {
      await expect(sheet).toBeVisible()
      await expect(page.getByTestId('favorite-status')).toHaveText('')
    } else {
      // 기존 오류 처리(데모의 실패 문구)로 넘어가고 시트는 열리지 않는다
      await expect(page.getByTestId('favorite-status')).toHaveText('즐겨찾기를 저장하지 못했어요')
      await expect(sheet).toHaveCount(0)
    }
    // 어느 경우에도 저장 성공 표시와 눌림 상태는 남지 않는다
    await expect(demo.getByRole('button', { name: '즐겨찾기함' })).toHaveCount(0)
  })
}

test('AI 설명도 401 login_required만 시트를 열고 다른 오류는 기존 오류 처리로 넘어간다', async ({ page }) => {
  await page.route('**/api/me', (route) => route.fulfill({ json: { authenticated: false } }))
  let status = 500
  await page.route('**/api/ai/explanations', (route) => route.fulfill(
    status === 401 ? { status, json: errorBody('login_required', 'Login is required') } : { status, json: errorBody('internal_error', 'Internal server error') },
  ))
  await page.goto('/dev/components')
  const demo = page.getByRole('region', { name: '로그인 안내 시트 (MEG-77)' })
  const sheet = page.getByRole('dialog', { name: '로그인이 필요해요' })
  await demo.getByRole('button', { name: 'AI 설명', exact: true }).click()
  await expect(page.getByTestId('ai-status')).toHaveText('AI 설명을 불러오지 못했어요')
  await expect(sheet).toHaveCount(0)
  status = 401
  await demo.getByRole('button', { name: 'AI 설명', exact: true }).click()
  await expect(sheet).toBeVisible()
})
