import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// MEG-76 용어 바텀시트(F1-3). playwright.config.ts가 VITE_API_MOCK=true로 서버를 띄우므로 가짜 응답(E05 예시 1, E06 예시 2, E07)으로 시험한다.
// E06·E07 호출 횟수와 실패 분기는 브라우저 fetch 경로가 필요해 notes.spec.ts에서 시험한다. 실제 백엔드의 E06·E07은 확인하지 못한다.
const term = (page: Page) => page.getByRole('link', { name: 'ExampleTerm' })
const sheet = (page: Page) => page.getByRole('dialog', { name: 'ExampleTerm' })

test('AC-1 용어를 누르면 시트에 사전 배지, 용어 이름, 설명, 이미지가 나온다', async ({ page }) => {
  await page.goto('/notes/11')
  await term(page).click()
  await expect(sheet(page)).toBeVisible()
  await expect(sheet(page).getByText('사전', { exact: true })).toBeVisible()
  await expect(sheet(page).getByRole('heading', { name: 'ExampleTerm' })).toBeFocused()
  await expect(sheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  const image = sheet(page).getByRole('img', { name: '합성 구조도' })
  await expect(image).toBeVisible()
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0)).toBe(true)
  // 주소는 그대로이고, 방문자의 정상 열람에는 오류·기록 실패 안내가 없다
  await expect(page).toHaveURL(/\/notes\/11$/)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByText('열람 기록을 저장하지 못했어요')).toHaveCount(0)
})

test('Esc·닫기 버튼·막 누르기로 닫히고 포커스가 용어 링크로 돌아온다', async ({ page }) => {
  await page.goto('/notes/11')
  await term(page).click()
  await expect(sheet(page)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(sheet(page)).toBeHidden()
  await expect(term(page)).toBeFocused()

  await term(page).click()
  await page.getByRole('button', { name: '닫기' }).click()
  await expect(sheet(page)).toBeHidden()
  await expect(term(page)).toBeFocused()

  await term(page).click()
  await expect(sheet(page)).toBeVisible()
  await page.mouse.click(195, 20) // 시트 위쪽 막
  await expect(sheet(page)).toBeHidden()
  await expect(term(page)).toBeFocused()
})

test('닫았다 다시 열어도 같은 내용이 새로 보인다', async ({ page }) => {
  await page.goto('/notes/11')
  await term(page).click()
  await expect(sheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(sheet(page)).toBeHidden()
  await term(page).click()
  await expect(sheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await expect(sheet(page).getByRole('img', { name: '합성 구조도' })).toBeVisible()
})

test('로그인한 사용자가 열면 열람이 기록돼 기록 실패 안내가 없다(E07 recorded: true)', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('이메일').fill('member@example.test')
  await page.getByLabel('비밀번호').fill('example-password')
  await page.getByRole('button', { name: '로그인' }).click()
  await expect(page).toHaveURL(/\/quiz$/)
  // 가짜 로그인 상태는 메모리에만 있어 새로 고치지 않고 임시 화면(/quiz)의 이동 링크로 옮긴다
  await page.getByRole('link', { name: 'F1-2 노트 읽기(노트 11)' }).click()
  await term(page).click()
  await expect(sheet(page).getByText('합성 설명 문장입니다.')).toBeVisible()
  await expect(page.getByText('열람 기록을 저장하지 못했어요')).toHaveCount(0)
})
