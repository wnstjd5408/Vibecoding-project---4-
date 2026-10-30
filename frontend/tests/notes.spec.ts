import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// Exercise the real importer output, not a hand-written approximation of Markdown.
function importedBody() {
  const backend = fileURLToPath(new URL('../../backend/', import.meta.url))
  const fixture = readFileSync(new URL('../../backend/tests/fixtures/notion_nested_blocks.json', import.meta.url), 'utf8')
  return execFileSync('uv', ['run', '--no-sync', '--directory', backend, 'python', '-c',
    'import json,sys; from types import SimpleNamespace; from scripts.notion_content import convert; tree=json.load(sys.stdin); print(convert(SimpleNamespace(children=lambda key: tree[key]), "00000000-0000-4000-8000-000000000001").markdown)'],
  { input: fixture, encoding: 'utf8' }).trimEnd()
}

for (const width of [390, 1280]) {
  test(`가져온 토글 코드·표를 구조와 원문 위치를 유지해 표시한다 (${width}px)`, async ({ page }) => {
    const body = importedBody()
    await setup(page)
    await page.setViewportSize({ width, height: 844 })
    const start = [...body.slice(0, body.indexOf('ExampleTerm'))].length
    await page.route('**/api/notes/11', (route) => route.fulfill({ json: {
      id: 11, revision: 1, title: 'Imported synthetic note', studied_on: null, subjects: [], sources: [],
      body_markdown: body, images: {}, glossary_terms: [],
      glossary_spans: [{ start, end: start + 'ExampleTerm'.length, term_id: 1 }],
    } }))
    await page.goto('/notes/11')
    const root = page.locator('[data-note-body]')
    await expect(root.locator('pre code')).toHaveText(['print(1)\n\nprint(2)', 'nested()'])
    await expect(root.getByRole('table')).toHaveCount(1)
    await expect(root.getByRole('columnheader')).toHaveText(['Name', 'Value'])
    await expect(root.getByRole('cell')).toHaveText(['ExampleTerm', 'A | B', '<script>bad()</script>', 'Reference'])
    await expect(root.locator('td strong')).toHaveText('ExampleTerm')
    await expect(root.locator('[data-term-id="1"]')).toHaveText('ExampleTerm')
    await expect(root.getByRole('link', { name: 'Reference' })).toHaveAttribute('href', 'https://example.test/reference')
    await expect(root.locator('script')).toHaveCount(0)
    await expect(root.getByText('Child paragraph', { exact: true })).toBeVisible()
    const range = await root.evaluate(async (element) => {
      const { sourceRangeOfSelection } = await import('/src/notes/selection.ts')
      const term = element.querySelector('[data-term-id="1"]')!
      const selection = document.createRange()
      selection.selectNodeContents(term)
      return sourceRangeOfSelection(element, selection)
    })
    expect(range && body.slice(range.start, range.end)).toBe('ExampleTerm')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
}

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
  test(`E08 응답을 기다리는 중 시트를 닫고 새 시트를 연 뒤 ${name} 응답이 와도 새 시트에 오류·저장 완료 안내가 남지 않고 버튼은 서버가 저장한 값에 맞춰진다`, async ({ page }) => {
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
    // 이 시트에서 누른 요청이 아니라 오류 안내도 저장 완료 안내도 없다. 버튼은 서버가 저장한 값에 맞춰진다(성공이면 켜짐, 실패면 꺼짐 그대로).
    if (failure === null) await expect(favoriteOn(page)).toHaveAttribute('aria-pressed', 'true')
    else await expect(favoriteOff(page)).toHaveAttribute('aria-pressed', 'false')
    await expect(favoriteAlert(page)).toHaveCount(0)
    await expect(termSheet(page).getByText('즐겨찾기에 저장했어요')).toHaveCount(0)
    await expect(loginPromptSheet(page)).toHaveCount(0)
  })
}

// PR #61 Codex 리뷰 P2(2): 저장 요청이 진행 중일 때 시트를 닫았다 다시 열면, 서버는 이미 저장했는데 새 시트의 버튼이 꺼진 채로 남았다.
// 다시 연 시트는 진행 중인 요청을 이어서 보고(버튼이 막힘), 끝나면 서버가 저장한 값으로 버튼이 맞춰져야 한다. 요청을 취소하는 것이 서버 저장을 취소한다고 보지 않는다.
test('저장 중 시트를 닫았다 다시 열면 버튼이 막혀 있다가 끝나면 서버가 저장한 값(켜짐)으로 맞춰지고, 다음 클릭은 해제 요청을 보낸다', async ({ page }) => {
  const held = gate()
  const calls = await setupFavorite(page, { member: true, gate: held.promise })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await favoriteOff(page).click()
  await expect.poll(() => calls.favorites).toBe(1)
  await page.keyboard.press('Escape')
  await expect(termSheet(page)).toBeHidden()
  // 다시 열면 E06은 아직 저장 전이라 꺼짐이지만, 진행 중인 요청이 있어 버튼은 막혀 있다
  await termLink(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await expect(favoriteOff(page)).toHaveAttribute('aria-pressed', 'false')
  await expect(favoriteOff(page)).toHaveAttribute('aria-disabled', 'true')
  await favoriteOff(page).click({ force: true }) // 막혀 있으므로 새 요청이 나가지 않는다
  expect(calls.favorites).toBe(1)
  held.release()
  // 서버가 저장한 값(켜짐)으로 맞춰지고 버튼이 풀린다. 이 시트에서 누른 것이 아니라 저장 완료 안내는 없다.
  await expect(favoriteOn(page)).toHaveAttribute('aria-pressed', 'true')
  await expect(favoriteOn(page)).not.toHaveAttribute('aria-disabled', 'true')
  await expect(termSheet(page).getByText('즐겨찾기에 저장했어요')).toHaveCount(0)
  // 사용자가 해제하려고 누르면 켜기(true)를 다시 보내지 않고 해제(false)를 보낸다
  await favoriteOn(page).click()
  await expect(favoriteOff(page)).toHaveAttribute('aria-pressed', 'false')
  expect(calls.bodies).toEqual([{ favorited: true }, { favorited: false }])
})

test('저장 중 시트를 닫았다 다시 열어 둔 채 요청이 실패하면 버튼은 풀리고 오류 안내·로그인 안내는 뜨지 않으며 꺼짐 그대로다', async ({ page }) => {
  const held = gate()
  const calls = await setupFavorite(page, { member: true, gate: held.promise, favoriteResponse: () => ({ status: 500 }) })
  await page.goto('/notes/11')
  await termLink(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await favoriteOff(page).click()
  await expect.poll(() => calls.favorites).toBe(1)
  await page.keyboard.press('Escape')
  await termLink(page).click()
  await expect(termSheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await expect(favoriteOff(page)).toHaveAttribute('aria-disabled', 'true')
  held.release()
  await expect(favoriteOff(page)).not.toHaveAttribute('aria-disabled', 'true')
  await expect(favoriteOff(page)).toHaveAttribute('aria-pressed', 'false')
  await expect(favoriteAlert(page)).toHaveCount(0)
  await expect(loginPromptSheet(page)).toHaveCount(0)
})

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

// ---- MEG-106 AI 설명(E09): 요청 규칙, 오류 코드별 안내, 재시도 키. 브라우저의 실제 fetch 경로에 합성 HTTP 응답을 준다. ----
// 실제 백엔드의 E09(서버 저장·원장·세션 만료)는 확인하지 못한다.

const aiButton = (page: Page) => page.getByRole('button', { name: 'AI 설명', exact: true })
const aiLoginSheet = (page: Page) => page.getByRole('dialog', { name: '로그인이 필요해요' })
const retryButton = (page: Page) => page.getByRole('button', { name: '다시 시도' })

const aiNote = (body: string, revision = 5) => ({
  id: 31, revision, title: 'AI 설명 시험', studied_on: null, subjects: [], sources: [], body_markdown: body, images: {}, glossary_terms: [], glossary_spans: [],
})
const aiSuccess = { source: 'ai', term: { id: 12, key: 'unknownword', label: 'UnknownWord' }, explanation: { id: 31, body: '합성 AI 설명입니다.', review_status: 'pending', cached: false }, reportable: true, is_favorite: false }
const aiError = (code: string, detail?: string) => ({ error: { code, message: 'synthetic english message', request_id: 'r-test-0001', ...(detail ? { detail } : {}) } })

type AiCall = { key: string | undefined; body: { note_id: number; note_revision: number; selection: { start: number; end: number } } }
type AiReply = { status: number; json: unknown } | 'abort'

async function setupAi(page: Page, options: { member: boolean; body?: string; revision?: number; respond?: (call: AiCall, n: number) => AiReply | Promise<AiReply> }) {
  const calls: AiCall[] = []
  const notes = { count: 0 }
  await page.route('**/api/me', (route) => route.fulfill({ json: options.member ? { authenticated: true, role: 'member', display_name: '합성 사용자' } : { authenticated: false } }))
  await page.route('**/api/notes/31', (route) => {
    notes.count += 1
    return route.fulfill({ json: aiNote(options.body ?? 'hello UnknownWord 끝', options.revision ?? 5) })
  })
  await page.route('**/api/ai/explanations', async (route) => {
    const request = route.request()
    const call: AiCall = { key: request.headers()['idempotency-key'], body: request.postDataJSON() }
    calls.push(call)
    const reply = await (options.respond?.(call, calls.length) ?? { status: 200, json: aiSuccess })
    if (reply === 'abort') return route.abort()
    return route.fulfill(reply)
  })
  return { calls, notes }
}

async function selectAiText(page: Page, needle: string) {
  await page.locator('[data-note-body]').waitFor()
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

async function askAi(page: Page, needle = 'UnknownWord') {
  await selectAiText(page, needle)
  await aiButton(page).click()
}

test('E09 요청은 Idempotency-Key 헤더와 코드포인트 위치의 본문을 보낸다(이모지 뒤 선택)', async ({ page }) => {
  const { calls } = await setupAi(page, { member: true, body: '😀😀 앞 글자 UnknownWord 뒤', revision: 7 })
  await page.goto('/notes/31')
  await askAi(page)
  await expect(page.getByText('합성 AI 설명입니다.')).toBeVisible()
  expect(calls).toHaveLength(1)
  // 😀는 UTF-16으로 두 칸이지만 코드포인트로는 한 칸이다. 이모지 둘 + " 앞 글자 " 6칸 → 8부터 11글자
  expect(calls[0].body).toEqual({ note_id: 31, note_revision: 7, selection: { start: 8, end: 19 } })
  expect(calls[0].key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
})

test('방문자는 E09 요청 없이 로그인 안내가 열린다', async ({ page }) => {
  const { calls } = await setupAi(page, { member: false })
  await page.goto('/notes/31')
  await expect(page.getByText('hello')).toBeVisible()
  await askAi(page)
  await expect(aiLoginSheet(page)).toBeVisible()
  await page.waitForTimeout(300)
  expect(calls).toHaveLength(0)
})

test('위치를 계산하지 못하는 선택과 공백만 고른 선택에는 AI 설명 버튼이 없다', async ({ page }) => {
  const { calls } = await setupAi(page, { member: true, body: '정상 글자\n\n    들여쓴 코드\n\n앞   뒤' })
  await page.goto('/notes/31')
  await expect(page.getByText('들여쓴 코드')).toBeVisible()
  await selectAiText(page, '들여쓴 코드')
  await page.waitForTimeout(200)
  await expect(aiButton(page)).toHaveCount(0)
  await selectAiText(page, '   ')
  await page.waitForTimeout(200)
  await expect(aiButton(page)).toHaveCount(0)
  await selectAiText(page, '정상 글자')
  await expect(aiButton(page)).toBeVisible()
  expect(calls).toHaveLength(0)
})

// AC-3: 오류 코드마다 다른 안내가 보이고, 어느 것도 로그인 안내로 바뀌지 않는다.
const FAILURES = [
  ['429 ai_limit_reached', { status: 429, json: aiError('ai_limit_reached') }, '오늘 쓸 수 있는 AI 설명을 모두 썼어요. 나중에 다시 시도해 주세요.', false],
  ['502 ai_unavailable', { status: 502, json: aiError('ai_unavailable') }, 'AI가 설명을 만들지 못했어요. 다시 시도해 주세요.', true],
  ['409 in_progress', { status: 409, json: aiError('conflict', 'in_progress') }, '같은 설명을 만드는 중이에요. 잠시 뒤에 다시 확인해 주세요.', true],
  ['409 result_unavailable', { status: 409, json: aiError('conflict', 'result_unavailable') }, '이전 요청의 설명을 다시 가져올 수 없어요. 새로 요청해 주세요.', true],
  ['409 stale_revision', { status: 409, json: aiError('conflict', 'stale_revision') }, '노트가 바뀌었어요. 노트를 다시 불러온 뒤 단어를 다시 골라 주세요.', false],
  ['429 rate_limited', { status: 429, json: aiError('rate_limited') }, '요청이 많아요. 잠시 뒤에 다시 시도해 주세요.', true],
  ['404 not_found', { status: 404, json: aiError('not_found') }, '설명할 수 없는 노트예요', false],
  ['422 validation_failed', { status: 422, json: { error: { ...aiError('validation_failed').error, fields: [{ name: 'selection.end', reason: 'out_of_range', message: 'Value is out of range' }] } } }, '이 선택으로는 설명을 만들 수 없어요. 다른 단어를 골라 주세요.', false],
  ['500 internal_error', { status: 500, json: aiError('internal_error') }, 'AI 설명을 불러오지 못했어요', true],
] as const

for (const [name, reply, message, retryable] of FAILURES) {
  test(`E09 ${name}는 전용 안내를 보이고 로그인 안내로 바뀌지 않는다`, async ({ page }) => {
    await setupAi(page, { member: true, respond: () => reply })
    await page.goto('/notes/31')
    await askAi(page)
    const sheet = page.getByRole('dialog', { name: 'UnknownWord' })
    await expect(sheet.getByRole('alert')).toContainText(message)
    // message(영어 고정 문구) 글자는 화면에 나오지 않는다
    await expect(page.getByText('synthetic english message')).toHaveCount(0)
    await expect(aiLoginSheet(page)).toHaveCount(0)
    await expect(retryButton(page)).toHaveCount(retryable ? 1 : 0)
  })
}

test('오류 안내 문구는 서로 모두 다르다', () => {
  const texts = FAILURES.map(([, , message]) => message)
  expect(new Set(texts).size).toBe(texts.length)
})

test('502 뒤 다시 시도하면 새 키, 409 in_progress 뒤 다시 시도하면 같은 키를 쓴다', async ({ page }) => {
  const { calls } = await setupAi(page, {
    member: true,
    respond: (_call, n) => n === 1 ? { status: 502, json: aiError('ai_unavailable') }
      : n <= 3 ? { status: 409, json: aiError('conflict', 'in_progress') }
      : { status: 200, json: aiSuccess },
  })
  await page.goto('/notes/31')
  await askAi(page)
  await expect(page.getByText('AI가 설명을 만들지 못했어요. 다시 시도해 주세요.')).toBeVisible()
  await retryButton(page).click()
  await expect(page.getByText('같은 설명을 만드는 중이에요. 잠시 뒤에 다시 확인해 주세요.')).toBeVisible()
  expect(calls).toHaveLength(2)
  await retryButton(page).click()
  await expect.poll(() => calls.length).toBe(3)
  await expect(retryButton(page)).toBeVisible()
  await retryButton(page).click()
  await expect(page.getByText('합성 AI 설명입니다.')).toBeVisible()
  expect(calls).toHaveLength(4)
  expect(calls[1].key).not.toBe(calls[0].key) // 502(끝난 요청) 뒤: 새 키
  expect(calls[2].key).toBe(calls[1].key) // in_progress 뒤: 같은 키
  expect(calls[3].key).toBe(calls[1].key)
})

test('응답을 받지 못한 요청은 같은 키로, 409 result_unavailable 뒤에는 새 키로 다시 보낸다', async ({ page }) => {
  const { calls } = await setupAi(page, {
    member: true,
    respond: (_call, n) => n === 1 ? 'abort'
      : n === 2 ? { status: 409, json: aiError('conflict', 'result_unavailable') }
      : { status: 200, json: aiSuccess },
  })
  await page.goto('/notes/31')
  await askAi(page)
  await expect(page.getByText('AI 설명을 불러오지 못했어요')).toBeVisible()
  await retryButton(page).click() // 응답을 못 받았으니 서버가 처리했는지 모른다 → 같은 키
  await expect(page.getByText('이전 요청의 설명을 다시 가져올 수 없어요. 새로 요청해 주세요.')).toBeVisible()
  await retryButton(page).click() // result_unavailable 뒤 → 새 키
  await expect(page.getByText('합성 AI 설명입니다.')).toBeVisible()
  expect(calls).toHaveLength(3)
  expect(calls[1].key).toBe(calls[0].key)
  expect(calls[2].key).not.toBe(calls[1].key)
})

test('응답을 기다리는 중에는 다시 시도 버튼이 없고, 시트를 닫았다 같은 선택을 다시 열어도 요청은 한 번이다', async ({ page }) => {
  const held = gate()
  const { calls } = await setupAi(page, { member: true, respond: async () => { await held.promise; return { status: 200, json: aiSuccess } } })
  await page.goto('/notes/31')
  await askAi(page)
  const sheet = page.getByRole('dialog', { name: 'UnknownWord' })
  await expect(sheet.getByText('AI 설명을 만드는 중이에요')).toBeVisible()
  await expect(retryButton(page)).toHaveCount(0)
  await expect.poll(() => calls.length).toBe(1)
  await page.keyboard.press('Escape')
  await askAi(page)
  await expect(sheet.getByText('AI 설명을 만드는 중이에요')).toBeVisible()
  held.release()
  await expect(sheet.getByText('합성 AI 설명입니다.')).toBeVisible()
  expect(calls).toHaveLength(1)
})

test('로그인 사용자의 401 login_required만 로그인 안내를 연다', async ({ page }) => {
  await setupAi(page, { member: true, respond: () => ({ status: 401, json: aiError('login_required') }) })
  await page.goto('/notes/31')
  await askAi(page)
  await expect(aiLoginSheet(page)).toBeVisible()
  await expect(page.getByRole('dialog', { name: 'UnknownWord' })).toBeHidden()
})

test('401이어도 code가 login_required가 아니면 로그인 안내를 열지 않는다', async ({ page }) => {
  await setupAi(page, { member: true, respond: () => ({ status: 401, json: aiError('invalid_credentials') }) })
  await page.goto('/notes/31')
  await askAi(page)
  await expect(page.getByText('AI 설명을 불러오지 못했어요')).toBeVisible()
  await expect(aiLoginSheet(page)).toHaveCount(0)
})

test('시트를 닫은 뒤 늦게 도착한 401은 로그인 안내를 열지 않는다', async ({ page }) => {
  const held = gate()
  const { calls } = await setupAi(page, { member: true, respond: async () => { await held.promise; return { status: 401, json: aiError('login_required') } } })
  await page.goto('/notes/31')
  await askAi(page)
  await expect.poll(() => calls.length).toBe(1)
  await page.keyboard.press('Escape')
  held.release()
  await page.waitForTimeout(300)
  await expect(aiLoginSheet(page)).toHaveCount(0)
})

test('409 stale_revision이면 노트를 다시 불러오고 새 개정으로 단어를 다시 고를 수 있다', async ({ page }) => {
  const { calls, notes } = await setupAi(page, { member: true, respond: (call) => call.body.note_revision === 5 ? { status: 409, json: aiError('conflict', 'stale_revision') } : { status: 200, json: aiSuccess } })
  await page.goto('/notes/31')
  await askAi(page)
  await expect(page.getByText('노트가 바뀌었어요. 노트를 다시 불러온 뒤 단어를 다시 골라 주세요.')).toBeVisible()
  const before = notes.count
  // 노트가 개정 6으로 바뀌었다
  await page.route('**/api/notes/31', (route) => route.fulfill({ json: aiNote('hello UnknownWord 끝', 6) }))
  await page.getByRole('button', { name: '노트 다시 불러오기' }).click()
  await expect(page.getByRole('dialog', { name: 'UnknownWord' })).toBeHidden()
  await expect(page.getByText('hello')).toBeVisible()
  await expect(aiButton(page)).toHaveCount(0) // 이전 선택은 버린다
  await askAi(page)
  await expect(page.getByText('합성 AI 설명입니다.')).toBeVisible()
  expect(calls.map((call) => call.body.note_revision)).toEqual([5, 6])
  expect(before).toBeGreaterThanOrEqual(1)
})

// PR #67 AI 리뷰 P2 ② 서버가 retry_after_seconds로 정한 대기 시간 전에는 같은 선택의 요청을 다시 보내지 않는다.
const withRetryAfter = (code: string, seconds: number, detail?: string) => ({ error: { ...aiError(code, detail).error, retry_after_seconds: seconds } })

test('429 rate_limited의 retry_after_seconds 동안은 다시 시도해도 요청이 늘지 않고, 시트를 닫았다 열어도 같다', async ({ page }) => {
  await page.clock.install()
  const { calls } = await setupAi(page, {
    member: true,
    respond: (_call, n) => n === 1 ? { status: 429, json: withRetryAfter('rate_limited', 60) } : { status: 200, json: aiSuccess },
  })
  await page.goto('/notes/31')
  await askAi(page)
  const sheet = page.getByRole('dialog', { name: 'UnknownWord' })
  await expect(sheet.getByText('60초 뒤에 다시 시도할 수 있어요')).toBeVisible()
  await expect(retryButton(page)).toHaveAttribute('aria-disabled', 'true')
  await retryButton(page).click({ force: true }) // aria-disabled라 Playwright는 기본으로 누르지 않는다. 눌러도 요청이 나가지 않는지 본다
  await page.waitForTimeout(200)
  expect(calls).toHaveLength(1) // 대기 시간 전에는 요청이 나가지 않는다
  // 닫았다 같은 선택을 다시 열어도 대기가 이어진다(서버에 다시 묻지 않는다)
  await page.keyboard.press('Escape')
  await askAi(page)
  await expect(sheet.getByText('요청이 많아요. 잠시 뒤에 다시 시도해 주세요.')).toBeVisible()
  await expect(retryButton(page)).toHaveAttribute('aria-disabled', 'true')
  await page.waitForTimeout(200)
  expect(calls).toHaveLength(1)
  // 대기 시간이 지나면 다시 시도할 수 있다
  await page.clock.fastForward(61_000)
  await expect(retryButton(page)).not.toHaveAttribute('aria-disabled', 'true')
  await retryButton(page).click()
  await expect(sheet.getByText('합성 AI 설명입니다.')).toBeVisible()
  expect(calls).toHaveLength(2)
})

test('409 in_progress의 retry_after_seconds도 기다린 뒤 같은 키로 다시 보낸다', async ({ page }) => {
  await page.clock.install()
  const { calls } = await setupAi(page, {
    member: true,
    respond: (_call, n) => n === 1 ? { status: 409, json: withRetryAfter('conflict', 30, 'in_progress') } : { status: 200, json: aiSuccess },
  })
  await page.goto('/notes/31')
  await askAi(page)
  const sheet = page.getByRole('dialog', { name: 'UnknownWord' })
  await expect(sheet.getByText('30초 뒤에 다시 시도할 수 있어요')).toBeVisible()
  await retryButton(page).click({ force: true }) // aria-disabled라 Playwright는 기본으로 누르지 않는다. 눌러도 요청이 나가지 않는지 본다
  await page.waitForTimeout(200)
  expect(calls).toHaveLength(1)
  await page.clock.fastForward(31_000)
  await expect(retryButton(page)).not.toHaveAttribute('aria-disabled', 'true')
  await retryButton(page).click()
  await expect(sheet.getByText('합성 AI 설명입니다.')).toBeVisible()
  expect(calls).toHaveLength(2)
  expect(calls[1].key).toBe(calls[0].key)
})

// PR #67 AI 리뷰 P2 ① review_status가 없는 1회용 설명에도 "AI 생성·검수 전"을 보인다. 검수가 끝난 값이 오면 "AI 생성"이다.
test('review_status가 없는 1회용 설명은 "AI 생성·검수 전", 검수 끝난 설명은 "AI 생성"을 보인다', async ({ page }) => {
  let reviewed = false
  await setupAi(page, {
    member: true,
    respond: () => reviewed
      ? { status: 200, json: { ...aiSuccess, explanation: { ...aiSuccess.explanation, review_status: 'approved' } } }
      : { status: 200, json: { source: 'ai', term: null, explanation: { id: null, body: '합성 1회용 AI 설명입니다.' }, reportable: false } },
  })
  await page.goto('/notes/31')
  await askAi(page)
  const sheet = page.getByRole('dialog', { name: 'UnknownWord' })
  await expect(sheet.getByText('합성 1회용 AI 설명입니다.')).toBeVisible()
  await expect(sheet.getByText('AI 생성·검수 전')).toBeVisible()
  await page.keyboard.press('Escape')
  reviewed = true
  await askAi(page)
  await expect(sheet.getByText('합성 AI 설명입니다.')).toBeVisible()
  await expect(sheet.getByText('AI 생성', { exact: true })).toBeVisible()
  await expect(sheet.getByText('AI 생성·검수 전')).toHaveCount(0)
})

// PR #67 AI 리뷰(재검증) P2 서버가 준 대기 시간은 줄이지 않는다. 600초를 넘는 값도 기한 전에는 요청이 늘지 않는다.
test('429 retry_after_seconds가 600초를 넘어도 서버 기한 전에는 다시 보내지 않고 기한 뒤에 보낸다', async ({ page }) => {
  await page.clock.install()
  const { calls } = await setupAi(page, {
    member: true,
    respond: (_call, n) => n === 1 ? { status: 429, json: withRetryAfter('rate_limited', 900) } : { status: 200, json: aiSuccess },
  })
  await page.goto('/notes/31')
  await askAi(page)
  const sheet = page.getByRole('dialog', { name: 'UnknownWord' })
  await expect(sheet.getByText('900초 뒤에 다시 시도할 수 있어요')).toBeVisible()
  await page.clock.fastForward(601_000)
  await expect(retryButton(page)).toHaveAttribute('aria-disabled', 'true') // 600초가 지나도 서버 기한(900초)까지는 막혀 있다
  await retryButton(page).click({ force: true })
  await page.waitForTimeout(200)
  expect(calls).toHaveLength(1)
  await page.clock.fastForward(300_000)
  await expect(retryButton(page)).not.toHaveAttribute('aria-disabled', 'true')
  await retryButton(page).click()
  await expect(sheet.getByText('합성 AI 설명입니다.')).toBeVisible()
  expect(calls).toHaveLength(2)
})

// ---- MEG-108 오늘의 퀴즈(E11): 여섯 상태, generating 재조회, 오류별 안내. 브라우저의 실제 fetch 경로에 합성 HTTP 응답을 준다. ----
// 실제 백엔드의 E11(퀴즈 생성·저장, 서버의 08:30 경계, 세션 만료)은 확인하지 못한다.

type QuizReply = { status: number; json: unknown } | { status: number; body: string; contentType: string } | 'abort'

async function setupQuiz(page: Page, options: { member?: boolean; respond: (n: number) => QuizReply | Promise<QuizReply> }) {
  const calls = { count: 0 }
  await page.route('**/api/me', (route) => route.fulfill({ json: options.member === false ? { authenticated: false } : { authenticated: true, role: 'member', display_name: '합성 사용자' } }))
  await page.route('**/api/notes', (route) => route.fulfill({ json: { subjects: [], notes: [] } }))
  await page.route('**/api/quiz/today', async (route) => {
    calls.count += 1
    const reply = await options.respond(calls.count)
    if (reply === 'abort') return route.abort()
    return route.fulfill(reply)
  })
  return calls
}

const quizItems = [
  { id: 41, difficulty: '중', question: '합성 질문 1입니다.', answered: false, followups: [], can_request_followup: false },
  { id: 42, difficulty: '하', question: '합성 질문 2입니다.', answered: true, your_answer: '합성 답변', correct_answer: '합성 정답', explanation: '합성 해설', followups: [], can_request_followup: false },
]
const ok = (body: unknown): QuizReply => ({ status: 200, json: body })
const quizRetry = (page: Page) => page.getByRole('button', { name: '다시 시도' })
const quizRecheck = (page: Page) => page.getByRole('button', { name: '다시 확인' })

// AC-1~3: 여섯 상태는 모두 HTTP 200이고 각각 다른 화면으로 보인다.
const QUIZ_STATES = [
  ['ready', { status: 'ready', quiz_date: '2026-10-23', items: quizItems }, '합성 질문 1입니다.', false],
  ['not_open', { status: 'not_open' }, '오늘의 퀴즈는 아침 8시 30분부터 볼 수 있어요', true],
  ['none', { status: 'none' }, '오늘 풀 퀴즈가 없어요', true],
  ['generating', { status: 'generating', retry_after_seconds: 30 }, '퀴즈를 만드는 중이에요', false],
  ['failed', { status: 'failed' }, '오늘의 퀴즈를 만들지 못했어요', false],
  ['ai_limit_reached', { status: 'ai_limit_reached' }, '지금은 AI 사용 한도가 차서 퀴즈를 만들 수 없어요', true],
] as const

for (const [name, body, text, canRecheck] of QUIZ_STATES) {
  test(`E11 ${name}는 HTTP 200의 전용 화면으로 보이고 오류나 로그인 안내가 아니다`, async ({ page }) => {
    const calls = await setupQuiz(page, { respond: () => ok(body) })
    await page.goto('/quiz')
    await expect(page.getByRole('heading', { name: text })).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0) // 오류 안내가 아니다
    await expect(page.getByRole('dialog')).toHaveCount(0) // 로그인 안내가 아니다
    await expect(quizRecheck(page)).toHaveCount(canRecheck ? 1 : 0)
    await expect(quizRetry(page)).toHaveCount(0)
    expect(calls.count).toBe(1)
  })
}

test('여섯 상태의 안내 문구는 서로 모두 다르다', () => {
  const titles = QUIZ_STATES.map(([, , text]) => text)
  expect(new Set(titles).size).toBe(titles.length)
})

test('ready 응답의 정답·해설·내 답은 화면에 나오지 않는다', async ({ page }) => {
  await setupQuiz(page, { respond: () => ok({ status: 'ready', quiz_date: '2026-10-23', items: quizItems }) })
  await page.goto('/quiz')
  await expect(page.getByRole('heading', { name: '합성 질문 2입니다.' })).toBeVisible()
  await expect(page.getByText('답함', { exact: true })).toHaveCount(1)
  for (const hidden of ['합성 정답', '합성 해설', '합성 답변']) await expect(page.getByText(hidden)).toHaveCount(0)
})

test('not_open·none에서 다시 확인을 누르면 다시 조회하고 08:30이 되어도 저절로 갱신하지 않는다', async ({ page }) => {
  await page.clock.install()
  const calls = await setupQuiz(page, { respond: (n) => n === 1 ? ok({ status: 'not_open' }) : ok({ status: 'ready', quiz_date: '2026-10-23', items: quizItems }) })
  await page.goto('/quiz')
  await expect(page.getByRole('heading', { name: '오늘의 퀴즈는 아침 8시 30분부터 볼 수 있어요' })).toBeVisible()
  await page.clock.fastForward(60 * 60 * 1000) // 한 시간이 지나도 저절로 다시 부르지 않는다
  await page.waitForTimeout(200)
  expect(calls.count).toBe(1)
  await quizRecheck(page).click()
  await expect(page.getByRole('heading', { name: '합성 질문 1입니다.' })).toBeVisible()
  expect(calls.count).toBe(2)
})

test('generating은 서버가 준 retry_after_seconds 뒤에 다시 부르고, 다른 상태가 되면 더 부르지 않는다', async ({ page }) => {
  await page.clock.install()
  const calls = await setupQuiz(page, {
    respond: (n) => n <= 2 ? ok({ status: 'generating', retry_after_seconds: 7 }) : ok({ status: 'ready', quiz_date: '2026-10-23', items: quizItems }),
  })
  await page.goto('/quiz')
  await expect(page.getByRole('heading', { name: '퀴즈를 만드는 중이에요' })).toBeVisible()
  expect(calls.count).toBe(1)
  await page.clock.fastForward(6_000)
  await page.waitForTimeout(200)
  expect(calls.count).toBe(1) // 아직 7초가 안 됐다
  await page.clock.fastForward(1_500)
  await expect.poll(() => calls.count).toBe(2)
  await expect(page.getByRole('heading', { name: '퀴즈를 만드는 중이에요' })).toBeVisible() // 다시 generating이어도 화면이 깜박이지 않는다
  await page.clock.fastForward(7_500)
  await expect(page.getByRole('heading', { name: '합성 질문 1입니다.' })).toBeVisible()
  expect(calls.count).toBe(3)
  await page.clock.fastForward(5 * 60 * 1000) // ready가 된 뒤에는 반복하지 않는다
  await page.waitForTimeout(200)
  expect(calls.count).toBe(3)
})

test('generating 응답에 retry_after_seconds가 없으면 임시로 5초 뒤에 다시 부르고, 너무 짧은 값은 1초로 맞춘다', async ({ page }) => {
  await page.clock.install()
  const calls = await setupQuiz(page, {
    respond: (n) => n === 1 ? ok({ status: 'generating' }) : n === 2 ? ok({ status: 'generating', retry_after_seconds: 0.2 }) : ok({ status: 'none' }),
  })
  await page.goto('/quiz')
  await expect(page.getByRole('heading', { name: '퀴즈를 만드는 중이에요' })).toBeVisible()
  await page.clock.fastForward(4_500)
  await page.waitForTimeout(200)
  expect(calls.count).toBe(1)
  await page.clock.fastForward(1_000)
  await expect.poll(() => calls.count).toBe(2)
  await page.clock.fastForward(500)
  await page.waitForTimeout(200)
  expect(calls.count).toBe(2) // 0.2초는 1초로 맞춰진다
  await page.clock.fastForward(1_000)
  await expect.poll(() => calls.count).toBe(3)
  await expect(page.getByRole('heading', { name: '오늘 풀 퀴즈가 없어요' })).toBeVisible()
})

test('generating 중 화면을 떠나면 반복 요청이 멈추고 응답을 기다리는 동안에는 요청이 겹치지 않는다', async ({ page }) => {
  await page.clock.install()
  const held = gate()
  const calls = await setupQuiz(page, {
    respond: async (n) => {
      if (n === 1) return ok({ status: 'generating', retry_after_seconds: 3 })
      await held.promise // 두 번째 응답은 붙잡아 둔다
      return ok({ status: 'generating', retry_after_seconds: 3 })
    },
  })
  await page.goto('/quiz')
  await expect(page.getByRole('heading', { name: '퀴즈를 만드는 중이에요' })).toBeVisible()
  await page.clock.fastForward(3_500)
  await expect.poll(() => calls.count).toBe(2)
  await page.clock.fastForward(30_000) // 두 번째 응답이 아직이라 세 번째를 겹쳐 보내지 않는다
  await page.waitForTimeout(200)
  expect(calls.count).toBe(2)
  await goInAppQuiz(page, '/') // 화면을 떠난다
  held.release()
  await page.clock.fastForward(60_000)
  await page.waitForTimeout(300)
  expect(calls.count).toBe(2) // 떠난 뒤에는 더 부르지 않는다
})

test('다시 확인을 누르면 요청이 하나만 나가고 응답 전에는 버튼이 없다', async ({ page }) => {
  const held = gate()
  const calls = await setupQuiz(page, {
    respond: async (n) => {
      if (n === 1) return ok({ status: 'none' })
      await held.promise
      return ok({ status: 'ready', quiz_date: '2026-10-23', items: quizItems })
    },
  })
  await page.goto('/quiz')
  await quizRecheck(page).click()
  await expect(page.getByRole('heading', { name: '오늘의 퀴즈를 불러오는 중이에요' })).toBeVisible()
  await expect(quizRecheck(page)).toHaveCount(0)
  expect(calls.count).toBe(2)
  held.release()
  await expect(page.getByRole('heading', { name: '합성 질문 1입니다.' })).toBeVisible()
  expect(calls.count).toBe(2)
})

// AC-4 오류
test('방문자는 E11 요청 없이 로그인 안내가 열린다', async ({ page }) => {
  const calls = await setupQuiz(page, { member: false, respond: () => ok({ status: 'none' }) })
  await page.goto('/quiz')
  await expect(page.getByRole('dialog', { name: '로그인이 필요해요' }).getByText('오늘의 퀴즈는 로그인한 뒤에 볼 수 있어요. 계정은 운영자가 만들어 줘요.')).toBeVisible()
  await page.waitForTimeout(300)
  expect(calls.count).toBe(0)
})

test('E11 로그인 사용자의 401 login_required는 공통 로그인 안내를 연다', async ({ page }) => {
  await setupQuiz(page, { respond: () => ({ status: 401, json: aiError('login_required') }) })
  await page.goto('/quiz')
  await expect(page.getByRole('dialog', { name: '로그인이 필요해요' })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('E11 401이어도 code가 login_required가 아니면 로그인 안내를 열지 않는다', async ({ page }) => {
  await setupQuiz(page, { respond: () => ({ status: 401, json: aiError('invalid_credentials') }) })
  await page.goto('/quiz')
  await expect(page.getByRole('alert')).toContainText('퀴즈를 불러오지 못했어요')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

const QUIZ_ERRORS = [
  ['429 rate_limited', { status: 429, json: aiError('rate_limited') }, '요청이 많아요. 잠시 뒤에 다시 시도해 주세요.'],
  ['502 ai_unavailable', { status: 502, json: aiError('ai_unavailable') }, '퀴즈를 만드는 중 AI에 문제가 생겼어요. 다시 시도해 주세요.'],
  ['500 internal_error', { status: 500, json: aiError('internal_error') }, '퀴즈를 불러오지 못했어요'],
  ['네트워크 오류', 'abort', '퀴즈를 불러오지 못했어요'],
] as const

for (const [name, reply, message] of QUIZ_ERRORS) {
  test(`E11 ${name}는 전용 안내와 다시 시도를 보이고 저절로 다시 부르지 않으며 로그인 안내가 아니다`, async ({ page }) => {
    await page.clock.install()
    const calls = await setupQuiz(page, { respond: (n) => n === 1 ? reply : ok({ status: 'none' }) })
    await page.goto('/quiz')
    await expect(page.getByRole('alert')).toContainText(message)
    await expect(page.getByText('synthetic english message')).toHaveCount(0) // 영어 message 글자는 보이지 않는다
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await page.clock.fastForward(10 * 60 * 1000)
    await page.waitForTimeout(200)
    expect(calls.count).toBe(1) // 저절로 다시 부르지 않는다
    await quizRetry(page).click() // 사용자가 누르면 다시 보낸다
    await expect(page.getByRole('heading', { name: '오늘 풀 퀴즈가 없어요' })).toBeVisible()
    expect(calls.count).toBe(2)
  })
}

test('429의 retry_after_seconds 동안은 다시 시도해도 요청이 늘지 않고, 화면을 나갔다 돌아와도 같으며, 기한 뒤에 보낸다', async ({ page }) => {
  await page.clock.install()
  const calls = await setupQuiz(page, {
    respond: (n) => n === 1 ? { status: 429, json: { error: { ...aiError('rate_limited').error, retry_after_seconds: 60 } } } : ok({ status: 'none' }),
  })
  await page.goto('/quiz')
  await expect(page.getByText('60초 뒤에 다시 시도할 수 있어요')).toBeVisible()
  await expect(quizRetry(page)).toHaveAttribute('aria-disabled', 'true')
  await quizRetry(page).click({ force: true }) // aria-disabled라 Playwright는 기본으로 누르지 않는다. 눌러도 요청이 나가지 않는지 본다
  await page.waitForTimeout(200)
  expect(calls.count).toBe(1)
  await goInAppQuiz(page, '/')
  await goInAppQuiz(page, '/quiz') // 나갔다 돌아와도 서버 기한 전에는 요청하지 않는다
  await expect(page.getByRole('alert')).toContainText('요청이 많아요')
  await page.waitForTimeout(200)
  expect(calls.count).toBe(1)
  await page.clock.fastForward(61_000)
  await expect(quizRetry(page)).not.toHaveAttribute('aria-disabled', 'true')
  await quizRetry(page).click()
  await expect(page.getByRole('heading', { name: '오늘 풀 퀴즈가 없어요' })).toBeVisible()
  expect(calls.count).toBe(2)
})

// 앱 안에서 경로를 옮긴다(새로 고치지 않아 모듈의 요청 상태가 이어진다)
async function goInAppQuiz(page: Page, path: string) {
  await page.evaluate((to) => {
    history.pushState({}, '', to)
    dispatchEvent(new PopStateEvent('popstate'))
  }, path)
}

// 자체 점검에서 찾은 빈틈: 서버가 약속하지 않은 status나 모양이 이상한 응답을 줘도 화면이 깨지지 않고 오류 안내와 다시 시도가 보인다.
for (const [name, body] of [
  ['모르는 status', { status: 'something_new' }],
  ['status가 없는 응답', {}],
  ['ready인데 items가 배열이 아님', { status: 'ready', quiz_date: '2026-10-23', items: null }],
] as const) {
  test(`E11 ${name}는 화면을 깨지 않고 불러오지 못했다는 안내와 다시 시도를 보인다`, async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    const calls = await setupQuiz(page, { respond: (n) => n === 1 ? ok(body) : ok({ status: 'none' }) })
    await page.goto('/quiz')
    await expect(page.getByRole('alert')).toContainText('퀴즈를 불러오지 못했어요')
    await expect(page.getByRole('heading', { level: 1, name: '오늘의 퀴즈' })).toBeVisible()
    await quizRetry(page).click()
    await expect(page.getByRole('heading', { name: '오늘 풀 퀴즈가 없어요' })).toBeVisible()
    expect(calls.count).toBe(2)
    expect(errors).toEqual([])
  })
}

test('ready의 문항이 비어 있으면 퀴즈 없음 안내를 보인다', async ({ page }) => {
  await setupQuiz(page, { respond: () => ok({ status: 'ready', quiz_date: '2026-10-23', items: [] }) })
  await page.goto('/quiz')
  await expect(page.getByRole('heading', { name: '오늘 풀 퀴즈가 없어요' })).toBeVisible()
})

// 독립 리뷰에서 나온 빈틈: 본문이 null인 응답, 문항 배열 속 이상한 값, 포커스, 세션 만료 뒤 로그인 길, 계정 전환.
test('E11 본문이 JSON null이어도 로딩에 멈추지 않고 불러오지 못했다는 안내와 다시 시도를 보인다', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const calls = await setupQuiz(page, { respond: (n) => n === 1 ? { status: 200, body: 'null', contentType: 'application/json' } : ok({ status: 'none' }) })
  await page.goto('/quiz')
  await expect(page.getByRole('alert')).toContainText('퀴즈를 불러오지 못했어요')
  await quizRetry(page).click()
  await expect(page.getByRole('heading', { name: '오늘 풀 퀴즈가 없어요' })).toBeVisible()
  expect(calls.count).toBe(2)
  expect(errors).toEqual([])
})

test('ready의 문항 배열에 null·낯선 값이 섞여도 읽을 수 있는 문항만 보이고, 하나도 읽을 수 없으면 오류 안내다', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await setupQuiz(page, {
    respond: (n) => n === 1
      ? ok({ status: 'ready', quiz_date: '2026-10-23', items: [null, 7, { id: 'x' }, { ...quizItems[0], difficulty: 'constructor' }] })
      : ok({ status: 'ready', quiz_date: '2026-10-23', items: [null, {}] }),
  })
  await page.goto('/quiz')
  await expect(page.getByRole('heading', { name: '합성 질문 1입니다.' })).toBeVisible()
  await expect(page.getByRole('main').getByRole('listitem')).toHaveCount(1)
  await expect(page.getByText('난이도')).toHaveCount(0) // 모르는 난이도 값은 칩 없이 둔다
  expect(errors).toEqual([])
  await page.reload() // 두 번째 응답(읽을 수 있는 문항 없음)을 받는다
  await expect(page.getByRole('alert')).toContainText('퀴즈를 불러오지 못했어요')
  expect(errors).toEqual([])
})

test('다시 확인을 누르면 포커스가 사라지지 않고 결과 영역에 남는다', async ({ page }) => {
  const held = gate()
  await setupQuiz(page, { respond: async (n) => { if (n === 1) return ok({ status: 'none' }); await held.promise; return ok({ status: 'not_open' }) } })
  await page.goto('/quiz')
  await quizRecheck(page).click()
  await expect(page.getByRole('heading', { name: '오늘의 퀴즈를 불러오는 중이에요' })).toBeVisible()
  await expect(page.locator('main > div[tabindex="-1"]')).toBeFocused()
  held.release()
  await expect(page.getByRole('heading', { name: '오늘의 퀴즈는 아침 8시 30분부터 볼 수 있어요' })).toBeVisible()
  await expect(page.locator('main > div[tabindex="-1"]')).toBeFocused()
})

test('로그인 사용자의 401 login_required 뒤 안내를 닫아도 화면에 로그인으로 가는 길이 있다', async ({ page }) => {
  await setupQuiz(page, { respond: () => ({ status: 401, json: aiError('login_required') }) })
  await page.goto('/quiz')
  await expect(page.getByRole('dialog', { name: '로그인이 필요해요' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('main').getByRole('link', { name: '로그인' })).toHaveAttribute('href', '/login')
})

test('429 대기는 같은 계정에만 적용되고 다른 계정으로 바뀌면 이어받지 않는다', async ({ page }) => {
  const calls = await setupQuiz(page, {
    respond: (n) => n === 1 ? { status: 429, json: { error: { ...aiError('rate_limited').error, retry_after_seconds: 60 } } } : ok({ status: 'none' }),
  })
  await page.goto('/')
  const outcomes = await page.evaluate(async () => {
    const { requestQuizToday } = await import('/src/quiz/quizToday.ts')
    const result = async (account: string) => requestQuizToday(account).then(() => 'ok', () => 'error')
    return [await result('member:가'), await result('member:가'), await result('member:나')]
  })
  expect(outcomes).toEqual(['error', 'error', 'ok']) // 같은 계정은 서버 기한까지 막히고(요청 안 나감), 다른 계정은 바로 요청한다
  expect(calls.count).toBe(2)
})

test('generating 대기 중(타이머 예약 상태)에 화면을 떠나면 이후 요청이 나가지 않는다', async ({ page }) => {
  await page.clock.install()
  const calls = await setupQuiz(page, { respond: () => ok({ status: 'generating', retry_after_seconds: 10 }) })
  await page.goto('/quiz')
  await expect(page.getByRole('heading', { name: '퀴즈를 만드는 중이에요' })).toBeVisible()
  await page.clock.fastForward(3_000)
  await goInAppQuiz(page, '/')
  await expect(page.getByRole('heading', { level: 1, name: '과목' })).toBeVisible()
  await page.clock.fastForward(60_000)
  await page.waitForTimeout(300)
  expect(calls.count).toBe(1)
})

// PR #79 AI 리뷰 P1: 표시 이름·역할이 같은 다른 계정이 이전 계정의 진행 중 E11 요청과 429 대기를 이어받으면 안 된다.
// 계정 구분은 표시 이름이 아니라 로그인·로그아웃 때마다 올라가는 세션 번호로 한다. 브라우저에서 실제 로그아웃·로그인 흐름으로 시험한다.
async function setupAccountSwitch(page: Page, respond: (n: number) => QuizReply | Promise<QuizReply>) {
  const state = { loggedIn: true, calls: 0 }
  await page.route('**/api/me', (route) => route.fulfill({ json: state.loggedIn ? { authenticated: true, role: 'member', display_name: '같은이름' } : { authenticated: false } }))
  await page.route('**/api/notes', (route) => route.fulfill({ json: { subjects: [], notes: [] } }))
  await page.route('**/api/auth/logout', (route) => {
    state.loggedIn = false
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/auth/login', (route) => {
    state.loggedIn = true
    return route.fulfill({ json: { user: { role: 'member', display_name: '같은이름' } } })
  })
  await page.route('**/api/quiz/today', async (route) => {
    state.calls += 1
    const reply = await respond(state.calls)
    if (reply === 'abort') return route.abort()
    return route.fulfill(reply)
  })
  return state
}

// 로그아웃한 뒤 같은 표시 이름의 다른 계정(B)으로 로그인해 퀴즈 화면으로 온다.
async function switchToSameNameAccount(page: Page) {
  await page.getByRole('button', { name: /^내 계정/ }).click()
  await page.getByRole('menuitem', { name: '로그아웃' }).click()
  await expect(page).toHaveURL(/\/$/)
  await goInAppQuiz(page, '/login')
  await page.getByLabel('이메일').fill('b@example.test')
  await page.getByLabel('비밀번호').fill('example-password')
  await page.getByRole('button', { name: '로그인' }).click()
  await expect(page).toHaveURL(/\/quiz$/)
}

const quizReady = (title: string): QuizReply => ok({ status: 'ready', quiz_date: '2026-10-23', items: [{ ...quizItems[0], question: title }] })

test('A의 E11 요청이 진행 중일 때 로그아웃하고 같은 표시 이름의 B로 로그인해도 B는 A의 요청·문항을 받지 않는다', async ({ page }) => {
  const held = gate()
  const state = await setupAccountSwitch(page, async (n) => {
    if (n === 1) {
      await held.promise
      return quizReady('A의 문항')
    }
    return quizReady('B의 문항')
  })
  await page.goto('/quiz')
  await expect.poll(() => state.calls).toBe(1)
  await switchToSameNameAccount(page)
  await expect(page.getByRole('heading', { name: 'B의 문항' })).toBeVisible()
  expect(state.calls).toBe(2) // B는 A의 진행 중 요청을 이어받지 않고 자기 요청을 보낸다
  held.release() // 늦게 도착한 A의 응답
  await page.waitForTimeout(300)
  await expect(page.getByText('A의 문항')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'B의 문항' })).toBeVisible()
})

test('A가 429 대기 중일 때 같은 표시 이름의 B로 로그인하면 B는 그 대기를 이어받지 않는다', async ({ page }) => {
  const state = await setupAccountSwitch(page, (n) => n === 1
    ? { status: 429, json: { error: { ...aiError('rate_limited').error, retry_after_seconds: 600 } } }
    : ok({ status: 'none' }))
  await page.goto('/quiz')
  await expect(page.getByText('600초 뒤에 다시 시도할 수 있어요')).toBeVisible()
  await switchToSameNameAccount(page)
  await expect(page.getByRole('heading', { name: '오늘 풀 퀴즈가 없어요' })).toBeVisible()
  expect(state.calls).toBe(2)
  await expect(page.getByText('초 뒤에 다시 시도할 수 있어요')).toHaveCount(0)
})

// ---- MEG-137 AI 설명(E09) 요청·재시도 키·대기를 로그인 세션별로 분리. 실제 로그아웃·로그인 흐름과 합성 HTTP 응답으로 시험한다. ----
// 같은 노트·개정·선택을 다른 계정(표시 이름이 같아도 된다)이 요청해도 이전 세션의 진행 중 요청·응답·오류·대기·재시도 키를 이어받으면 안 된다.
// 실제 백엔드의 E09·세션 만료·권한/열람 기록은 확인하지 못한다.

async function setupAiSwitch(page: Page, respond: (call: AiCall, n: number) => AiReply | Promise<AiReply>) {
  const state = { loggedIn: true, calls: [] as AiCall[] }
  await page.route('**/api/me', (route) => route.fulfill({ json: state.loggedIn ? { authenticated: true, role: 'member', display_name: '같은이름' } : { authenticated: false } }))
  await page.route('**/api/notes', (route) => route.fulfill({ json: { subjects: [], notes: [] } }))
  await page.route('**/api/notes/31', (route) => route.fulfill({ json: aiNote('hello UnknownWord 끝', 5) }))
  await page.route('**/api/auth/logout', (route) => {
    state.loggedIn = false
    return route.fulfill({ status: 204 })
  })
  await page.route('**/api/auth/login', (route) => {
    state.loggedIn = true
    return route.fulfill({ json: { user: { role: 'member', display_name: '같은이름' } } })
  })
  await page.route('**/api/ai/explanations', async (route) => {
    const request = route.request()
    const call: AiCall = { key: request.headers()['idempotency-key'], body: request.postDataJSON() }
    state.calls.push(call)
    const reply = await respond(call, state.calls.length)
    if (reply === 'abort') return route.abort()
    return route.fulfill(reply)
  })
  return state
}

// 열려 있는 시트를 닫고 로그아웃한 뒤 같은 표시 이름의 다른 계정(B)으로 로그인해, 같은 노트로 돌아온다.
async function switchToAccountB(page: Page) {
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: /^내 계정/ }).click()
  await page.getByRole('menuitem', { name: '로그아웃' }).click()
  await expect(page).toHaveURL(/\/$/)
  await goInAppQuiz(page, '/login')
  await page.getByLabel('이메일').fill('b@example.test')
  await page.getByLabel('비밀번호').fill('example-password')
  await page.getByRole('button', { name: '로그인' }).click()
  await expect(page).toHaveURL(/\/quiz$/)
  await goInAppQuiz(page, '/notes/31')
  await page.locator('[data-note-body]').waitFor()
}

const aiText = (text: string) => ({ status: 200, json: { ...aiSuccess, explanation: { ...aiSuccess.explanation, body: text } } })

test('AC-1 A의 E09가 진행 중일 때 닫고 로그아웃 → B 로그인 → 같은 선택을 요청하면 B가 별도 요청을 보내 B 응답만 보이고, 늦은 A 성공은 영향이 없다', async ({ page }) => {
  const held = gate()
  const state = await setupAiSwitch(page, async (_call, n) => {
    if (n === 1) {
      await held.promise
      return aiText('A의 설명')
    }
    return aiText('B의 설명')
  })
  await page.goto('/notes/31')
  await askAi(page)
  await expect.poll(() => state.calls.length).toBe(1)
  await switchToAccountB(page)
  await askAi(page)
  const sheet = page.getByRole('dialog', { name: 'UnknownWord' })
  await expect(sheet.getByText('B의 설명')).toBeVisible()
  expect(state.calls).toHaveLength(2) // B는 A의 진행 중 요청을 이어받지 않고 자기 요청을 보낸다
  held.release() // 늦게 도착한 A의 성공
  await page.waitForTimeout(300)
  await expect(page.getByText('A의 설명')).toHaveCount(0)
  await expect(sheet.getByText('B의 설명')).toBeVisible()
})

test('AC-1 늦게 도착한 A의 오류도 B 화면과 상태에 영향을 주지 않는다', async ({ page }) => {
  const held = gate()
  const state = await setupAiSwitch(page, async (_call, n) => {
    if (n === 1) {
      await held.promise
      return { status: 500, json: aiError('internal_error') }
    }
    return aiText('B의 설명')
  })
  await page.goto('/notes/31')
  await askAi(page)
  await expect.poll(() => state.calls.length).toBe(1)
  await switchToAccountB(page)
  await askAi(page)
  const sheet = page.getByRole('dialog', { name: 'UnknownWord' })
  await expect(sheet.getByText('B의 설명')).toBeVisible()
  held.release()
  await page.waitForTimeout(300)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(sheet.getByText('B의 설명')).toBeVisible()
})

for (const [name, reply, wait] of [
  ['429 rate_limited', { status: 429, json: { error: { ...aiError('rate_limited').error, retry_after_seconds: 600 } } }, '600초 뒤에 다시 시도할 수 있어요'],
  ['409 in_progress', { status: 409, json: { error: { ...aiError('conflict', 'in_progress').error, retry_after_seconds: 600 } } }, '600초 뒤에 다시 시도할 수 있어요'],
] as const) {
  test(`AC-2 A의 ${name} 대기가 B에게 이어지지 않는다`, async ({ page }) => {
    const state = await setupAiSwitch(page, (_call, n) => n === 1 ? reply : aiText('B의 설명'))
    await page.goto('/notes/31')
    await askAi(page)
    await expect(page.getByRole('dialog', { name: 'UnknownWord' }).getByText(wait)).toBeVisible()
    await switchToAccountB(page)
    await askAi(page)
    const sheet = page.getByRole('dialog', { name: 'UnknownWord' })
    await expect(sheet.getByText('B의 설명')).toBeVisible()
    expect(state.calls).toHaveLength(2)
    await expect(sheet.getByText('초 뒤에 다시 시도할 수 있어요')).toHaveCount(0)
  })
}

test('AC-2 B의 대기가 있는 중 늦게 온 A의 응답이 B의 대기를 바꾸지 않는다', async ({ page }) => {
  await page.clock.install()
  const held = gate()
  const state = await setupAiSwitch(page, async (_call, n) => {
    if (n === 1) {
      await held.promise
      return { status: 429, json: { error: { ...aiError('rate_limited').error, retry_after_seconds: 5 } } }
    }
    return { status: 429, json: { error: { ...aiError('rate_limited').error, retry_after_seconds: 600 } } }
  })
  await page.goto('/notes/31')
  await askAi(page)
  await expect.poll(() => state.calls.length).toBe(1)
  await switchToAccountB(page)
  await askAi(page)
  const sheet = page.getByRole('dialog', { name: 'UnknownWord' })
  await expect(sheet.getByText('600초 뒤에 다시 시도할 수 있어요')).toBeVisible()
  held.release() // A의 늦은 429(5초 대기)
  await page.waitForTimeout(300)
  await page.clock.fastForward(10_000) // A의 5초가 지나도 B는 600초 대기를 유지한다
  await expect(retryButton(page)).toHaveAttribute('aria-disabled', 'true')
  await retryButton(page).click({ force: true })
  await page.waitForTimeout(200)
  expect(state.calls).toHaveLength(2)
})

test('AC-3 A의 응답 미확정(network_error) 뒤 B의 첫 요청은 새 Idempotency-Key를 쓴다', async ({ page }) => {
  const state = await setupAiSwitch(page, (_call, n) => n === 1 ? 'abort' : aiText('B의 설명'))
  await page.goto('/notes/31')
  await askAi(page)
  await expect(page.getByRole('dialog', { name: 'UnknownWord' }).getByText('AI 설명을 불러오지 못했어요')).toBeVisible()
  await switchToAccountB(page)
  await askAi(page)
  await expect(page.getByRole('dialog', { name: 'UnknownWord' }).getByText('B의 설명')).toBeVisible()
  expect(state.calls).toHaveLength(2)
  expect(state.calls[0].key).toBeTruthy()
  expect(state.calls[1].key).toBeTruthy()
  expect(state.calls[1].key).not.toBe(state.calls[0].key)
})

// 독립 리뷰 보완: 로그인·로그아웃이 실패하면 세션이 바뀐 것이 아니므로 같은 계정의 재시도 키·대기가 끊기지 않는다. 대기 조회는 요청을 시작한 세션 번호로 한다.
test('로그아웃이 실패하면 같은 계정의 응답 미확정 재시도 키가 이어진다', async ({ page }) => {
  const state = await setupAiSwitch(page, (_call, n) => n === 1 ? 'abort' : aiText('A의 설명'))
  await page.route('**/api/auth/logout', (route) => route.fulfill({ status: 500, json: aiError('internal_error') })) // 나중에 등록한 경로가 우선한다
  await page.goto('/notes/31')
  await askAi(page)
  await expect(page.getByRole('dialog', { name: 'UnknownWord' }).getByText('AI 설명을 불러오지 못했어요')).toBeVisible()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: /^내 계정/ }).click()
  await page.getByRole('menuitem', { name: '로그아웃' }).click()
  await expect(page.getByRole('alert')).toBeVisible() // 로그아웃 실패 안내. 로그인 상태는 그대로다
  await page.keyboard.press('Escape')
  await askAi(page)
  await expect(page.getByRole('dialog', { name: 'UnknownWord' }).getByText('A의 설명')).toBeVisible()
  expect(state.calls).toHaveLength(2)
  expect(state.calls[1].key).toBe(state.calls[0].key) // 같은 세션이라 응답을 받지 못한 요청의 키를 다시 쓴다
})

test('로그인에 실패해도 세션 번호는 올라가지 않고 성공하면 올라간다', async ({ page }) => {
  await page.route('**/api/me', (route) => route.fulfill({ json: { authenticated: false } }))
  let fail = true
  await page.route('**/api/auth/login', (route) => fail
    ? route.fulfill({ status: 401, json: aiError('invalid_credentials') })
    : route.fulfill({ json: { user: { role: 'member', display_name: '같은이름' } } }))
  await page.goto('/')
  const result = await page.evaluate(async (shouldFail) => {
    const { login } = await import('/src/auth/login.ts')
    const { currentSession } = await import('/src/auth/sessionGeneration.ts')
    const before = currentSession()
    await login('a@example.test', 'wrong').catch(() => {})
    const afterFailure = currentSession()
    return { before, afterFailure, shouldFail }
  }, fail)
  expect(result.afterFailure).toBe(result.before)
  fail = false
  const afterSuccess = await page.evaluate(async () => {
    const { login } = await import('/src/auth/login.ts')
    const { currentSession } = await import('/src/auth/sessionGeneration.ts')
    const before = currentSession()
    await login('a@example.test', 'right')
    return currentSession() > before
  })
  expect(afterSuccess).toBe(true)
})

test('서버 대기 시각은 요청을 시작한 세션 번호로 조회한다(다른 세션 번호로는 보이지 않는다)', async ({ page }) => {
  await page.route('**/api/ai/explanations', (route) => route.fulfill({ status: 429, json: { error: { ...aiError('rate_limited').error, retry_after_seconds: 60 } } }))
  await page.goto('/')
  const result = await page.evaluate(async () => {
    const { requestExplanation, retryAvailableAt } = await import('/src/ai/explain.ts')
    const target = { noteId: 31, revision: 5, start: 0, end: 4 }
    await requestExplanation(target, 9001).catch(() => {})
    return { same: retryAvailableAt(target, 9001) !== null, other: retryAvailableAt(target, 9002) }
  })
  expect(result.same).toBe(true)
  expect(result.other).toBeNull()
})
