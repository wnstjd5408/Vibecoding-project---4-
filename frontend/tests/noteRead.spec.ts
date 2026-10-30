import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// MEG-74 노트 읽기(F1-2). playwright.config.ts가 VITE_API_MOCK=true로 서버를 띄우므로 가짜 응답(E05 예시 1과 시험용 노트 12)으로 시험한다.
// 실제 E05는 아직 백엔드에 없어 이 시험이 확인하지 못한다.

const RICH_BODY = [
  '## 프로세스 **스케줄링**',
  '',
  '😀 ExampleTerm 은 \\*별표\\* 와 &amp; 가 있는 글에서도 찾아요.',
  '',
  '- 첫째 항목 ExampleTerm',
  '- 둘째 `code ExampleTerm` 항목',
  '',
  '```js',
  'const a = ExampleTerm',
  '```',
  '',
  '끝 줄입니다.',
].join('\n')

// 화면에서 글자 범위를 드래그한 것처럼 선택하고 sourceRangeOfSelection이 돌려준 원문 위치를 받는다.
async function selectedSource(page: Page, from: { text: string; offset: number }, to: { text: string; offset: number }) {
  return page.evaluate(async ({ from, to }) => {
    const { sourceRangeOfSelection } = await import('/src/notes/selection.ts')
    const root = document.querySelector('[data-note-body]')!
    const find = (needle: string) => {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
      for (let node = walker.nextNode(); node; node = walker.nextNode()) if (node.textContent?.includes(needle)) return node as Text
      throw new Error(`글자를 찾지 못했어요: ${needle}`)
    }
    const a = find(from.text)
    const b = find(to.text)
    const range = document.createRange()
    range.setStart(a, a.textContent!.indexOf(from.text) + from.offset)
    range.setEnd(b, b.textContent!.indexOf(to.text) + to.offset)
    return sourceRangeOfSelection(root, range)
  }, { from, to })
}

test('AC-1 사전 용어가 표시되고 누르면 용어 이름이 제목인 바텀시트가 열린다', async ({ page }) => {
  await page.goto('/notes/11')
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
  const term = page.getByRole('link', { name: 'ExampleTerm' })
  await expect(term).toHaveCount(1)
  await expect(term).toHaveAttribute('aria-haspopup', 'dialog')
  // 사전에 없는 글자는 용어가 아니다
  await expect(page.getByText('UnknownWord')).toBeVisible()
  await expect(page.getByRole('link', { name: 'UnknownWord' })).toHaveCount(0)

  await term.click()
  const sheet = page.getByRole('dialog', { name: 'ExampleTerm' })
  await expect(sheet).toBeVisible()
  await expect(page).toHaveURL(/\/notes\/11$/)
  await page.keyboard.press('Escape')
  await expect(sheet).toBeHidden()
  await expect(term).toBeFocused()
})

test('AC-2 본문 이미지가 보인다', async ({ page }) => {
  await page.goto('/notes/11')
  const image = page.getByRole('img', { name: '그림' })
  await expect(image).toBeVisible()
  await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.complete && element.naturalWidth > 0)).toBe(true)
})

test('없는 노트는 찾을 수 없음 안내와 목록 링크를 보인다', async ({ page }) => {
  await page.goto('/notes/404')
  await expect(page.getByRole('heading', { name: '찾을 수 없는 노트예요' })).toBeVisible()
  await page.getByRole('link', { name: '노트 목록으로' }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.goto('/notes/abc')
  await expect(page.getByRole('heading', { name: '찾을 수 없는 노트예요' })).toBeVisible()
})

test.describe('AC-3 렌더된 글에서 드래그한 범위의 원문 위치', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/notes/12')
    await expect(page.getByRole('heading', { level: 3, name: '프로세스 스케줄링' })).toBeVisible()
  })

  test('화면의 용어 표시가 서버 위치(코드포인트)와 같은 글자에 붙는다', async ({ page }) => {
    // 이모지가 UTF-16 두 칸이라, 코드포인트→UTF-16 변환이 틀리면 한 글자씩 밀린다
    const terms = page.locator('[data-note-body] [data-term-id]')
    await expect(terms).toHaveCount(4)
    await expect(terms).toHaveText(['ExampleTerm', 'ExampleTerm', 'ExampleTerm', 'ExampleTerm'])
  })

  test('되는 경우: 같은 글자 구간(굵게 안, 목록, 인라인 코드, 코드 블록, 용어 안)', async ({ page }) => {
    const slice = (r: { start: number; end: number } | null) => (r ? RICH_BODY.slice(r.start, r.end) : null)
    // 굵게 안
    expect(slice(await selectedSource(page, { text: '스케줄링', offset: 0 }, { text: '스케줄링', offset: 4 }))).toBe('스케줄링')
    // 이모지 뒤 용어
    expect(slice(await selectedSource(page, { text: 'ExampleTerm', offset: 0 }, { text: 'ExampleTerm', offset: 11 }))).toBe('ExampleTerm')
    // 목록 항목
    expect(slice(await selectedSource(page, { text: '첫째 항목 ', offset: 0 }, { text: '첫째 항목 ', offset: 6 }))).toBe('첫째 항목 ')
    // 인라인 코드 안
    expect(slice(await selectedSource(page, { text: 'code ', offset: 0 }, { text: 'code ', offset: 4 }))).toBe('code')
    // 코드 블록 안
    expect(slice(await selectedSource(page, { text: 'const a', offset: 6 }, { text: 'const a', offset: 7 }))).toBe('a')
    // 빈 선택은 범위가 없다
    expect(await selectedSource(page, { text: '스케줄링', offset: 2 }, { text: '스케줄링', offset: 2 })).toBeNull()
    // 서로 다른 요소에 걸친 선택(제목 끝~본문 처음)
    expect(slice(await selectedSource(page, { text: '스케줄링', offset: 0 }, { text: '😀', offset: 2 }))).toBe('스케줄링**\n\n😀')
  })

  test('이스케이프·엔티티는 덩어리 경계로 밀어낸다', async ({ page }) => {
    const slice = (r: { start: number; end: number } | null) => (r ? RICH_BODY.slice(r.start, r.end) : null)
    // 화면 글자 `*별표`는 원문 `\*별표`다(이스케이프의 백슬래시까지 포함)
    expect(slice(await selectedSource(page, { text: '*', offset: 0 }, { text: '별표', offset: 2 }))).toBe('\\*별표')
    expect(slice(await selectedSource(page, { text: '별표', offset: 0 }, { text: '별표', offset: 2 }))).toBe('별표')
    // 엔티티 `&`는 원문 `&amp;` 전체로 밀어낸다
    expect(slice(await selectedSource(page, { text: '&', offset: 0 }, { text: '&', offset: 1 }))).toBe('&amp;')
  })
})
