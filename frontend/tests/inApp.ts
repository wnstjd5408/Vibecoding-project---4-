import type { Page } from '@playwright/test'

// 새로 고치지 않고 앱 안에서 경로를 옮긴다. 가짜 로그인 상태는 메모리에만 있어 새로 고치면 사라지기 때문이다.
// 임시 화면의 이동 링크(DevNav)에 기대지 않으려고 쓴다. 화면이 실제로 만들어지면 DevNav가 사라진다.
export async function goInApp(page: Page, path: string) {
  await page.evaluate((to) => {
    history.pushState({}, '', to)
    dispatchEvent(new PopStateEvent('popstate'))
  }, path)
}
