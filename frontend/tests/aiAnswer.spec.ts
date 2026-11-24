import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// MEG-256 CS Agent 답변 AI 렌더링 모드. 컴포넌트 시험 도구를 더하지 않고(결정 요청 13 권장안),
// 개발 서버가 내보내는 시험 전용 화면(tests/harness/aiAnswerHarness.tsx)에 가짜 응답(E29 result 모양)을 넣어 그린다.
// 모델과 백엔드는 부르지 않는다. 바깥 주소(evil.example)로 나가는 요청은 막고 기록한다.

const SOURCES = [
  { ref: 1, source_kind: 'note', title: '프로세스와 스레드', section: '스케줄링', cited_revision: 3 },
  { ref: 2, source_kind: 'note', title: '메모리 관리', cited_revision: 1 },
]

type Fixture = { sections: { heading?: string; body: string }[]; figures?: unknown[]; sources?: unknown[]; steps?: string[] }

async function mount(page: Page, fixture: Fixture) {
  const outside: string[] = []
  await page.route(/evil\.example/, (route) => {
    outside.push(route.request().url())
    return route.abort()
  })
  await page.addInitScript(() => {
    // HTML이 실행되면 이 값이 바뀐다.
    (window as unknown as { __pwned: number }).__pwned = 0
  })
  await page.goto('/dev/foundation')
  await page.evaluate(async (data) => {
    const { mount } = await import('/tests/harness/aiAnswerHarness.tsx')
    mount(data as never)
  }, fixture)
  await expect(page.getByTestId('answer')).toBeVisible()
  return { outside }
}

const pwned = (page: Page) => page.evaluate(() => (window as unknown as { __pwned: number }).__pwned)

test('AI 모드는 링크·이미지·HTML을 실행하지 않고 글자로 보이며, 허용한 블록만 그린다 (AC-1)', async ({ page }) => {
  const body = [
    '## 소제목 [1]',
    '',
    '일반 문장 [1]과 출처에 없는 번호 [9], 두 출처 [1][2].',
    '',
    '[외부 링크](https://evil.example/link) · [스크립트](javascript:window.__pwned=1) · <https://evil.example/auto>',
    '',
    '![추적 그림](https://evil.example/track.png) ![노트 그림](note-image:abc)',
    '',
    '<img src="https://evil.example/html.png" onerror="window.__pwned=1">',
    '',
    '글 속 <b onclick="window.__pwned=1">굵게 아님</b> <script>window.__pwned=1</script>',
    '',
    '`코드 [1]` 와 **굵게** *기울임*',
    '',
    '```mermaid',
    'flowchart LR',
    '  A --> B',
    '```',
    '',
    '| 항목 | 출처 |',
    '| --- | --- |',
    '| 칸 | [2] |',
    '',
    '> 인용 블록',
    '',
    '---',
    '',
    '- 목록 하나',
    '1. 번호 목록',
  ].join('\n')
  const { outside } = await mount(page, { sections: [{ heading: '핵심', body }], sources: SOURCES })
  const answer = page.getByTestId('answer')

  // 링크는 글자만: <a>가 하나도 없다.
  await expect(answer.locator('a')).toHaveCount(0)
  await expect(answer).toContainText('외부 링크 · 스크립트 · https://evil.example/auto')
  // 이미지 문법은 대체 글만: <img>가 없고 주소를 부르지 않는다.
  await expect(answer.locator('img')).toHaveCount(0)
  await expect(answer).toContainText('추적 그림 노트 그림')
  // HTML은 글자 그대로
  await expect(answer).toContainText('<img src="https://evil.example/html.png" onerror="window.__pwned=1">')
  await expect(answer).toContainText('<b onclick="window.__pwned=1">굵게 아님</b>')
  await expect(answer).toContainText('<script>window.__pwned=1</script>')
  await expect(answer.locator('script, b, iframe, [onclick], [onerror]')).toHaveCount(0)
  // 본문의 mermaid 코드 블록은 코드로만 보이고 보기 방식 선택도 없다.
  await expect(answer.locator('pre code')).toHaveText('flowchart LR\n  A --> B')
  await expect(answer.getByRole('radiogroup')).toHaveCount(0)
  // 용어 링크·노트 본문 표시·원문 위치 속성이 없다.
  await expect(answer.locator('[data-note-body], [data-term-id], [data-src], [data-src-end], [data-src-unmapped]')).toHaveCount(0)
  // 허용 블록
  await expect(answer.locator('h3')).toHaveText('핵심')
  // 본문 제목은 절 제목(h3) 아래 단계로 낮춘다(## → h5).
  await expect(answer.locator('h5')).toContainText('소제목')
  await expect(answer.locator('strong')).toHaveText('굵게')
  await expect(answer.locator('em')).toHaveText('기울임')
  await expect(answer.locator('table td').nth(1)).toHaveText('[2]')
  await expect(answer.locator('blockquote')).toHaveText('인용 블록')
  await expect(answer.locator('hr')).toHaveCount(1)
  await expect(answer.locator('ul li')).toHaveText('목록 하나')
  await expect(answer.locator('ol li')).toHaveText('번호 목록')

  // 인용: sources[]에 있는 번호만 버튼이고, 코드 안의 [1]과 없는 번호 [9]는 글자로 남는다.
  const cite1 = answer.getByRole('button', { name: '출처 1 보기: 프로세스와 스레드' })
  await expect(cite1).toHaveCount(3) // 소제목, 일반 문장, [1][2]의 [1]
  await expect(answer.getByRole('button', { name: '출처 2 보기: 메모리 관리' })).toHaveCount(2) // [1][2]의 [2], 표
  await expect(answer.locator('code').first()).toHaveText('코드 [1]')
  await expect(answer).toContainText('출처에 없는 번호 [9]')
  await expect(answer.getByRole('button', { name: /출처 9/ })).toHaveCount(0)
  await cite1.nth(1).click()
  await answer.getByRole('button', { name: '출처 2 보기: 메모리 관리' }).first().click()
  expect(await page.evaluate(() => window.__sourceClicks)).toEqual([1, 2])

  expect(await pwned(page)).toBe(0)
  expect(outside).toEqual([])
})

test('본문에 링크 정의가 있어도 [n]을 링크로 만들지 않고 정의 줄도 글자로 남긴다', async ({ page }) => {
  const { outside } = await mount(page, {
    sections: [{ body: '정의가 있는 인용 [1] 과 [글자][2]\n\n[1]: https://evil.example/def\n[2]: javascript:window.__pwned=1' }],
    sources: SOURCES,
  })
  const answer = page.getByTestId('answer')
  await expect(answer.locator('a')).toHaveCount(0)
  await expect(answer.getByRole('button', { name: '출처 1 보기: 프로세스와 스레드' })).toHaveCount(2) // 본문 [1], 정의 줄의 [1]
  await expect(answer).toContainText('[글자]')
  await expect(answer).toContainText(': https://evil.example/def')
  await expect(answer).toContainText(': javascript:window.__pwned=1')
  expect(await pwned(page)).toBe(0)
  expect(outside).toEqual([])
})

const FLOW = 'flowchart LR\n  A[요청] --> B[응답]'

test('그림은 after_section 절 바로 아래에 strict로 그리고, 실패한 그림만 실패 카드로 바꾼다 (AC-2)', async ({ page }) => {
  const { outside } = await mount(page, {
    steps: ['노트 문단 2개를 확인했어요', '답을 정리하고 있어요'],
    sections: [{ heading: '핵심', body: '요청과 응답 [1]' }, { heading: '조건', body: '조건 설명 [2]' }],
    figures: [
      { figure_id: 'f-1', kind: 'diagram', mermaid: FLOW, caption: '요청 흐름', alt_text: '요청이 응답으로 이어진다', source_refs: [1], after_section: 1 },
      { figure_id: 'f-2', kind: 'diagram', mermaid: 'flowchart LR\n  A[[[ -->', caption: '깨진 그림', alt_text: '문법이 틀린 그림의 설명', source_refs: [2], after_section: 2 },
      // 노트 근거 기간에는 오지 않는 종류. 주소를 부르지 않고 실패 카드로 보이며, 범위 밖 절 번호라 마지막 절 아래에 둔다.
      { figure_id: 'f-3', kind: 'image', image: { url: 'https://evil.example/figure.png' }, caption: '이미지 그림', alt_text: '이미지 설명', source_refs: [1], after_section: 99 },
      // 서버가 막는 click 지시문이 와도 그림은 <img> 데이터 주소라 실행되지 않는다.
      { figure_id: 'f-4', kind: 'diagram', mermaid: 'flowchart LR\n  A --> B\n  click A "javascript:window.__pwned=1"', caption: '클릭 그림', alt_text: '클릭 설명', source_refs: [1], after_section: 1 },
      // 라벨 속 HTML도 strict 설정이 글자로 바꿔, 그리는 동안 바깥 주소를 부르지 않는다.
      { figure_id: 'f-5', kind: 'diagram', mermaid: 'flowchart LR\n  A["<img src=https://evil.example/label.png onerror=window.__pwned=1>"] --> B', caption: '라벨 그림', alt_text: '라벨 설명', source_refs: [1], after_section: 2 },
      // 객체가 아닌 항목은 빼고 나머지를 그린다(답변 전체가 깨지지 않는다).
      null,
    ],
    sources: SOURCES,
  })
  const answer = page.getByTestId('answer')

  // 정상 그림: 데이터 주소 <img>, 대체 글, 캡션과 출처 버튼
  const first = answer.locator('[data-figure-id="f-1"]')
  const img = first.locator('img')
  await expect(img).toHaveAttribute('src', /^data:image\/svg\+xml/)
  await expect(img).toHaveAttribute('alt', '요청이 응답으로 이어진다')
  await expect.poll(() => img.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0)
  await expect(first.locator('figcaption')).toHaveText('요청 흐름노트 문단 [1]')
  await expect(first.getByRole('group', { name: '요청 흐름' })).toHaveAttribute('tabindex', '0')
  await first.getByRole('button', { name: '출처 1 보기: 프로세스와 스레드' }).click()
  expect(await page.evaluate(() => window.__sourceClicks)).toEqual([1])

  // 위치: f-1·f-4는 1절 다음·2절 앞, f-2·f-3·f-5는 2절 다음(f-3은 범위 밖 절 번호라 마지막 절 아래). 같은 절 아래에서는 배열 순서를 따른다.
  await expect.poll(async () => await answer.locator('[data-figure-id="f-5"] img').count() + await answer.locator('[data-figure-id="f-5"][data-figure-failed]').count()).toBe(1)
  const order = await answer.locator('section, [data-figure-id]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-figure-id') ?? node.querySelector('h3')?.textContent))
  expect(order).toEqual(['핵심', 'f-1', 'f-4', '조건', 'f-2', 'f-3', 'f-5'])

  // 실패 그림: 실패 카드에 캡션과 그림 설명이 글로 남는다. '다시 그리기'는 없다.
  const broken = answer.locator('[data-figure-id="f-2"]')
  await expect(broken).toHaveAttribute('data-figure-failed', '')
  await expect(broken).toContainText('오류: 그림을 표시하지 못했어요')
  await expect(broken).toContainText('깨진 그림노트 문단 [2]')
  await expect(broken).toContainText('그림 설명: 문법이 틀린 그림의 설명')
  // 실패 카드에도 캡션의 출처 버튼은 남고, '다시 그리기' 버튼은 없다.
  await expect(broken.getByRole('button')).toHaveCount(1)
  await expect(broken.getByRole('button', { name: '출처 2 보기: 메모리 관리' })).toBeVisible()
  await expect(broken.getByRole('button', { name: /다시/ })).toHaveCount(0)
  await expect(answer.locator('[data-figure-id="f-3"]')).toContainText('그림 설명: 이미지 설명')
  await expect(answer.locator('[data-figure-id="f-3"] img')).toHaveCount(0)

  // click 지시문이 있는 그림: strict 설정이라 javascript: 주소가 그림(SVG)에 남지 않는다. 그리지 못하면 실패 카드다.
  const clicked = answer.locator('[data-figure-id="f-4"]')
  await expect.poll(async () => await clicked.locator('img').count() + (await clicked.getAttribute('data-figure-failed') === null ? 0 : 1)).toBe(1)
  const svg = await clicked.locator('img').evaluateAll((nodes) => nodes.map((node) => decodeURIComponent((node as HTMLImageElement).src)))
  for (const text of svg) expect(text).not.toMatch(/javascript:/i)

  // 본문과 단계 글은 그대로 남는다.
  await expect(answer).toContainText('요청과 응답 [1]')
  await expect(answer).toContainText('조건 설명 [2]')
  await expect(page.getByTestId('steps')).toHaveText('노트 문단 2개를 확인했어요답을 정리하고 있어요')
  expect(await pwned(page)).toBe(0)
  expect(outside).toEqual([])
})

test('mermaid를 불러오지 못해도 본문과 단계 글은 남고 그림만 실패 카드가 된다 (AC-2)', async ({ page }) => {
  // 지연 로드하는 mermaid 모듈만 막는다(src/notes/mermaid.ts는 막지 않는다).
  await page.route(/\/node_modules\/\.vite\/deps\/mermaid\.js/, (route) => route.abort())
  await mount(page, {
    steps: ['노트 문단 1개를 확인했어요'],
    sections: [{ body: '본문은 남아요 [1]' }],
    figures: [{ figure_id: 'f-1', kind: 'diagram', mermaid: FLOW, caption: '요청 흐름', alt_text: '요청이 응답으로 이어진다', source_refs: [1], after_section: 1 }],
    sources: SOURCES,
  })
  const answer = page.getByTestId('answer')
  await expect(answer.locator('[data-figure-id="f-1"]')).toContainText('오류: 그림을 표시하지 못했어요')
  await expect(answer).toContainText('본문은 남아요 [1]')
  await expect(page.getByTestId('steps')).toHaveText('노트 문단 1개를 확인했어요')
})

test('그림 값이 깨져 그리다 오류가 나도 그 그림만 실패 카드가 되고 나머지는 남는다 (AC-2)', async ({ page }) => {
  await mount(page, {
    steps: ['노트 문단 1개를 확인했어요'],
    sections: [{ body: '앞 절 [1]' }, { body: '뒤 절 [1]' }],
    // 캡션이 글자가 아니면 React가 그리다 오류를 낸다. 경계가 그 그림만 실패 카드로 바꾼다.
    figures: [{ figure_id: 'f-1', kind: 'diagram', mermaid: FLOW, caption: { bad: true }, alt_text: '설명', source_refs: [1], after_section: 1 }],
    sources: SOURCES,
  })
  const answer = page.getByTestId('answer')
  await expect(answer.locator('[data-figure-id="f-1"]')).toContainText('오류: 그림을 표시하지 못했어요')
  await expect(answer).toContainText('앞 절 [1]')
  await expect(answer).toContainText('뒤 절 [1]')
  await expect(page.getByTestId('steps')).toHaveText('노트 문단 1개를 확인했어요')
})

test('숫자 하나만 있는 링크 [1](주소)는 <a> 없이 인용 버튼이 된다', async ({ page }) => {
  const { outside } = await mount(page, { sections: [{ body: '근거 [1](https://evil.example/cite) 와 [설명](https://evil.example/x) 끝' }], sources: SOURCES })
  const answer = page.getByTestId('answer')
  await expect(answer.locator('a')).toHaveCount(0)
  await expect(answer.getByRole('button', { name: '출처 1 보기: 프로세스와 스레드' })).toHaveCount(1)
  await expect(answer).toHaveText('근거 [1] 와 설명 끝')
  expect(outside).toEqual([])
})

test('같은 자리에 다음 답변이 오면 앞 답변의 그림 실패 표시를 풀고 새 그림을 그린다', async ({ page }) => {
  const broken = { figure_id: 'f-1', kind: 'diagram', mermaid: FLOW, caption: { bad: true }, alt_text: '설명', source_refs: [1], after_section: 1 }
  await mount(page, { sections: [{ body: '첫 답 [1]' }], figures: [broken], sources: SOURCES })
  const answer = page.getByTestId('answer')
  await expect(answer.locator('[data-figure-id="f-1"]')).toContainText('오류: 그림을 표시하지 못했어요')
  await page.evaluate(async (data) => {
    const { mount } = await import('/tests/harness/aiAnswerHarness.tsx')
    mount(data as never)
  }, { sections: [{ body: '다음 답 [1]' }], figures: [{ ...broken, caption: '다음 그림' }], sources: SOURCES })
  await expect(answer).toContainText('다음 답 [1]')
  await expect(answer.locator('[data-figure-id="f-1"] img')).toHaveAttribute('src', /^data:image\/svg\+xml/)
  await expect(answer.locator('[data-figure-failed]')).toHaveCount(0)
})
