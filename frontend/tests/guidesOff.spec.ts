import { expect, test } from '@playwright/test'

// MEG-289 가이드 플래그를 끈 빌드(agent-disabled, 4183). 시험용 목록(VITE_GUIDES_E2E)은 켜 두어,
// 노트 11에 연결된 가이드가 목록에 있어도 플래그가 꺼지면 연결과 경로가 없다는 것을 본다(PRD v0.5 5.2절).

test('플래그가 꺼지면 연결된 노트에도 가이드 연결이 없다', async ({ page }) => {
  await page.goto('/notes/11')
  await expect(page.getByRole('heading', { level: 1, name: 'Example Note' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'ExampleTerm' })).toBeVisible()
  await expect(page.getByRole('link', { name: '가이드 열기' })).toHaveCount(0)
  await expect(page.getByText('단계별 가이드', { exact: true })).toHaveCount(0)
})

test('플래그가 꺼지면 /guides/* 경로가 없어 기존 없는 경로 화면이 보인다', async ({ page }) => {
  await page.goto('/guides/sample-handshake')
  await expect(page.getByRole('heading', { level: 1, name: '예시: 인사 주고받기' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '닫기' })).toHaveCount(0)
  await expect(page.getByRole('heading', { level: 1, name: '이 가이드는 지금 볼 수 없어요' })).toHaveCount(0)
  await expect(page.getByText('없는 경로').first()).toBeVisible()
})
