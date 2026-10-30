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

// MEG-76 용어 바텀시트의 E06·E07 호출 규칙. 브라우저의 실제 fetch 경로로 서버 응답을 합성해 호출 횟수와 실패 분기를 시험한다.
// 실제 백엔드의 E06·E07은 이 시험이 확인하지 못한다.
const termNote = {
  id: 11, revision: 1, title: '용어 시험', studied_on: null, subjects: [], sources: [],
  body_markdown: '앞 ExampleTerm 뒤', images: {},
  glossary_terms: [{ term_id: 7, key: 'exampleterm', label: 'ExampleTerm' }],
  glossary_spans: [{ term_id: 7, start: 2, end: 13 }],
}
const glossary = (images: { id: number; url: string; alt: string }[] = []) => ({
  term: { id: 7, key: 'exampleterm', label: 'ExampleTerm' }, body_markdown: '합성 설명 문장입니다.', images,
})
const serverError = (status: number) => ({
  status,
  json: { error: { code: status === 404 ? 'not_found' : status === 429 ? 'rate_limited' : 'internal_error', message: 'x', request_id: 'r-test-0001' } },
})

type TermRoutes = {
  member?: boolean
  glossaryStatus?: number // 200이 아니면 그 상태의 오류로 답한다
  glossaryBody?: () => object
  viewStatus?: number // 200이 아니면 그 상태의 오류로 답한다
  recorded?: boolean
}

// 노트·사전·열람 기록 응답을 합성하고 E06·E07 호출 횟수를 센다.
async function setupTerm(page: Page, options: TermRoutes = {}) {
  const calls = { glossary: 0, views: 0, viewBodies: [] as unknown[] }
  await page.route('**/api/me', (route) => route.fulfill({
    json: options.member ? { authenticated: true, role: 'member', display_name: '합성 사용자' } : { authenticated: false },
  }))
  await page.route('**/api/notes/11', (route) => route.fulfill({ json: termNote }))
  await page.route('**/api/glossary/7', (route) => {
    calls.glossary += 1
    if (options.glossaryStatus && options.glossaryStatus !== 200) return route.fulfill(serverError(options.glossaryStatus))
    return route.fulfill({ json: (options.glossaryBody ?? glossary)() })
  })
  await page.route('**/api/term-views', (route) => {
    calls.views += 1
    calls.viewBodies.push(route.request().postDataJSON())
    if (options.viewStatus && options.viewStatus !== 200) return route.fulfill(serverError(options.viewStatus))
    return route.fulfill({ json: { recorded: options.recorded ?? Boolean(options.member) } })
  })
  return calls
}

const termLink = (page: Page) => page.getByRole('link', { name: 'ExampleTerm' })
const termSheet = (page: Page) => page.getByRole('dialog', { name: 'ExampleTerm' })
const viewNotice = (page: Page) => page.getByText('열람 기록을 저장하지 못했어요')

test('E07은 E06 성공 뒤 열 때마다 한 번, 용어 번호와 함께 부른다', async ({ page }) => {
  const calls = await setupTerm(page, { member: true })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await expect.poll(() => calls.views).toBe(1)
  expect(calls.viewBodies).toEqual([{ term_id: 7 }])
  await expect(viewNotice(page)).toHaveCount(0)
  // 닫았다 다시 열면 새로 한 번 더(열기당 한 번)
  await page.keyboard.press('Escape')
  await termLink(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await expect.poll(() => calls.views).toBe(2)
})

test('방문자도 E07을 부르고 recorded: false는 정상이라 안내도 로그인 시트도 뜨지 않는다', async ({ page }) => {
  const calls = await setupTerm(page, { member: false })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await expect.poll(() => calls.views).toBe(1)
  await page.waitForTimeout(300)
  await expect(viewNotice(page)).toHaveCount(0)
  await expect(page.getByRole('dialog', { name: '로그인이 필요해요' })).toHaveCount(0)
})

for (const [name, options] of [
  ['recorded: false', { recorded: false }],
  ['500 실패', { viewStatus: 500 }],
] as const) {
  test(`로그인 상태에서 E07이 ${name}이면 설명은 유지하고 짧게 안내하며 로그인 안내는 띄우지 않는다`, async ({ page }) => {
    const calls = await setupTerm(page, { member: true, ...options })
    await page.goto('/notes/11')
    await termLink(page).click()
    await expect(viewNotice(page)).toBeVisible()
    await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
    expect(calls.views).toBe(1)
    await expect(page.getByRole('dialog', { name: '로그인이 필요해요' })).toHaveCount(0)
  })
}

test('E06이 404면 안내만 보이고 열람은 기록하지 않는다', async ({ page }) => {
  const calls = await setupTerm(page, { glossaryStatus: 404 })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByText('설명을 찾을 수 없어요')).toBeVisible()
  await page.waitForTimeout(300)
  expect(calls.views).toBe(0)
})

test('E06이 실패하면 오류와 다시 시도가 보이고, 다시 시도해 성공하면 열람을 한 번 기록한다', async ({ page }) => {
  const calls = await setupTerm(page, { glossaryStatus: 500 })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByRole('alert')).toContainText('설명을 불러오지 못했어요')
  expect(calls.views).toBe(0)
  await page.unroute('**/api/glossary/7')
  await page.route('**/api/glossary/7', (route) => route.fulfill({ json: glossary() }))
  await termSheet(page).getByRole('button', { name: '다시 시도' }).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await expect.poll(() => calls.views).toBe(1)
})

test('이미지가 안 열리면 E06을 한 번 다시 부르고, 재실패하면 대체 글을 보이며 E07은 다시 보내지 않는다', async ({ page }) => {
  let n = 0
  const failedImages: string[] = []
  page.on('requestfailed', (request) => { if (request.url().includes('/glossary-broken-')) failedImages.push(request.url()) })
  const calls = await setupTerm(page, {
    member: true,
    glossaryBody: () => {
      n += 1
      return glossary([{ id: 3, url: `http://127.0.0.1:1/glossary-broken-${n}.png`, alt: '합성 구조도' }])
    },
  })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByText('이미지를 불러오지 못했어요')).toBeVisible()
  await page.waitForTimeout(500)
  // 처음 URL과 다시 받은 URL이 각각 한 번씩만 실패하고 더 되풀이하지 않는다
  expect(new Set(failedImages).size).toBe(failedImages.length)
  expect(failedImages.length).toBeLessThanOrEqual(2)
  // 이미지 때문에 E06을 다시 받아도 E07은 열기당 한 번이다
  expect(calls.views).toBe(1)
})

// PR #58 Codex 리뷰 P2: 다시 받은 E06 응답에서 실패한 이미지가 빠지면 이미지 영역이 대체 글도 없이 사라졌다.
test('E06을 다시 불러 응답에서 이미지가 빠져도 대체 글로 보이고 설명은 유지되며 E07은 다시 보내지 않는다', async ({ page }) => {
  let imageFailed = false
  page.on('requestfailed', (request) => { if (request.url().includes('/glossary-dropped.png')) imageFailed = true })
  const calls = await setupTerm(page, {
    member: true,
    // 이미지가 한 번 실패한 뒤(다시 받는 요청)에는 이미지 목록이 비어 온다
    glossaryBody: () => glossary(imageFailed ? [] : [{ id: 3, url: 'http://127.0.0.1:1/glossary-dropped.png', alt: '합성 구조도' }]),
  })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByText('이미지를 불러오지 못했어요')).toBeVisible()
  await expect(termSheet(page).getByText('(합성 구조도)')).toBeVisible()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await page.waitForTimeout(300)
  expect(calls.views).toBe(1)
  await expect(viewNotice(page)).toHaveCount(0)
})

test('E06을 다시 불러도 이미지 URL이 같으면 대체 글로 닫는다', async ({ page }) => {
  const calls = await setupTerm(page, { glossaryBody: () => glossary([{ id: 3, url: 'http://127.0.0.1:1/glossary-same.png', alt: '합성 구조도' }]) })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByText('이미지를 불러오지 못했어요')).toBeVisible()
  await page.waitForTimeout(300)
  expect(calls.glossary).toBeGreaterThanOrEqual(2)
  expect(calls.glossary).toBeLessThanOrEqual(4) // StrictMode의 첫 호출이 더 있을 수 있다
  expect(calls.views).toBe(1)
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

// MEG-90 용어 시트 안 즐겨찾기(E08)의 요청 규칙과 오류 분기. 브라우저의 실제 fetch 경로로 서버 응답을 합성해 요청 횟수·본문·실패 처리를 시험한다.
// 실제 백엔드의 E08과 서버 측 "저장되지 않음"은 이 시험이 확인하지 못한다.
type FavoriteRoutes = {
  member?: boolean
  initialFavorite?: boolean // E06의 is_favorite(로그인 사용자만 응답에 포함)
  favoriteResponse?: () => { status: number; body?: object } | null // null이면 정상 저장
  delayMs?: number
  gate?: Promise<void> // 이 약속이 풀릴 때까지 E08 응답을 보류한다(요청 중 시트를 닫는 경우를 시험한다)
  note?: object // 노트 응답을 바꾼다(같은 용어가 여러 번 나오는 본문 등)
}

async function setupFavorite(page: Page, options: FavoriteRoutes = {}) {
  const calls = { favorites: 0, bodies: [] as unknown[], glossary: 0 }
  let saved = options.initialFavorite ?? false
  await page.route('**/api/me', (route) => route.fulfill({
    json: options.member ? { authenticated: true, role: 'member', display_name: '합성 사용자' } : { authenticated: false },
  }))
  await page.route('**/api/notes/11', (route) => route.fulfill({ json: options.note ?? termNote }))
  // 노트 목록으로 옮기는 시험이 쓴다(앱 안 링크 이동)
  await page.route('**/api/notes', (route) => route.fulfill({ json: { subjects: [], notes: [] } }))
  await page.route('**/api/glossary/7', (route) => {
    calls.glossary += 1
    return route.fulfill({ json: options.member ? { ...glossary(), is_favorite: saved } : glossary() })
  })
  await page.route('**/api/term-views', (route) => route.fulfill({ json: { recorded: Boolean(options.member) } }))
  await page.route('**/api/favorites/7', async (route) => {
    calls.favorites += 1
    const body = route.request().postDataJSON() as { favorited: boolean }
    calls.bodies.push(body)
    if (options.delayMs) await new Promise((resolve) => setTimeout(resolve, options.delayMs))
    if (options.gate) await options.gate
    const failure = options.favoriteResponse?.()
    if (failure) return route.fulfill({ status: failure.status, json: failure.body ?? serverError(failure.status).json })
    saved = body.favorited
    return route.fulfill({ json: { term_id: 7, is_favorite: saved } })
  })
  return calls
}

const favoriteOff = (page: Page) => termSheet(page).getByRole('button', { name: '즐겨찾기', exact: true })
const favoriteOn = (page: Page) => termSheet(page).getByRole('button', { name: '즐겨찾기함' })
const favoriteAlert = (page: Page) => termSheet(page).getByRole('alert')
const loginPromptSheet = (page: Page) => page.getByRole('dialog', { name: '로그인이 필요해요' })

test('즐겨찾기는 응답을 받은 뒤에만 눌림으로 바뀌고, 요청 중 중복 클릭은 한 번만 보낸다', async ({ page }) => {
  const calls = await setupFavorite(page, { member: true, delayMs: 500 })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await favoriteOff(page).click()
  // 응답 전에는 눌린 것처럼 보이지 않고, 버튼은 막혀 있다
  await expect(favoriteOff(page)).toHaveAttribute('aria-pressed', 'false')
  await expect(favoriteOff(page)).toHaveAttribute('aria-disabled', 'true')
  await favoriteOff(page).click({ force: true })
  await expect(favoriteOn(page)).toHaveAttribute('aria-pressed', 'true')
  expect(calls.favorites).toBe(1)
  expect(calls.bodies).toEqual([{ favorited: true }])
})

test('E06의 is_favorite가 true면 눌린 채 열리고, 누르면 해제 요청을 보낸다', async ({ page }) => {
  const calls = await setupFavorite(page, { member: true, initialFavorite: true })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(favoriteOn(page)).toHaveAttribute('aria-pressed', 'true')
  await favoriteOn(page).click()
  await expect(favoriteOff(page)).toHaveAttribute('aria-pressed', 'false')
  expect(calls.bodies).toEqual([{ favorited: false }])
})

test('방문자도 E08을 보내 401 login_required를 받고, 용어 시트가 닫히며 로그인 안내가 열린다', async ({ page }) => {
  const calls = await setupFavorite(page, { member: false, favoriteResponse: () => ({ status: 401, body: { error: { code: 'login_required', message: 'Login is required', request_id: 'r-test-0001' } } }) })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await favoriteOff(page).click()
  await expect(loginPromptSheet(page)).toBeVisible()
  await expect(termSheet(page)).toBeHidden()
  expect(calls.favorites).toBe(1)
  // 저장된 것처럼 보이지 않는다
  await expect(page.getByText('즐겨찾기에 저장했어요')).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(termLink(page)).toBeFocused()
})

for (const [name, status, code, message] of [
  ['403 login_required(상태가 다름)', 403, 'login_required', 'Login is required'],
  ['401 invalid_credentials(code가 다름)', 401, 'invalid_credentials', 'Invalid email or password'],
  ['401이어도 message만 같고 code가 다름', 401, 'something_else', 'Login is required'],
  ['404 not_found', 404, 'not_found', 'Resource not found'],
  ['422 validation_failed', 422, 'validation_failed', 'Validation failed'],
  ['429 rate_limited', 429, 'rate_limited', 'Too many requests'],
  ['500 internal_error', 500, 'internal_error', 'Internal server error'],
] as const) {
  test(`즐겨찾기 ${name}는 로그인 안내를 열지 않고 시트 안에 오류를 보이며 눌림 상태를 바꾸지 않는다`, async ({ page }) => {
    const calls = await setupFavorite(page, { member: true, favoriteResponse: () => ({ status, body: { error: { code, message, request_id: 'r-test-0001' } } }) })
    await page.goto('/notes/11')
    await termLink(page).click()
    await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
    await favoriteOff(page).click()
    await expect(favoriteAlert(page)).toHaveText('즐겨찾기를 저장하지 못했어요')
    await expect(loginPromptSheet(page)).toHaveCount(0)
    await expect(termSheet(page)).toBeVisible()
    await expect(favoriteOff(page)).toHaveAttribute('aria-pressed', 'false')
    await expect(favoriteOn(page)).toHaveCount(0)
    expect(calls.favorites).toBe(1)
  })
}

test('즐겨찾기 오류 뒤 다시 누르면 성공하고 오류 안내는 사라진다', async ({ page }) => {
  let failing = true
  const calls = await setupFavorite(page, { member: true, favoriteResponse: () => (failing ? { status: 500 } : null) })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await favoriteOff(page).click()
  await expect(favoriteAlert(page)).toBeVisible()
  failing = false
  await favoriteOff(page).click()
  await expect(favoriteOn(page)).toHaveAttribute('aria-pressed', 'true')
  await expect(favoriteAlert(page)).toHaveCount(0)
  expect(calls.favorites).toBe(2)
})

// PR #61 Codex 리뷰 P2: 요청을 보낸 뒤 시트를 닫거나 화면을 옮겼을 때 늦게 도착한 E08 응답이 현재 화면에 영향을 주면 안 된다.
// 응답을 약속(gate)으로 붙잡아 두었다가 원하는 때 푼다. 서버 저장이 취소되는 것은 아니고, 화면이 그 결과를 쓰지 않는 것만 확인한다.
function gate() {
  let release!: () => void
  const promise = new Promise<void>((resolve) => { release = resolve })
  return { promise, release }
}

const loginRequiredFailure = () => ({ status: 401, body: { error: { code: 'login_required', message: 'Login is required', request_id: 'r-test-0001' } } })

test('E08 응답을 기다리는 중 시트를 닫으면 늦게 온 401이 로그인 안내를 열지 않는다', async ({ page }) => {
  const held = gate()
  const calls = await setupFavorite(page, { member: true, gate: held.promise, favoriteResponse: loginRequiredFailure })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await favoriteOff(page).click()
  await expect.poll(() => calls.favorites).toBe(1)
  await page.keyboard.press('Escape')
  await expect(termSheet(page)).toBeHidden()
  held.release()
  await page.waitForTimeout(400)
  await expect(loginPromptSheet(page)).toHaveCount(0)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(termLink(page)).toBeFocused()
})

test('E08 응답을 기다리는 중 목록으로 옮겨도 늦게 온 401이 이전 안내·포커스 이동·스크롤 잠금을 남기지 않는다', async ({ page }) => {
  const held = gate()
  const calls = await setupFavorite(page, { member: true, gate: held.promise, favoriteResponse: loginRequiredFailure })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await favoriteOff(page).click()
  await expect.poll(() => calls.favorites).toBe(1)
  // 시트를 닫고 앱 안 링크로 목록(/)으로 옮긴다(SPA 이동)
  await page.keyboard.press('Escape')
  await page.getByRole('link', { name: '목록' }).click()
  await expect(page).toHaveURL(/\/$/)
  held.release()
  await page.waitForTimeout(400)
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('body')).not.toHaveCSS('overflow', 'hidden')
  expect(await page.evaluate(() => document.activeElement?.closest('dialog') ?? null)).toBeNull()
})

test('E08 응답을 기다리는 중 시트를 닫고 새 시트를 열면 이전 응답(401)이 새 시트를 닫거나 바꾸지 않는다', async ({ page }) => {
  const held = gate()
  const calls = await setupFavorite(page, { member: true, gate: held.promise, favoriteResponse: loginRequiredFailure })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await favoriteOff(page).click()
  await expect.poll(() => calls.favorites).toBe(1)
  await page.keyboard.press('Escape')
  await expect(termSheet(page)).toBeHidden()
  // 같은 용어를 다시 열면 새 시트다
  await termLink(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  held.release()
  await page.waitForTimeout(400)
  await expect(termSheet(page)).toBeVisible()
  await expect(loginPromptSheet(page)).toHaveCount(0)
  await expect(favoriteOff(page)).toHaveAttribute('aria-pressed', 'false')
  await expect(favoriteOff(page)).not.toHaveAttribute('aria-disabled', 'true')
  await expect(favoriteAlert(page)).toHaveCount(0)
})

for (const [name, failure] of [
  ['성공', null],
  ['일반 오류(500)', { status: 500 }],
] as const) {
  test(`E08 응답을 기다리는 중 시트를 닫고 새 시트를 연 뒤 ${name} 응답이 와도 새 시트에 이전 상태나 안내가 남지 않는다`, async ({ page }) => {
    const held = gate()
    const calls = await setupFavorite(page, { member: true, gate: held.promise, favoriteResponse: () => failure })
    await page.goto('/notes/11')
    await termLink(page).click()
    await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
    await favoriteOff(page).click()
    await expect.poll(() => calls.favorites).toBe(1)
    await page.keyboard.press('Escape')
    await expect(termSheet(page)).toBeHidden()
    await termLink(page).click()
    await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
    held.release()
    await page.waitForTimeout(400)
    // 새 시트는 자기 상태 그대로다: 이전 요청의 저장 표시도 오류 안내도 없다
    await expect(favoriteOff(page)).toHaveAttribute('aria-pressed', 'false')
    await expect(favoriteAlert(page)).toHaveCount(0)
    await expect(termSheet(page).getByText('즐겨찾기에 저장했어요')).toHaveCount(0)
    await expect(loginPromptSheet(page)).toHaveCount(0)
  })
}

// 같은 용어가 본문에 여러 번 나올 때 두 번째 링크로 열었다면 포커스는 첫 번째가 아니라 그 링크로 돌아와야 한다.
const twiceNote = {
  ...termNote,
  body_markdown: 'ExampleTerm 그리고 ExampleTerm',
  glossary_spans: [{ term_id: 7, start: 0, end: 11 }, { term_id: 7, start: 16, end: 27 }],
}

for (const [name, close] of [
  ['Esc', (page: Page) => page.keyboard.press('Escape')],
  ['닫기 버튼', (page: Page) => page.getByRole('button', { name: '닫기' }).click()],
  ['막(스크림) 누르기', (page: Page) => page.mouse.click(195, 20)],
] as const) {
  test(`같은 용어가 두 번 나와도 두 번째 링크로 연 로그인 안내를 ${name}로 닫으면 그 링크로 포커스가 돌아오고 Enter로 다시 열린다`, async ({ page }) => {
    await setupFavorite(page, { member: false, note: twiceNote, favoriteResponse: loginRequiredFailure })
    await page.goto('/notes/11')
    await expect(termLink(page)).toHaveCount(2)
    await termLink(page).nth(1).click()
    await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
    await favoriteOff(page).click()
    await expect(loginPromptSheet(page)).toBeVisible()
    await close(page)
    await expect(loginPromptSheet(page)).toBeHidden()
    await expect(termLink(page).nth(1)).toBeFocused()
    await expect(termLink(page).nth(0)).not.toBeFocused()
    await termLink(page).nth(1).press('Enter')
    await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  })
}
