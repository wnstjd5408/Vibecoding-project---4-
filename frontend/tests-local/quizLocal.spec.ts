import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { test, expect } from '@playwright/test'
import type { Browser, Page } from '@playwright/test'

// 로컬 실제 백엔드·DB·Auth로 E11~E14를 거치는 화면 시험이다(MEG-207). Bedrock만 시험용 가짜다.
// 합성 계정과 비밀번호는 backend/scripts/local_backend.py가 만든 .local-backend/.env에 있다. 값은 출력하지 않는다.
const ITEM_1 = 132101
const QUESTION_1 = '합성 질문: 스택에서 가장 먼저 꺼내는 값은?'

function localPassword(): string {
  const text = readFileSync(new URL('../../.local-backend/.env', import.meta.url), 'utf-8')
  const line = text.split(/\r?\n/).find((l) => l.startsWith('LOCAL_TEST_PASSWORD='))
  if (!line) throw new Error('.local-backend/.env에 LOCAL_TEST_PASSWORD가 없습니다. local_backend fixture를 먼저 실행하세요.')
  return line.slice('LOCAL_TEST_PASSWORD='.length)
}

async function login(page: Page, account: string) {
  await page.goto('/login')
  await page.getByLabel('이메일').fill(`${account}@example.test`)
  await page.getByLabel('비밀번호').fill(localPassword())
  await page.getByRole('button', { name: '로그인' }).click()
  await expect(page.getByLabel('이메일')).toHaveCount(0)
}

const card = (page: Page, question: string) => page.locator('section', { has: page.getByRole('heading', { name: question }) })

test.beforeEach(() => {
  execFileSync('uv', ['run', '--frozen', 'python', '-m', 'scripts.local_quiz_e2e', 'seed'], { cwd: '../backend', stdio: 'pipe' })
})

test('E11~E14: 답 제출, 정답·해설, 꼬리 질문 두 차례, 재접속 복원', async ({ page }) => {
  await login(page, 'member-a')
  await page.goto('/quiz')
  const first = card(page, QUESTION_1)
  await expect(first).toBeVisible()
  await expect(page.getByText('합성 해설: 후입선출 구조입니다.')).toHaveCount(0)

  await first.getByLabel('문항에 대한 답').fill('나중에 넣은 값')
  await first.getByRole('button', { name: '답 제출', exact: true }).click()
  await expect(first.getByText('합성 해설: 후입선출 구조입니다.')).toBeVisible()
  await expect(first.getByText('마지막에 넣은 값')).toBeVisible()
  await expect(first.getByText('나중에 넣은 값')).toBeVisible()

  for (const n of [1, 2]) {
    await first.getByRole('button', { name: '꼬리 질문 받기' }).click()
    await expect(first.getByRole('heading', { name: `꼬리 질문 ${n}/2` })).toBeVisible()
    await first.getByLabel(`꼬리 질문 ${n}에 대한 답`).fill(`합성 꼬리 답 ${n}`)
    await first.getByRole('button', { name: '답 저장' }).click()
    await expect(first.getByText('답 저장됨').nth(n - 1)).toBeVisible()
  }
  await expect(first.getByRole('button', { name: '꼬리 질문 받기' })).toHaveCount(0)

  // 재접속: DB에서 다시 읽어도 답·정답·해설·꼬리 질문 두 개가 그대로다. 꼬리 질문 답 원문은 E11이 돌려주지 않는다.
  await page.reload()
  const again = card(page, QUESTION_1)
  await expect(again.getByText('나중에 넣은 값')).toBeVisible()
  await expect(again.getByText('합성 해설: 후입선출 구조입니다.')).toBeVisible()
  await expect(again.getByRole('heading', { name: '꼬리 질문 1/2' })).toBeVisible()
  await expect(again.getByRole('heading', { name: '꼬리 질문 2/2' })).toBeVisible()
  await expect(again.getByText('답 저장됨')).toHaveCount(2)
  await expect(again.getByRole('button', { name: '꼬리 질문 받기' })).toHaveCount(0)
})

test('E12: 이미 답한 문항에 다시 제출하면 409이고 첫 답이 유지된다', async ({ page }) => {
  await login(page, 'member-a')
  await page.goto('/quiz')
  const first = card(page, QUESTION_1)
  await first.getByLabel('문항에 대한 답').fill('첫 답')
  await first.getByRole('button', { name: '답 제출', exact: true }).click()
  await expect(first.getByText('합성 해설: 후입선출 구조입니다.')).toBeVisible()

  const status = await page.evaluate(async (id) => {
    const response = await fetch(`/api/quiz/items/${id}/answer`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answer: '두 번째 답' }),
    })
    return response.status
  }, ITEM_1)
  expect(status).toBe(409)
  await page.reload()
  await expect(card(page, QUESTION_1).getByText('첫 답')).toBeVisible()
  await expect(card(page, QUESTION_1).getByText('두 번째 답')).toHaveCount(0)
})

async function otherAccount(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ baseURL: 'http://127.0.0.1:4187', viewport: { width: 390, height: 844 } })
  const page = await context.newPage()
  await login(page, 'member-b')
  return page
}

test('E12·E13: 다른 사용자의 문항에는 404이다', async ({ browser }) => {
  const page = await otherAccount(browser)
  await page.goto('/quiz')
  const results = await page.evaluate(async (id) => {
    const post = (path: string, body: unknown) => fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then((r) => r.status)
    return { answer: await post(`/api/quiz/items/${id}/answer`, { answer: '남의 문항에 답' }), followup: await post(`/api/quiz/items/${id}/followups`, {}) }
  }, ITEM_1)
  expect(results).toEqual({ answer: 404, followup: 404 })
  await page.context().close()
})

test('E13: 답하기 전에는 꼬리 질문을 만들 수 없다(409)', async ({ page }) => {
  await login(page, 'member-a')
  await page.goto('/quiz')
  await expect(card(page, QUESTION_1)).toBeVisible()
  const status = await page.evaluate(async (id) => (await fetch(`/api/quiz/items/${id}/followups`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
  })).status, ITEM_1)
  expect(status).toBe(409)
})
