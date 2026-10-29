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
  await page.getByRole('link', { name: /연결과 학습/ }).click()
  await expect(page).toHaveURL(/\/notes\/12$/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('F1-2')
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
  await expect(page.getByRole('link', { name: '내 정보' })).toBeVisible()
  await expect(page.getByRole('link', { name: /운영자 비공개 노트/ })).toBeVisible()
  await testInfo.attach('운영자 목록', { body: await page.screenshot(), contentType: 'image/png' })
})

test('일반 사용자와 좁은 화면에서 목록·키보드 조작을 제공한다', async ({ page }) => {
  await setup(page)
  await page.route('**/api/me', (route) => route.fulfill({ json: { authenticated: true, role: 'member' } }))
  await page.setViewportSize({ width: 320, height: 700 })
  await page.goto('/')
  await expect(page.getByRole('link', { name: '내 정보' })).toBeVisible()
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
