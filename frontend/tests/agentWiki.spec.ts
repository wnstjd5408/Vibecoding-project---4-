import { expect, test } from '@playwright/test'
import { MOBILE, PC, SELECTED, answeredFromWiki, conversationBodies, input, login, mockWiki, panelOf, revokeSources, selectText, send, sheetOf, shot, wikiBuild } from './agentWikiSupport.ts'

// MEG-254 위키 출처 보기와 위키 질문 입구(T4e). 가짜 API(src/api/mocks/agent.ts)가 서버의 위키 플래그와 위키 근거를 흉내 낸다. 모델은 부르지 않는다.
// 이 파일은 두 빌드에서 돈다(playwright.config.ts): agent-wiki(4187, 화면 위키 플래그 켬)와 agent-enabled(4185, 끔).
// 플래그를 켠 빌드에서만 뜻이 있는 시험은 agentWikiFlagOn.spec.ts에 있다(CI는 건너뛴 시험을 실패로 본다).
// 결정(사용자 2026-11-23, MEG-254 댓글): 위키 출처의 '용어 시트 열기'로 연 시트에만 'AI에게 질문'을 두고 플래그를 따른다.
// 노트 강조에서 연 시트에는 버튼이 없고, 노트 선택 'AI에게 질문'은 플래그와 관계없이 origin note다(2026-11-19 결정, T3c 퀴즈 자료 경로).

for (const [device, viewport] of [['PC', PC], ['모바일', MOBILE]] as const) {
  test(`${device}: 위키 출처 보기(F6-4 위키) → 용어 시트 열기 → 플래그에 따른 'AI에게 질문'`, async ({ page }, testInfo) => {
    await login(page, viewport)
    const panel = await answeredFromWiki(page)
    await panel.getByRole('button', { name: '[1] ExampleTerm · 정의' }).click()
    const source = page.getByRole('dialog', { name: '출처 1' })
    await expect(source).toBeVisible()
    // 인용 당시 문단과 '용어 시트 열기'(AC-3). PC는 노트 자리, 모바일은 출처 화면에 있다.
    const doc = device === 'PC' ? page.getByRole('article', { name: '출처 1' }) : source
    await expect(doc.getByText('합성 위키 문단 하나입니다. 인용 당시의 합성 문단 원문입니다.')).toBeVisible()
    await expect(doc.getByRole('heading', { name: '정의' })).toBeVisible()
    if (device === 'PC') {
      await expect(doc.getByText('내부 위키')).toBeVisible()
      await expect(source.getByText('왼쪽 위키에서 인용된 문단을 표시했어요. 질문할 때 선택한 노트 문장은 질문 문맥으로만 쓰였어요.')).toBeVisible()
    }
    await expect(doc.getByText('인용한 뒤 위키 문단이 바뀌었어요.', { exact: false })).toHaveCount(0)
    await shot(page, testInfo, `${device}-F6-4-wiki-source`)

    await doc.getByRole('button', { name: '용어 시트 열기' }).click()
    // 대화 패널을 닫고 그 용어 시트(E06)를 연다(결정 4)
    await expect(panelOf(page)).toHaveCount(0)
    await expect(source).toHaveCount(0)
    const sheet = sheetOf(page)
    await expect(sheet).toBeVisible()
    await expect(sheet.getByText('합성 설명 문장입니다.')).toBeVisible()
    const ask = sheet.getByRole('button', { name: 'AI에게 질문' })
    if (!wikiBuild()) {
      // 플래그가 꺼져 있으면 버튼이 없다(AC-2 끔)
      await expect(ask).toHaveCount(0)
      await shot(page, testInfo, `${device}-term-sheet-flag-off`)
      expect((await conversationBodies(page)).map((body) => body.origin)).toEqual(['note'])
      return
    }
    await expect(ask).toBeVisible()
    await shot(page, testInfo, `${device}-term-sheet-flag-on`)
    await ask.click()
    // E27 origin wiki, wiki_ref glossary:{term_id}(AC-2 켬)
    await expect(panelOf(page)).toBeVisible()
    expect((await conversationBodies(page)).at(-1)).toEqual({ origin: 'wiki', wiki_ref: 'glossary:7' })
    await expect(sheet).toHaveCount(0)
    const wikiPanel = panelOf(page)
    // 현재 주제는 용어 제목이고 노트 선택 문맥 표시가 없다
    await expect(wikiPanel.getByText('현재 주제: ExampleTerm')).toBeVisible()
    await expect(wikiPanel.getByText('참고 문맥', { exact: false })).toHaveCount(0)
    await expect(wikiPanel.getByRole('button', { name: '선택 내용 보기' })).toHaveCount(0)
    await input(wikiPanel).fill('멱등성과 무슨 관계야?')
    await send(wikiPanel).click()
    await expect(wikiPanel.getByText('위키에서 자료 찾기').first()).toBeVisible({ timeout: 10_000 })
    await expect(wikiPanel.getByRole('button', { name: '[1] ExampleTerm · 정의' })).toBeVisible({ timeout: 10_000 })
    await shot(page, testInfo, `${device}-wiki-conversation`)
  })
}

test('PC: 인용 뒤 위키 문단이 바뀌면 노트 출처와 같은 규칙으로 안내한다', async ({ page }, testInfo) => {
  await login(page)
  const panel = await answeredFromWiki(page)
  await mockWiki(page, { changed: true })
  await panel.getByRole('button', { name: '[1] ExampleTerm · 정의' }).click()
  const doc = page.getByRole('article', { name: '출처 1' })
  await expect(doc.getByText('인용한 뒤 위키 문단이 바뀌었어요. 인용할 때의 문단을 보여 드려요.')).toBeVisible()
  await expect(doc.getByText('합성 위키 문단 하나입니다. 인용 당시의 합성 문단 원문입니다.')).toBeVisible()
  await shot(page, testInfo, 'PC-wiki-source-changed')
})

test('모바일: 인용 뒤 위키 문단이 바뀐 안내', async ({ page }) => {
  await login(page, MOBILE)
  const panel = await answeredFromWiki(page)
  await mockWiki(page, { changed: true })
  await panel.getByRole('button', { name: '[1] ExampleTerm · 정의' }).click()
  await expect(page.getByRole('dialog', { name: '출처 1' }).getByText('인용한 뒤 위키 문단이 바뀌었어요. 인용할 때의 문단을 보여 드려요.')).toBeVisible()
})

test('PC: 위키 출처가 404면 노트 출처와 같이 출처 보기를 닫고 가린 턴을 보인다(AC-3)', async ({ page }) => {
  await login(page)
  const panel = await answeredFromWiki(page)
  await revokeSources(page)
  await panel.getByRole('button', { name: '[1] ExampleTerm · 정의' }).click()
  await expect(panel.getByRole('status').filter({ hasText: '이 답변에 쓴 자료를 더 이상 볼 수 없어요.' })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('dialog', { name: '출처 1' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '용어 시트 열기' })).toHaveCount(0)
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
})

test('노트 출처에는 용어 시트 열기가 없고, 바뀜 안내는 노트 문구다', async ({ page }) => {
  await login(page)
  await mockWiki(page, { changed: true })
  await selectText(page, SELECTED)
  await page.getByRole('button', { name: 'AI에게 질문', exact: true }).click()
  const panel = panelOf(page)
  await input(panel).fill('이게 뭐야?')
  await send(panel).click()
  await panel.getByRole('button', { name: /^\[1\] 노트/ }).click({ timeout: 10_000 })
  const doc = page.getByRole('article', { name: '출처 1' })
  await expect(doc.getByText('인용한 뒤 노트가 바뀌었어요. 인용할 때의 문단을 보여 드려요.')).toBeVisible()
  await expect(page.getByRole('button', { name: '용어 시트 열기' })).toHaveCount(0)
})

test('노트 강조에서 연 용어 시트에는 플래그와 관계없이 AI에게 질문이 없다', async ({ page }) => {
  await login(page, MOBILE)
  await page.getByRole('link', { name: 'ExampleTerm' }).first().click()
  const sheet = sheetOf(page)
  await expect(sheet.getByText('합성 설명 문장입니다.')).toBeVisible()
  await expect(sheet.getByRole('button', { name: 'AI에게 질문' })).toHaveCount(0)
})

test('노트 선택 AI에게 질문은 플래그와 관계없이 origin note와 용어 하나다(AC-4, T3c 퀴즈 자료 경로)', async ({ page }) => {
  await login(page)
  await selectText(page, 'ExampleTerm')
  await page.getByRole('button', { name: 'AI에게 질문', exact: true }).click()
  const panel = panelOf(page)
  await input(panel).fill('이 용어가 뭐야?')
  await send(panel).click()
  await expect(panel.getByRole('button', { name: /^\[1\]/ }).first()).toBeVisible({ timeout: 10_000 })
  const [body] = await conversationBodies(page)
  expect(body.origin).toBe('note')
  expect(body.note_id).toBe(11)
  expect(body.wiki_ref).toBeUndefined()
  // 고른 글이 강조 용어 하나와 정확히 겹친다(가짜 E05 glossary_spans의 위치)
  const spans = await page.evaluate(async () => {
    const m = await import(/* @vite-ignore */ '/src/api/mocks/handlers.ts')
    return (m.handleMock({ method: 'GET', path: '/api/notes/11', query: new URLSearchParams(), body: undefined }).body as any).glossary_spans
  })
  expect(spans).toContainEqual({ term_id: 7, ...body.selection })
})
