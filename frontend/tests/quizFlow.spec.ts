import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'

async function fixture(page: Page, answered = false) {
  const item = { id: 51, question: '스택에서 가장 먼저 꺼내는 값은?', difficulty: '하', answered, your_answer: answered ? '마지막 값' : undefined,
    correct_answer: answered ? '마지막에 넣은 값' : undefined, explanation: answered ? '후입선출 구조입니다.' : undefined,
    can_request_followup: answered, followups: [] as { seq: number; question: string; answered: boolean }[] }
  let answers = 0
  let generations = 0
  let saves = 0
  await page.route('**/api/me', route => route.fulfill({ json: { authenticated: true, role: 'member' } }))
  await page.route('**/api/quiz/today', route => route.fulfill({ json: { status: 'ready', quiz_date: '2026-11-03', items: [item] } }))
  await page.route('**/api/quiz/items/51/answer', async route => {
    answers++
    expect(route.request().method()).toBe('POST')
    item.answered = true
    item.your_answer = route.request().postDataJSON().answer
    item.correct_answer = '마지막에 넣은 값'
    item.explanation = '후입선출 구조입니다.'
    item.can_request_followup = true
    await route.fulfill({ json: { item_id: 51, your_answer: item.your_answer, correct_answer: item.correct_answer, explanation: item.explanation, difficulty: '하', can_request_followup: true, followups_remaining: 2 } })
  })
  await page.route('**/api/quiz/items/51/followups', async route => {
    generations++
    expect(route.request().method()).toBe('POST')
    const seq = item.followups.length + 1
    item.followups.push({ seq, question: `합성 꼬리 질문 ${seq}`, answered: false })
    item.can_request_followup = false
    await route.fulfill({ json: { seq, question: `합성 꼬리 질문 ${seq}`, followups_remaining: 2 - seq } })
  })
  await page.route('**/api/quiz/items/51/followups/*/answer', async route => {
    saves++
    expect(route.request().method()).toBe('PUT')
    const seq = Number(route.request().url().split('/').at(-2))
    item.followups[seq - 1].answered = true
    item.can_request_followup = seq < 2
    await route.fulfill({ json: { seq, answered: true, can_request_followup: seq < 2 } })
  })
  return { item, counts: () => ({ answers, generations, saves }) }
}

for (const width of [390, 1280]) test(`E12→E13→E14 두 차례와 재접속 복원 (${width}px)`, async ({ page }) => {
  const state = await fixture(page)
  await page.setViewportSize({ width, height: 900 })
  await page.goto('/quiz')
  await expect(page.getByText('마지막에 넣은 값')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '꼬리 질문 받기' })).toHaveCount(0)
  await page.getByLabel('문항에 대한 답').fill('마지막 값')
  await page.getByRole('button', { name: '답 제출', exact: true }).click()
  await expect(page.getByText('후입선출 구조입니다.')).toBeVisible()
  await page.reload()
  await expect(page.getByText('마지막 값', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '정답과 해설' })).toBeVisible()
  await expect(page.getByText('마지막에 넣은 값', { exact: true })).toBeVisible()
  await expect(page.getByText('후입선출 구조입니다.', { exact: true })).toBeVisible()
  for (const seq of [1, 2]) {
    await page.getByRole('button', { name: '꼬리 질문 받기' }).click()
    await expect(page.getByText(`합성 꼬리 질문 ${seq}`)).toBeVisible()
    // MEG-110 AC-1: 꼬리 질문마다 "꼬리 질문 n/2" 제목과 "AI 생성" 표시가 보인다.
    const followup = page.getByRole('region', { name: `꼬리 질문 ${seq}/2` })
    await expect(followup.getByRole('heading', { name: `꼬리 질문 ${seq}/2` })).toBeVisible()
    await expect(followup.getByText('AI 생성', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '꼬리 질문 받기' })).toHaveCount(0)
    await page.reload()
    await page.getByLabel(`꼬리 질문 ${seq}에 대한 답`).fill(`합성 답변 ${seq}`)
    await page.getByRole('button', { name: '답 저장', exact: true }).click()
    await expect(page.getByText('답 저장됨', { exact: true })).toHaveCount(seq)
  }
  await expect(page.getByText('꼬리 질문 2개를 모두 마쳤어요.')).toBeVisible()
  await page.reload()
  await expect(page.getByText('답 저장됨', { exact: true })).toHaveCount(2)
  await expect(page.getByRole('textbox')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '꼬리 질문 받기' })).toHaveCount(0)
  expect(state.counts()).toEqual({ answers: 1, generations: 2, saves: 2 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

// MEG-109 AC-3: 답한 문항이 담긴 E11 응답으로 열면 답 입력 없이 내 답·정답·해설이 그대로 보인다.
for (const width of [390, 1280]) test(`E11 응답에 답한 문항이 있으면 내 답·정답·해설을 복원한다 (${width}px)`, async ({ page }) => {
  await fixture(page, true)
  let answers = 0
  await page.route('**/api/quiz/items/51/answer', route => { answers++; return route.abort() })
  await page.setViewportSize({ width, height: 900 })
  await page.goto('/quiz')
  await expect(page.getByText('답함', { exact: true })).toBeVisible()
  await expect(page.getByText('마지막 값', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '정답과 해설' })).toBeVisible()
  await expect(page.getByText('마지막에 넣은 값', { exact: true })).toBeVisible()
  await expect(page.getByText('후입선출 구조입니다.', { exact: true })).toBeVisible()
  await expect(page.getByLabel('문항에 대한 답')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '답 제출', exact: true })).toHaveCount(0)
  expect(answers).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('공백·1001자는 전송하지 않고, 처리 중 중복 답 제출을 막는다', async ({ page }) => {
  await fixture(page)
  let calls = 0
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/quiz/items/51/answer', async route => { calls++; await gate; await route.fulfill({ status: 503, json: { error: { code: 'service_unavailable', message: 'Unavailable' } } }) })
  await page.goto('/quiz')
  await page.getByLabel('문항에 대한 답').fill('   ')
  await page.getByRole('button', { name: '답 제출', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('1~1,000자')
  await page.getByLabel('문항에 대한 답').fill('가'.repeat(1001))
  await page.getByRole('button', { name: '답 제출', exact: true }).click()
  expect(calls).toBe(0)
  await page.getByLabel('문항에 대한 답').fill('합성 답변')
  await page.getByRole('button', { name: '답 제출', exact: true }).dblclick()
  await expect.poll(() => calls).toBe(1)
  await expect(page.getByRole('button', { name: '답 제출', exact: true })).toHaveAttribute('aria-disabled', 'true')
  release()
  await expect(page.getByRole('alert')).toContainText('처리 결과를 확인하지 못했어요')
  await expect(page.getByLabel('문항에 대한 답')).toHaveValue('합성 답변')
})

for (const [status, code, detail, message] of [
  [404, 'not_found', undefined, '이 문항을 찾을 수 없어요'],
  [409, 'conflict', 'already_answered', '이미 다른 답이 저장되어 있어요'],
  [422, 'validation_failed', undefined, '답을 1~1,000자로'],
  [429, 'rate_limited', undefined, '요청이 많아요'],
] as const) test(`E12 오류 ${code}/${detail ?? ''}`, async ({ page }) => {
  await fixture(page)
  await page.route('**/api/quiz/items/51/answer', route => route.fulfill({ status, json: { error: { code, detail, message: 'Synthetic', retry_after_seconds: 60 } } }))
  await page.goto('/quiz')
  await page.getByLabel('문항에 대한 답').fill('합성 답변')
  await page.getByRole('button', { name: '답 제출', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText(message)
  if (status === 429) await expect(page.getByRole('button', { name: '답 제출', exact: true })).toHaveAttribute('aria-disabled', 'true')
})

for (const [status, code, detail, message] of [
  [409, 'conflict', 'answer_first', '문항에 먼저 답해 주세요'],
  [409, 'conflict', 'in_progress', '꼬리 질문을 만드는 중이에요'],
  [409, 'conflict', 'followup_limit_reached', '문항당 2개까지'],
  [429, 'ai_limit_reached', undefined, 'AI 사용 한도에 도달했어요'],
  [502, 'ai_unavailable', undefined, '꼬리 질문을 만들지 못했어요'],
] as const) test(`E13 오류 ${code}/${detail ?? ''}`, async ({ page }) => {
  await fixture(page, true)
  let calls = 0
  await page.route('**/api/quiz/items/51/followups', route => { calls++; return route.fulfill({ status, json: { error: { code, detail, message: 'Synthetic', retry_after_seconds: 60 } } }) })
  await page.goto('/quiz')
  await page.getByRole('button', { name: '꼬리 질문 받기' }).click()
  await expect(page.getByRole('alert')).toContainText(message)
  expect(calls).toBe(1)
  if (detail === 'in_progress') await expect(page.getByRole('button', { name: '꼬리 질문 받기' })).toHaveAttribute('aria-disabled', 'true')
})

test('401은 로그인 안내를 연다', async ({ page }) => {
  await fixture(page)
  await page.route('**/api/quiz/items/51/answer', route => route.fulfill({ status: 401, json: { error: { code: 'login_required', message: 'Login required' } } }))
  await page.goto('/quiz')
  await page.getByLabel('문항에 대한 답').fill('합성 답변')
  await page.getByRole('button', { name: '답 제출', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '로그인이 필요해요' })).toBeVisible()
})

for (const action of ['answer', 'followup', 'followup-answer'] as const) test(`${action}: 이탈 후 늦은 401은 로그인 안내를 다시 열지 않는다`, async ({ page }) => {
  const state = await fixture(page, action !== 'answer')
  if (action === 'followup-answer') {
    state.item.followups.push({ seq: 1, question: '기존 꼬리 질문', answered: false })
    state.item.can_request_followup = false
  }
  await page.route('**/api/notes', route => route.fulfill({ json: { subjects: [], notes: [] } }))
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let called = false
  const endpoint = action === 'answer' ? '/api/quiz/items/51/answer'
    : action === 'followup' ? '/api/quiz/items/51/followups' : '/api/quiz/items/51/followups/1/answer'
  await page.route(`**${endpoint}`, async route => {
    called = true; await gate
    await route.fulfill({ status: 401, json: { error: { code: 'login_required', message: 'Login required' } } })
  })
  await page.goto('/quiz')
  if (action !== 'followup') await page.getByLabel(action === 'answer' ? '문항에 대한 답' : '꼬리 질문 1에 대한 답').fill('합성 답변')
  await page.getByRole('button', { name: action === 'answer' ? '답 제출' : action === 'followup' ? '꼬리 질문 받기' : '답 저장', exact: true }).click()
  await expect.poll(() => called).toBe(true)
  await page.getByRole('link', { name: '노트 보러 가기' }).click()
  // SPA 클릭 완료만으로 React 화면 전환·이탈 처리가 끝났다고 가정하지 않는다.
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('heading', { name: '과목', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '오늘의 퀴즈', exact: true })).toHaveCount(0)
  const response = page.waitForResponse(`**${endpoint}`)
  release()
  const received = await response
  expect(received.status()).toBe(401)
  await received.finished()
  // route.fulfill 완료는 앱의 응답 처리 완료가 아니다. 응답 후 렌더 기회를 준 뒤 부재를 검사한다.
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
  await expect(page.getByRole('dialog', { name: '로그인이 필요해요' })).toHaveCount(0)
})

test('다른 세션에서 도착한 답 응답을 화면에 적용하지 않는다', async ({ page }) => {
  await fixture(page)
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let called = false
  await page.route('**/api/quiz/items/51/answer', async route => {
    called = true; await gate
    await route.fulfill({ json: { item_id: 51, your_answer: '옛 계정 답', correct_answer: '옛 계정 정답', explanation: '옛 계정 해설', difficulty: '하', can_request_followup: true, followups_remaining: 2 } })
  })
  await page.goto('/quiz')
  await page.getByLabel('문항에 대한 답').fill('합성 답변')
  await page.getByRole('button', { name: '답 제출', exact: true }).click()
  await expect.poll(() => called).toBe(true)
  await page.evaluate(async () => { const { startNewSession } = await import('/src/auth/sessionGeneration.ts'); startNewSession() })
  const response = page.waitForResponse('**/api/quiz/items/51/answer')
  release()
  await response
  await expect(page.getByText('옛 계정 정답')).toHaveCount(0)
})

test('E14 저장 실패는 질문과 입력을 보존하고 완료로 표시하지 않는다', async ({ page }) => {
  const state = await fixture(page, true)
  state.item.followups.push({ seq: 1, question: '기존 꼬리 질문', answered: false })
  state.item.can_request_followup = false
  await page.route('**/api/quiz/items/51/followups/1/answer', route => route.fulfill({ status: 503, json: { error: { code: 'service_unavailable', message: 'Unavailable' } } }))
  await page.goto('/quiz')
  await page.getByLabel('꼬리 질문 1에 대한 답').fill('저장할 합성 답변')
  await page.getByRole('button', { name: '답 저장', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByLabel('꼬리 질문 1에 대한 답')).toHaveValue('저장할 합성 답변')
  await expect(page.getByText('답 저장됨')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '꼬리 질문 받기' })).toHaveCount(0)
})
