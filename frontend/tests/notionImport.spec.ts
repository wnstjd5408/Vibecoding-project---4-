import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

// MEG-142: 실제 가져오기 변환기(convert) 출력을 실제 노트 렌더러로 읽어 물결표와 줄바꿈 인라인 코드를 확인한다.
// 변환 → 화면 구간만 확인하며, 저장(DB)·E05 응답은 합성 응답으로 대체한다.
const PAGE = '00000000-0000-4000-8000-000000000001'
const TABLE = '00000000-0000-4000-8000-000000000002'

function t(content: string, annotations: Record<string, boolean> = {}) {
  return { plain_text: content, annotations }
}
function paragraph(n: number, ...items: unknown[]) {
  return { id: `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`, type: 'paragraph', paragraph: { rich_text: items } }
}

const tree = {
  [PAGE]: [
    paragraph(10, t('~~~ 글 ~~~')),
    paragraph(11, t('범위 1~3일 또는 5~10일, ~ 하나')),
    paragraph(12, t('앞 '), t('코드\n\n빈 줄', { code: true }), t(' 뒤 한 줄')),
    paragraph(13, t('경로는 ~/home 입니다')),
    paragraph(14, t('끝 문단 마커')),
    { id: TABLE, type: 'table', table: { table_width: 2, has_column_header: true } },
  ],
  [TABLE]: [
    { table_row: { cells: [[t('머리1')], [t('머리2')]] } },
    { table_row: { cells: [[t('줄\n바꿈', { code: true })], [t('보통 글')]] } },
  ],
}

function importedBody() {
  const backend = fileURLToPath(new URL('../../backend/', import.meta.url))
  return execFileSync('uv', ['run', '--no-sync', '--directory', backend, 'python', '-c',
    `import json,sys; from types import SimpleNamespace; from scripts.notion_content import convert; tree=json.load(sys.stdin); print(convert(SimpleNamespace(children=lambda key: tree[key]), "${PAGE}").markdown)`],
  { input: JSON.stringify(tree), encoding: 'utf8' }).replace(/\r?\n$/, '')
}

for (const width of [390, 1280]) {
  test(`가져온 물결표와 줄바꿈 인라인 코드를 글자대로 표시한다 (${width}px)`, async ({ page }) => {
    const body = importedBody()
    const start = [...body.slice(0, body.indexOf('\\~/home'))].length
    const end = start + [...'\\~/home'].length
    await page.setViewportSize({ width, height: 844 })
    await page.route('**/api/me', (route) => route.fulfill({ json: { authenticated: false } }))
    await page.route('**/api/notes/21', (route) => route.fulfill({ json: {
      id: 21, revision: 1, title: 'Imported tilde note', studied_on: null, subjects: [], sources: [],
      body_markdown: body, images: {}, glossary_terms: [],
      glossary_spans: [{ start, end, term_id: 5 }],
    } }))
    await page.goto('/notes/21')
    const root = page.locator('[data-note-body]')
    // 문단 시작 "~~~"가 코드 블록으로 바뀌지 않고 글자로 보인다. 뒤 문단도 코드로 묻히지 않는다.
    await expect(root.locator('pre')).toHaveCount(0)
    await expect(root.getByText('~~~ 글 ~~~', { exact: true })).toBeVisible()
    await expect(root.getByText('범위 1~3일 또는 5~10일, ~ 하나', { exact: true })).toBeVisible()
    await expect(root.getByText('끝 문단 마커', { exact: true })).toBeVisible()
    // 빈 줄이 있던 인라인 코드가 문단을 쪼개거나 백틱을 글자로 노출하지 않는다.
    await expect(root.locator('code').filter({ hasText: '코드' })).toHaveText('코드  빈 줄')
    await expect(root.getByText('뒤 한 줄')).toBeVisible()
    await expect(root.getByText('`', { exact: false })).toHaveCount(0)
    // 표 셀: 코드 안에 <br> 글자가 노출되지 않는다. (일반 글 셀의 줄바꿈은 이 시험 범위 밖이다.)
    await expect(root.getByRole('cell')).toHaveText(['줄 바꿈', '보통 글'])
    await expect(root.locator('td code')).toHaveText('줄 바꿈')
    await expect(root.getByText('<br>')).toHaveCount(0)
    // 물결표 포함 용어: 링크와 선택 위치가 원문 구간과 맞는다.
    // 이스케이프(\~)가 든 용어는 기존 A\*처럼 이스케이프 경계에서 이웃한 링크 둘로 그려진다(위치는 모두 맞다).
    const terms = root.locator('[data-term-id="5"]')
    expect((await terms.allTextContents()).join('')).toBe('~/home')
    await expect(terms.first()).toHaveAttribute('href', '#term-5')
    const range = await root.evaluate(async (element) => {
      const { sourceRangeOfSelection } = await import('/src/notes/selection.ts')
      const links = element.querySelectorAll('[data-term-id="5"]')
      const selection = document.createRange()
      selection.setStartBefore(links[0])
      selection.setEndAfter(links[links.length - 1])
      return sourceRangeOfSelection(element, selection)
    })
    expect(range && body.slice(range.start, range.end)).toBe('\\~/home')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
}
