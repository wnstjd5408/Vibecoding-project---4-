import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

// MEG-144 PC 사이드 패널(1024px 이상). 가짜 응답(방문자, E05 예시 1, E06 예시 2, E07)으로 실제 노트 화면에서 시험한다.
// 용어가 둘인 노트, 요청 횟수, 오류 분기는 브라우저 fetch 경로가 필요해 notes.spec.ts에서 시험한다.
const PC = { width: 1280, height: 800 }
const term = (page: Page) => page.getByRole('link', { name: 'ExampleTerm' })
const panel = (page: Page) => page.getByRole('dialog', { name: 'ExampleTerm' })

async function box(locator: Locator) {
  const result = await locator.boundingBox()
  if (!result) throw new Error('보이지 않는 요소다')
  return result
}

test.describe('PC 폭 용어 패널', () => {
  test.use({ viewport: PC })

  test('AC-2 용어를 누르면 오른쪽 480px 패널이 헤더 아래에 열리고 스크림이 없다(모달이 아니다)', async ({ page }) => {
    await page.goto('/notes/11')
    await term(page).click()
    await expect(panel(page)).toBeVisible()
    const rect = await box(panel(page))
    expect(Math.round(rect.width)).toBe(480)
    expect(Math.round(rect.x + rect.width)).toBe(PC.width) // 오른쪽 끝에 붙는다
    expect(Math.round(rect.y)).toBe(57) // 헤더(56px)와 구분선 바로 아래
    expect(Math.round(rect.y + rect.height)).toBe(PC.height) // 화면 아래까지
    // 비모달: 브라우저의 모달 대화상자가 아니고, 배경을 어둡게 덮는 막이 없다
    expect(await panel(page).evaluate((element) => element.matches(':modal'))).toBe(false)
    // (닫혀 있는 다른 시트에 들어 있는 막은 보이지 않으므로 세지 않는다)
    await expect(page.locator('[class*="scrim"]:visible')).toHaveCount(0)
    // 본문 스크롤을 잠그지 않는다
    expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden')
  })

  test('패널이 열려도 본문은 패널에 가려지지 않고 남은 영역의 가운데에 놓인다(열 x 40~760)', async ({ page }) => {
    await page.goto('/notes/11')
    await term(page).click()
    await expect(panel(page)).toBeVisible()
    const article = await box(page.locator('article'))
    const sheet = await box(panel(page))
    expect(article.x + article.width).toBeLessThanOrEqual(sheet.x) // 본문이 패널 왼쪽에서 끝난다
    expect(Math.round(article.x)).toBe(40)
    expect(Math.round(article.width)).toBe(720)
    // 본문은 계속 읽고 누를 수 있다
    await expect(page.getByText('이 노트는')).toBeVisible()
  })

  test('패널 첫 줄에 배지와 "닫기"가 있고 그 아래에 제목이 있다(손잡이 없음)', async ({ page }) => {
    await page.goto('/notes/11')
    await term(page).click()
    const badge = await box(panel(page).getByText('사전', { exact: true }))
    const close = await box(panel(page).getByRole('button', { name: '닫기' }))
    const title = await box(panel(page).getByRole('heading', { name: 'ExampleTerm' }))
    expect(Math.abs((badge.y + badge.height / 2) - (close.y + close.height / 2))).toBeLessThanOrEqual(6) // 같은 줄
    expect(badge.x).toBeLessThan(close.x) // 배지는 왼쪽, 닫기는 오른쪽
    expect(title.y).toBeGreaterThan(close.y + close.height - 4) // 제목은 그 아래
    await expect(panel(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  })

  test('AC-3 처음 열 때 제목으로 포커스가 가고, 용어 링크는 aria-expanded·aria-controls로 패널과 이어진다', async ({ page }) => {
    await page.goto('/notes/11')
    await expect(term(page)).toHaveAttribute('aria-expanded', 'false')
    await term(page).click()
    await expect(panel(page)).toBeVisible()
    await expect(panel(page).getByRole('heading', { name: 'ExampleTerm' })).toBeFocused()
    await expect(term(page)).toHaveAttribute('aria-expanded', 'true')
    const panelId = await panel(page).getAttribute('id')
    expect(panelId).toBeTruthy()
    await expect(term(page)).toHaveAttribute('aria-controls', panelId ?? '')
  })

  test('AC-3 Esc로 닫으면 용어 링크로 포커스가 돌아오고 aria-expanded가 false가 된다', async ({ page }) => {
    await page.goto('/notes/11')
    await term(page).click()
    await expect(panel(page)).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(panel(page)).toBeHidden()
    await expect(term(page)).toBeFocused()
    await expect(term(page)).toHaveAttribute('aria-expanded', 'false')
  })

  test('AC-3 "닫기" 버튼으로 닫아도 용어 링크로 포커스가 돌아온다', async ({ page }) => {
    await page.goto('/notes/11')
    await term(page).click()
    await panel(page).getByRole('button', { name: '닫기' }).click()
    await expect(panel(page)).toBeHidden()
    await expect(term(page)).toBeFocused()
  })

  test('패널이 열린 채 본문을 누르거나 스크롤해도 패널은 닫히지 않는다(스크림·막 누르기 없음)', async ({ page }) => {
    await page.goto('/notes/11')
    await term(page).click()
    await expect(panel(page)).toBeVisible()
    await page.getByText('이 노트는').click()
    await expect(panel(page)).toBeVisible()
  })
})

test.describe('모바일(1023px)은 기존 바텀시트다', () => {
  test('1023px에서는 모달 시트이고 스크림이 있으며 aria-expanded가 없다', async ({ page }) => {
    await page.setViewportSize({ width: 1023, height: 800 })
    await page.goto('/notes/11')
    await expect(term(page)).not.toHaveAttribute('aria-expanded', /.*/)
    await term(page).click()
    await expect(panel(page)).toBeVisible()
    expect(await panel(page).evaluate((element) => element.matches(':modal'))).toBe(true)
    expect(await page.evaluate(() => document.body.style.overflow)).toBe('hidden')
  })
})

// 로그인 안내: 용어 즐겨찾기가 E08 401을 받았을 때(F3-2d)만 PC 패널이다. AI 요청(F2-2b)과 다른 화면의 안내는 PC 폭에서도 바텀시트다.
const loginDialog = (page: Page) => page.getByRole('dialog', { name: '로그인이 필요해요' })

async function selectText(page: Page, needle: string) {
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

test.describe('PC 폭 로그인 안내', () => {
  test.use({ viewport: PC })

  test('AC-4 방문자가 즐겨찾기를 누르면(E08 401) 용어 패널이 닫히고 같은 자리에 로그인 안내 패널이 열린다', async ({ page }) => {
    await page.goto('/notes/11')
    await term(page).click()
    await expect(panel(page)).toBeVisible()
    await panel(page).getByRole('button', { name: '즐겨찾기', exact: true }).click()
    await expect(loginDialog(page)).toBeVisible()
    await expect(panel(page)).toBeHidden() // 용어 패널은 닫힌다
    const rect = await box(loginDialog(page))
    expect(Math.round(rect.width)).toBe(480)
    expect(Math.round(rect.x + rect.width)).toBe(PC.width)
    expect(Math.round(rect.y)).toBe(57) // 용어 패널과 같은 자리
    expect(await loginDialog(page).evaluate((element) => element.matches(':modal'))).toBe(false) // 비모달
    await expect(page.locator('[class*="scrim"]:visible')).toHaveCount(0)
    await expect(loginDialog(page).getByText('로그인하면 AI 설명, 즐겨찾기, 오늘의 퀴즈를 쓸 수 있어요.')).toBeVisible()
    // 본문은 패널 때문에 다시 가운데로 움직이지 않고 그대로 왼쪽 영역에 남는다
    expect(Math.round((await box(page.locator('article'))).x)).toBe(40)
  })

  test('AC-4 로그인 버튼은 패널 폭을 채우지 않고 내용 폭이다', async ({ page }) => {
    await page.goto('/notes/11')
    await term(page).click()
    await panel(page).getByRole('button', { name: '즐겨찾기', exact: true }).click()
    await expect(loginDialog(page)).toBeVisible()
    const button = await box(loginDialog(page).getByRole('link', { name: '로그인' }))
    expect(button.width).toBeLessThan(160)
  })

  test('AC-4 로그인 안내 패널을 닫기·Esc로 닫으면 마지막으로 누른 용어 링크로 포커스가 돌아온다', async ({ page }) => {
    await page.goto('/notes/11')
    await term(page).click()
    await panel(page).getByRole('button', { name: '즐겨찾기', exact: true }).click()
    await expect(loginDialog(page)).toBeVisible()
    await loginDialog(page).getByRole('button', { name: '닫기' }).click()
    await expect(loginDialog(page)).toBeHidden()
    await expect(term(page)).toBeFocused()
    // 다시 열어 Esc로 닫아도 같다
    await term(page).click()
    await panel(page).getByRole('button', { name: '즐겨찾기', exact: true }).click()
    await expect(loginDialog(page)).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(loginDialog(page)).toBeHidden()
    await expect(term(page)).toBeFocused()
  })

  test('AC-4 AI 요청의 로그인 안내(F2-2b)는 노트 읽기 화면에서도 PC 폭에서 기존 바텀시트다', async ({ page }) => {
    await page.goto('/notes/11')
    await page.locator('[data-note-body]').waitFor()
    await selectText(page, 'UnknownWord')
    await page.getByRole('button', { name: 'AI 설명', exact: true }).click()
    await expect(loginDialog(page)).toBeVisible()
    expect(await loginDialog(page).evaluate((element) => element.matches(':modal'))).toBe(true) // 모달 시트
    await expect(page.locator('[class*="scrim"]:visible')).toHaveCount(1)
  })

  test('AC-4 다른 화면(오늘의 퀴즈)의 로그인 안내도 PC 폭에서 기존 바텀시트다', async ({ page }) => {
    await page.goto('/quiz')
    await expect(loginDialog(page)).toBeVisible()
    expect(await loginDialog(page).evaluate((element) => element.matches(':modal'))).toBe(true)
  })
})

// AI 설명 패널(F2-2a PC): 로그인한 사용자가 단어를 골라 연다. 가짜 응답(E09 예시 3)이고 실제 E09 연동은 확인하지 못한다.
const aiPanel = (page: Page) => page.getByRole('dialog', { name: 'UnknownWord' })
const reportDialog = (page: Page) => page.getByRole('dialog', { name: '오류 신고' })

async function loginAsMember(page: Page) {
  await page.goto('/login')
  await page.getByLabel('이메일').fill('member@example.test')
  await page.getByLabel('비밀번호').fill('example-password')
  await page.getByRole('button', { name: '로그인' }).click()
  await expect(page).toHaveURL(/\/quiz$/)
  // 가짜 로그인 상태는 메모리에만 있어 새로 고치지 않고 앱 안에서 경로를 옮긴다
  await page.evaluate(() => {
    history.pushState({}, '', '/notes/11')
    dispatchEvent(new PopStateEvent('popstate'))
  })
  await page.locator('[data-note-body]').waitFor()
}

async function openAiPanel(page: Page) {
  await selectText(page, 'UnknownWord')
  await page.getByRole('button', { name: 'AI 설명', exact: true }).click()
  await expect(aiPanel(page)).toBeVisible()
}

test.describe('PC 폭 AI 설명 패널', () => {
  test.use({ viewport: PC })

  test('AC-5 AI 설명이 오른쪽 480px 비모달 패널로 열리고 버튼 줄에 "오류 신고"만 있다(즐겨찾기 별 없음)', async ({ page }) => {
    await loginAsMember(page)
    await openAiPanel(page)
    const rect = await box(aiPanel(page))
    expect(Math.round(rect.width)).toBe(480)
    expect(Math.round(rect.x + rect.width)).toBe(PC.width)
    expect(Math.round(rect.y)).toBe(57)
    expect(await aiPanel(page).evaluate((element) => element.matches(':modal'))).toBe(false)
    await expect(aiPanel(page).getByText('AI 생성·검수 전')).toBeVisible()
    await expect(aiPanel(page).getByRole('group', { name: 'AI 생성 설명' }).getByText('합성 AI 설명입니다.')).toBeVisible()
    await expect(aiPanel(page).getByRole('button', { name: '오류 신고' })).toBeVisible()
    // AI 설명 즐겨찾기는 이번 범위가 아니라 별 버튼을 그리지 않는다
    await expect(aiPanel(page).getByRole('button', { name: /즐겨찾기/ })).toHaveCount(0)
    // 본문은 패널에 가려지지 않는다
    expect(Math.round((await box(page.locator('article'))).x)).toBe(40)
    expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden')
  })

  test('AC-5 "오류 신고"를 누르면 기존 입력 모달이 패널 위에 열리고, Esc는 모달만 닫은 뒤 패널을 닫는다', async ({ page }) => {
    await loginAsMember(page)
    await openAiPanel(page)
    await aiPanel(page).getByRole('button', { name: '오류 신고' }).click()
    await expect(reportDialog(page)).toBeVisible()
    expect(await reportDialog(page).evaluate((element) => element.matches(':modal'))).toBe(true)
    await expect(aiPanel(page)).toBeVisible() // 패널은 그대로 아래에 있다
    await page.keyboard.press('Escape')
    await expect(reportDialog(page)).toBeHidden()
    await expect(aiPanel(page)).toBeVisible() // 모달만 닫혔다
    await page.keyboard.press('Escape')
    await expect(aiPanel(page)).toBeHidden()
  })

  test('AI 설명 패널을 닫으면 포커스가 본문으로 돌아온다', async ({ page }) => {
    await loginAsMember(page)
    await openAiPanel(page)
    await expect(aiPanel(page).getByRole('heading', { name: 'UnknownWord' })).toBeFocused() // 처음 열 때 제목으로
    await aiPanel(page).getByRole('button', { name: '닫기' }).click()
    await expect(aiPanel(page)).toBeHidden()
    await expect(page.locator('article')).toBeFocused()
  })

  test('패널은 한 번에 하나만 열린다: 용어 패널이 열린 채 AI 설명을 열면 용어 패널이 닫히고, 반대도 같다', async ({ page }) => {
    await loginAsMember(page)
    await term(page).click()
    await expect(panel(page)).toBeVisible()
    await openAiPanel(page)
    await expect(panel(page)).toBeHidden()
    await expect(page.getByRole('dialog')).toHaveCount(1) // 열린 패널은 AI 설명 하나
    // 반대로 AI 패널이 열린 채 용어를 누르면 AI 패널이 닫히고 용어 패널이 열린다
    await term(page).click()
    await expect(panel(page)).toBeVisible()
    await expect(aiPanel(page)).toBeHidden()
    await expect(term(page)).toHaveAttribute('aria-expanded', 'true')
  })
})
