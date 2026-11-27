import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// MEG-289 단계별 지도 가이드(PRD v0.5 AC-1~AC-6, AC-8~AC-11). guides 프로젝트(4189)에서만 돈다.
// 그 서버는 가이드 플래그(VITE_GUIDES_ENABLED)를 켜고 시험용 목록(VITE_GUIDES_E2E, src/guides/fixtures/e2e)을 쓴다.
//  - sample-handshake: 노트 11에 연결된 합성 예시(3단계: 준비 → 인사 → 답)
//  - sample-orphan: 없는 노트(404)에 연결된 합성 예시
// 실제 노트 본문이나 검수 전 초안은 쓰지 않는다.

const GUIDE = '/guides/sample-handshake'
const TITLE = '예시: 인사 주고받기'
const STEPS = ['아직 아무것도 오가지 않았어요', '클라이언트가 인사를 보내요', '서버가 답하고 클라이언트가 확인해요']
// 개발 서버가 가이드 파일을 내주는 요청. 불러오기 실패(AC-10)를 만들 때 막는다.
const GUIDE_FILE = '**/sample-handshake.json*'

const stepHeading = (page: Page, n: number) => page.getByRole('heading', { level: 2, name: STEPS[n] })
const map = (page: Page) => page.getByRole('img', { name: /단계 지도:/ })
const nextButton = (page: Page) => page.getByRole('button', { name: '다음', exact: true })
const prevButton = (page: Page) => page.getByRole('button', { name: '이전', exact: true })
const currentChip = (page: Page) => page.getByRole('group', { name: '단계 고르기' }).locator('[aria-current="step"]')
const guideLink = (page: Page) => page.getByRole('link', { name: '가이드 열기' })

async function openFromNote(page: Page) {
  await page.goto('/notes/11')
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
  await guideLink(page).click()
  await expect(page).toHaveURL(new RegExp(`${GUIDE}$`))
  await expect(stepHeading(page, 0)).toBeVisible()
}

// 지도와 글이 같은 단계를 가리키는지 본다. 지도 이름은 「n단계 지도: …」다.
// 예시는 전체 흐름을 마지막 단계에 둔다(sequence.placement: last_step). 그 단계의 그림은 시퀀스 다이어그램이다.
const LAST = STEPS.length - 1
const sequence = (page: Page) => page.getByRole('img', { name: `${TITLE} 전체 흐름 시퀀스 다이어그램`, exact: false })
async function expectStep(page: Page, n: number) {
  await expect(stepHeading(page, n)).toBeVisible()
  await expect(currentChip(page)).toHaveCount(1)
  await expect(currentChip(page)).toHaveText(new RegExp(`^${n + 1} `))
  if (n === LAST) await expect(sequence(page)).toBeVisible()
  else await expect(map(page)).toHaveAttribute('aria-label', new RegExp(`^${n + 1}단계 지도:`))
}

test.describe('AC-1 지도와 단계 이동', () => {
  test('다음·이전·단계 칩으로 이동하면 지도와 글이 같은 단계를 가리키고 첫·마지막에서 막힌다', async ({ page }) => {
    await page.goto(GUIDE)
    await expect(page.getByRole('heading', { level: 1, name: TITLE })).toBeVisible()
    await expectStep(page, 0)
    await expect(prevButton(page)).toBeDisabled()

    for (const n of [1, 2]) {
      await nextButton(page).click()
      await expectStep(page, n)
    }
    await expect(nextButton(page)).toBeDisabled()
    await expect(page.getByText('예시 가이드는 여기까지예요.')).toBeVisible()

    await prevButton(page).click()
    await expectStep(page, 1)
    // 떨어진 단계로 바로 가기
    await page.getByRole('group', { name: '단계 고르기' }).getByRole('button', { name: '1 준비' }).click()
    await expectStep(page, 0)
    await page.getByRole('group', { name: '단계 고르기' }).getByRole('button', { name: '3 답' }).click()
    await expectStep(page, 2)
  })
})

test('AC-2 지금 단계는 색 말고도 칩의 aria-current와 위치 글자로 구분된다', async ({ page }) => {
  await page.goto(GUIDE)
  await nextButton(page).click()
  await expectStep(page, 1)
  await expect(page.getByText(/2 \/ 3단계/).first()).toBeVisible()
  // 지도 이름에도 지금 단계 번호가 있다(색을 보지 않는 사용자용)
  await expect(map(page)).toHaveAttribute('aria-label', /^2단계 지도:/)
})

test.describe('AC-3 움직임 줄이기', () => {
  test('설정을 끄면 메시지가 움직이고 다시 보기 버튼이 있다', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto(GUIDE)
    await nextButton(page).click()
    await expectStep(page, 1)
    await expect(map(page).locator('animateMotion')).not.toHaveCount(0)
    await expect(page.getByRole('button', { name: '움직임 다시 보기' })).toBeVisible()
  })

  test('설정을 켜면 움직임 없이 같은 단계 정보가 보인다', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto(GUIDE)
    await nextButton(page).click()
    await expectStep(page, 1)
    await expect(map(page).locator('animate, animateMotion')).toHaveCount(0)
    await expect(page.getByRole('button', { name: '움직임 다시 보기' })).toHaveCount(0)
    // 누가 누구에게 무엇을 보내는지는 지도 이름과 글 상자에 그대로 있다
    await expect(map(page)).toHaveAttribute('aria-label', /클라이언트 → 서버\. 인사 · 번호 100/)
    await expect(page.getByText('전체 지도에서 따라가기')).toBeVisible()
  })
})

test('AC-4 키보드만으로 노트에서 들어가 모든 단계를 지나 닫고 돌아온다', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/notes/11')
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
  await guideLink(page).focus()
  await page.keyboard.press('Enter')
  await expect(stepHeading(page, 0)).toBeVisible()

  // 「다음」까지 Tab으로 간다. 포커스가 보이는지(2px 링) 함께 본다.
  for (let i = 0; i < 20 && !(await nextButton(page).evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press('Tab')
  await expect(nextButton(page)).toBeFocused()
  expect(await nextButton(page).evaluate((el) => getComputedStyle(el).outlineWidth)).toBe('2px')
  await page.keyboard.press('Enter')
  await expectStep(page, 1)
  await page.keyboard.press('Enter')
  await expectStep(page, 2)
  // 마지막 단계에서 「다음」이 막히면 포커스는 「이전」으로 옮겨 간다
  await expect(prevButton(page)).toBeFocused()

  // 닫기까지 Shift+Tab으로 거슬러 간다
  const close = page.getByRole('button', { name: '닫기' })
  for (let i = 0; i < 30 && !(await close.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press('Shift+Tab')
  await expect(close).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/notes\/11$/)
  await expect(guideLink(page)).toBeFocused()
})

test.describe('AC-5 지도를 그리지 못해도 글로 같은 내용을 읽고 빈 그림 자리가 없다', () => {
  // 지도 실패는 개발 미리보기의 failMap으로 만든다(제품 경로와 같은 GuidePage를 그린다).
  // 넓은 화면(지도 칸이 따로 있는 배치)과 좁은 화면을 모두 본다.
  for (const width of [390, 1280]) {
    test(`${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 })
      await page.goto('/dev/guide?slug=sample-handshake&failMap=1')
      await expect(page.getByRole('heading', { level: 2, name: STEPS[0] })).toBeVisible()
      await nextButton(page).click()
      await expect(page.getByRole('heading', { level: 2, name: STEPS[1] })).toBeVisible()
      await expect(page.getByRole('img', { name: /단계 지도:/ })).toHaveCount(0)
      await expect(page.getByRole('region', { name: '지도 칸' })).toHaveCount(0)
      await expect(page.getByRole('region', { name: /^지도/ })).toHaveCount(0)
      // 지도 대신 글 상자가 누가 누구에게 무엇을 보내는지 알려 준다
      await expect(page.getByText('이 단계에서 오가는 것')).toBeVisible()
      await expect(page.getByText('인사 · 번호 100').first()).toBeVisible()
      await expect(page.getByRole('heading', { level: 3, name: '무엇이 바뀌었나' })).toBeVisible()
    })
  }
})

test.describe('AC-6 화면 폭', () => {
  for (const width of [390, 1280]) {
    test(`${width}px에서 가로로 넘치지 않고 이동 버튼이 가려지지 않는다`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 })
      await page.goto(GUIDE)
      for (const n of [0, 1, 2]) {
        await expectStep(page, n)
        expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0)
        const target = n < 2 ? nextButton(page) : prevButton(page)
        await target.scrollIntoViewIfNeeded()
        // 버튼 가운데를 다른 요소가 덮고 있지 않다
        const covered = await target.evaluate((el) => {
          const r = el.getBoundingClientRect()
          const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
          return !(hit && (hit === el || el.contains(hit)))
        })
        expect(covered).toBe(false)
        if (n < 2) await nextButton(page).click()
      }
    })
  }

  test('1024px에서 지도 칸이 600px 이상이다', async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 800 })
    await page.goto(GUIDE)
    const column = page.getByRole('region', { name: '지도 칸' })
    await expect(column).toBeVisible()
    expect((await column.boundingBox())!.width).toBeGreaterThanOrEqual(600)
  })
})

test.describe('AC-8 노트에서 열고 닫기', () => {
  test('노트 본문 첫머리의 연결로 첫 단계가 열리고, 닫으면 읽던 위치로 돌아와 연결에 포커스가 간다', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 400 })
    await page.goto('/notes/11')
    await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
    await expect(page.getByText('단계별 가이드', { exact: true })).toBeVisible()
    await expect(guideLink(page)).toHaveAccessibleDescription(TITLE)
    // 연결은 본문보다 앞에 있다
    expect(await guideLink(page).evaluate((el) => {
      const body = document.querySelector('[data-note-body]')!
      return Boolean(el.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING)
    })).toBe(true)

    await page.evaluate(() => window.scrollTo(0, 80))
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(80)
    // Playwright의 click은 대상을 화면 안으로 굴려 위치가 바뀔 수 있다. 위치를 그대로 두고 누른다.
    await guideLink(page).evaluate((el: HTMLElement) => el.click())
    await expect(stepHeading(page, 0)).toBeVisible()

    await page.getByRole('button', { name: '닫기' }).click()
    await expect(page).toHaveURL(/\/notes\/11$/)
    await expect.poll(() => page.evaluate(() => Math.round(window.scrollY))).toBe(80)
    await expect(guideLink(page)).toBeFocused()
  })

  test('브라우저 뒤로 가기도 읽던 위치로 돌아온다', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 400 })
    await page.goto('/notes/11')
    await expect(guideLink(page)).toBeVisible()
    await page.evaluate(() => window.scrollTo(0, 80))
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(80)
    await guideLink(page).evaluate((el: HTMLElement) => el.click())
    await expect(stepHeading(page, 0)).toBeVisible()
    await page.goBack()
    await expect(page).toHaveURL(/\/notes\/11$/)
    await expect.poll(() => page.evaluate(() => Math.round(window.scrollY))).toBe(80)
  })

  test('주소로 바로 들어와 닫으면 연결된 노트의 처음으로 가고 기록을 늘리지 않는다', async ({ page }) => {
    await page.goto(GUIDE)
    await expect(stepHeading(page, 0)).toBeVisible()
    const before = await page.evaluate(() => history.length)
    await page.getByRole('button', { name: '닫기' }).click()
    await expect(page).toHaveURL(/\/notes\/11$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
    expect(await page.evaluate(() => history.length)).toBe(before)
    expect(await page.evaluate(() => window.scrollY)).toBe(0)
  })

  test('연결된 노트가 없으면(404) 닫을 때 노트 목록으로 간다', async ({ page }) => {
    await page.goto('/guides/sample-orphan')
    await expect(page.getByRole('heading', { level: 1, name: '예시: 노트가 사라진 가이드' })).toBeVisible()
    await page.getByRole('button', { name: '닫기' }).click()
    await expect(page).toHaveURL(/\/$/)
  })
})

test.describe('AC-9 공개 목록에 없는 가이드', () => {
  // sample-unlisted는 파일은 있지만 시험용 목록(fixtures/e2e/index.json)에 없다. 공개를 멈춘 가이드와 같은 상태다.
  for (const slug of ['sample-unlisted', 'no-such-guide']) {
    test(`${slug}: 제목과 내용 없이 볼 수 없다는 안내만 보이고 가이드 파일을 받지 않는다`, async ({ page }) => {
      const files: string[] = []
      page.on('request', (request) => {
        // 목록 파일(index.json)은 노트 화면 묶음에 들어 있어 늘 받는다. 가이드 파일 자체를 받는지만 본다.
        const url = request.url()
        if (/\/(content|fixtures)\/.+\.json/.test(url) && !url.includes('index.json')) files.push(url)
      })
      await page.goto(`/guides/${slug}`)
      await expect(page.getByRole('heading', { level: 1, name: '이 가이드는 지금 볼 수 없어요' })).toBeVisible()
      await expect(page.getByRole('link', { name: '노트 목록으로' })).toBeVisible()
      await expect(page.getByText('예시: 목록에 없는 가이드')).toHaveCount(0)
      await expect(page.getByRole('group', { name: '단계 고르기' })).toHaveCount(0)
      await expect(page.getByRole('img', { name: /단계 지도:/ })).toHaveCount(0)
      expect(files).toEqual([])
      await page.getByRole('link', { name: '노트 목록으로' }).click()
      await expect(page).toHaveURL(/\/$/)
    })
  }
})

test.describe('AC-10 가이드를 불러오지 못했을 때', () => {
  test('노트에서: 노트는 그대로이고 연결 자리에 오류와 다시 시도가 보이며, 다시 시도하면 열린다', async ({ page }) => {
    let blocked = false
    await page.route(GUIDE_FILE, (route) => {
      if (blocked) return route.continue()
      blocked = true
      return route.abort()
    })
    await page.goto('/notes/11')
    await guideLink(page).click()
    const alert = page.getByRole('alert').filter({ hasText: '가이드를 불러오지 못했어요' })
    await expect(alert).toBeVisible()
    await expect(page).toHaveURL(/\/notes\/11$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'ExampleTerm' })).toBeVisible()
    const retry = alert.getByRole('button', { name: '다시 시도' })
    await expect(retry).toBeVisible()

    // 다시 시도. 브라우저가 실패한 모듈을 기억하면 두 번째 실패에서 페이지를 새로 고친다(GuideLink). 어느 쪽이든 결국 열려야 한다.
    await retry.click()
    await expect
      .poll(async () => {
        if (new URL(page.url()).pathname === GUIDE) return true
        const again = page.getByRole('alert').getByRole('button', { name: '다시 시도' })
        if (await again.isVisible().catch(() => false)) await again.click({ timeout: 500 }).catch(() => {})
        else if (await guideLink(page).isVisible().catch(() => false)) await guideLink(page).click({ timeout: 500 }).catch(() => {})
        return false
      }, { timeout: 15_000 })
      .toBe(true)
    await expect(stepHeading(page, 0)).toBeVisible()
  })

  test('주소로 바로 들어와서: 닫기 막대와 오류, 다시 시도가 보이고, 다시 시도하면 열린다', async ({ page }) => {
    let blocked = false
    await page.route(GUIDE_FILE, (route) => {
      if (blocked) return route.continue()
      blocked = true
      return route.abort()
    })
    await page.goto(GUIDE)
    await expect(page.getByRole('heading', { name: '가이드를 불러오지 못했어요' })).toBeVisible()
    await expect(page.getByRole('button', { name: '닫기' })).toBeVisible()
    // 다시 시도를 누른 뒤 불러오는 동안에는 버튼이 없다. 보일 때만 짧게 누른다(없는 버튼을 기다리며 멈추지 않게).
    await expect
      .poll(async () => {
        if (await stepHeading(page, 0).isVisible().catch(() => false)) return true
        const retry = page.getByRole('button', { name: '다시 시도' })
        if (await retry.isVisible().catch(() => false)) await retry.click({ timeout: 500 }).catch(() => {})
        return false
      }, { timeout: 15_000 })
      .toBe(true)
  })
})

test('AC-11 가이드를 보는 동안 기록 요청을 보내지 않는다', async ({ page }) => {
  // 가짜 API를 거치지 않고 네트워크로 나가는 /api/ 요청도 함께 본다
  let guideOpen = false
  const network: string[] = []
  page.on('request', (request) => {
    if (guideOpen && new URL(request.url()).pathname.startsWith('/api/')) network.push(request.url())
  })
  await openFromNote(page)
  guideOpen = true
  // 기록 장치가 동작하는지 먼저 본다: 노트 화면은 E05를 불렀다
  expect(await page.evaluate(() => (globalThis as { __mockApiCalls?: string[] }).__mockApiCalls ?? [])).toContain('GET /api/notes/11')
  // 노트 화면에서 부른 요청은 빼고, 가이드 화면에 들어온 뒤의 요청만 본다
  await page.evaluate(() => {
    ;(globalThis as { __mockApiCalls?: string[] }).__mockApiCalls = []
  })
  for (const n of [1, 2]) {
    await nextButton(page).click()
    await expectStep(page, n)
  }
  await page.getByRole('group', { name: '단계 고르기' }).getByRole('button', { name: '1 준비' }).click()
  await expectStep(page, 0)
  const calls = await page.evaluate(() => (globalThis as { __mockApiCalls?: string[] }).__mockApiCalls ?? [])
  expect(calls).toEqual([])
  expect(network).toEqual([])
})
