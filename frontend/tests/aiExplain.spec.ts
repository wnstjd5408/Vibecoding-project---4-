import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// MEG-106 AI 설명(F2-1·F2-2a·F2-2b). playwright.config.ts가 VITE_API_MOCK=true로 서버를 띄우므로
// 가짜 응답(E05 예시 1, E09 예시 3: 방문자 401·로그인 사용자는 선택 위치에 따라 세 갈래)으로 실제 노트 화면에서 시험한다.
// 요청 헤더·본문, 오류 코드별 안내, 재시도 키는 브라우저 fetch 경로가 필요해 notes.spec.ts에서 시험한다. 실제 백엔드의 E09는 확인하지 못한다.

const aiButton = (page: Page) => page.getByRole('button', { name: 'AI 설명', exact: true })
const aiSheet = (page: Page, name: string) => page.getByRole('dialog', { name })
const loginSheet = (page: Page) => page.getByRole('dialog', { name: '로그인이 필요해요' })

// 화면에서 글자를 드래그해 고른 것처럼 본문 안의 글자 범위를 선택한다.
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

async function loginAsMember(page: Page) {
  await page.goto('/login')
  await page.getByLabel('이메일').fill('member@example.test')
  await page.getByLabel('비밀번호').fill('example-password')
  await page.getByRole('button', { name: '로그인' }).click()
  await expect(page).toHaveURL(/\/quiz$/)
  // 가짜 로그인 상태는 메모리에만 있어 새로 고치지 않고 임시 화면(/quiz)의 이동 링크로 옮긴다
  await page.getByRole('link', { name: 'F1-2 노트 읽기(노트 11)' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
}

test('AC-1 로그인 사용자가 사전에 없는 단어를 고르면 "AI 생성·검수 전" 표시가 있는 설명 시트가 열린다', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await loginAsMember(page)
  await expect(aiButton(page)).toHaveCount(0) // 고르기 전에는 버튼이 없다
  await selectText(page, 'UnknownWord')
  await expect(aiButton(page)).toBeVisible()
  await testInfo.attach('F2-1 단어를 고른 상태', { body: await page.screenshot(), contentType: 'image/png' })
  await aiButton(page).click()
  const sheet = aiSheet(page, 'UnknownWord')
  await expect(sheet).toBeVisible()
  await expect(sheet.getByText('AI 생성·검수 전')).toBeVisible()
  await expect(sheet.getByRole('group', { name: 'AI 생성 설명' }).getByText('합성 AI 설명입니다.')).toBeVisible()
  await expect(aiButton(page)).toHaveCount(0) // 시트가 열리면 선택과 버튼은 정리된다
  await testInfo.attach('F2-2a AI 설명 시트', { body: await page.screenshot(), contentType: 'image/png' })
  await page.keyboard.press('Escape')
  await expect(sheet).toBeHidden()
})

test('AC-2 방문자가 단어를 고르고 AI 설명 버튼을 누르면 로그인 안내가 열린다', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/notes/11')
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
  await selectText(page, 'UnknownWord')
  await aiButton(page).click()
  await expect(loginSheet(page)).toBeVisible()
  await expect(loginSheet(page).getByText('로그인하면 AI 설명, 즐겨찾기, 오늘의 퀴즈를 쓸 수 있어요. 계정은 운영자가 만들어 줘요.')).toBeVisible()
  await expect(page.getByRole('dialog', { name: 'UnknownWord' })).toHaveCount(0)
  await testInfo.attach('F2-2b 방문자 로그인 안내', { body: await page.screenshot(), contentType: 'image/png' })
  await page.keyboard.press('Escape')
  await expect(loginSheet(page)).toBeHidden()
})

test('사전에 있는 용어를 고르면 사전 설명과 이미지가 보이고 AI 표시는 없다', async ({ page }) => {
  await loginAsMember(page)
  await selectText(page, 'ExampleTerm')
  await aiButton(page).click()
  const sheet = aiSheet(page, 'ExampleTerm')
  await expect(sheet.getByText('합성 설명 문장입니다.')).toBeVisible()
  await expect(sheet.getByText('사전', { exact: true })).toBeVisible()
  await expect(sheet.getByRole('img', { name: '합성 구조도' })).toBeVisible()
  await expect(sheet.getByText('AI 생성')).toHaveCount(0)
})

test('저장하지 않는 1회용 설명에는 즐겨찾기·신고 같은 기능이 없다', async ({ page }) => {
  await loginAsMember(page)
  await selectText(page, '설명합니다')
  await aiButton(page).click()
  const sheet = aiSheet(page, '설명합니다')
  await expect(sheet.getByText('합성 1회용 AI 설명입니다.')).toBeVisible()
  await expect(sheet.getByRole('button', { name: /즐겨찾기|신고/ })).toHaveCount(0)
})

test('선택을 풀거나 공백만 고르면 버튼이 사라진다', async ({ page }) => {
  await loginAsMember(page)
  await selectText(page, 'UnknownWord')
  await expect(aiButton(page)).toBeVisible()
  await page.evaluate(() => document.getSelection()!.removeAllRanges())
  await expect(aiButton(page)).toHaveCount(0)
  await selectText(page, ' ') // 첫 공백 한 칸
  await page.waitForTimeout(150)
  await expect(aiButton(page)).toHaveCount(0)
})

test('제목처럼 본문 밖을 고르면 버튼이 없다', async ({ page }) => {
  await loginAsMember(page)
  await page.evaluate(() => {
    const range = document.createRange()
    range.selectNodeContents(document.querySelector('h1')!)
    const selection = document.getSelection()!
    selection.removeAllRanges()
    selection.addRange(range)
  })
  await page.waitForTimeout(150)
  await expect(aiButton(page)).toHaveCount(0)
})

for (const [name, close] of [
  ['Esc', (page: Page) => page.keyboard.press('Escape')],
  ['닫기 버튼', (page: Page) => page.getByRole('button', { name: '닫기' }).click()],
  ['막(스크림) 누르기', (page: Page) => page.mouse.click(195, 20)],
] as const) {
  test(`방문자의 로그인 안내를 ${name}로 닫으면 포커스가 노트 본문으로 돌아온다`, async ({ page }) => {
    await page.goto('/notes/11')
    await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
    await selectText(page, 'UnknownWord')
    await aiButton(page).click()
    await expect(loginSheet(page)).toBeVisible()
    await close(page)
    await expect(loginSheet(page)).toBeHidden()
    await expect(page.locator('article')).toBeFocused()
  })
}

test('방문자의 로그인 안내에서 로그인 버튼을 누르면 /login으로 이동하고 안내가 남지 않는다', async ({ page }) => {
  await page.goto('/notes/11')
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
  await selectText(page, 'UnknownWord')
  await aiButton(page).click()
  await loginSheet(page).getByRole('link', { name: '로그인' }).click()
  await expect(page).toHaveURL(/\/login$/)
  await expect(loginSheet(page)).toHaveCount(0)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
})

test('버튼을 누른 채 밖으로 끌어 떼도 이후 선택 변화를 버튼이 따라간다', async ({ page }) => {
  await loginAsMember(page)
  await selectText(page, 'UnknownWord')
  const box = (await aiButton(page).boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height + 120)
  await page.mouse.up()
  await expect(aiButton(page)).toBeVisible() // 누르기만 하고 클릭이 되지 않았으니 시트는 열리지 않는다
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await page.evaluate(() => document.getSelection()!.removeAllRanges())
  await expect(aiButton(page)).toHaveCount(0)
})
