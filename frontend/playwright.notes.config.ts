import { defineConfig } from '@playwright/test'

// VITE_API_MOCK를 끄고 브라우저의 실제 fetch 경로를 합성 HTTP 응답으로 검증한다.
// 노트 선택 버튼의 AI 설명(E09) 시험이 있어 노출 중단 플래그를 켠 빌드로 띄운다(MEG-259, playwright.config.ts의 agent-disabled와 같다).
export default defineConfig({
  forbidOnly: Boolean(process.env.CI),
  testDir: './tests', testMatch: ['notes.spec.ts', 'notionImport.spec.ts', 'quizFlow.spec.ts', 'agentTransport.spec.ts'], fullyParallel: true, workers: 2, retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report-notes' }]],
  use: { baseURL: 'http://127.0.0.1:4184', browserName: 'chromium', viewport: { width: 390, height: 844 }, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4184 --strictPort',
    url: 'http://127.0.0.1:4184', env: { VITE_API_MOCK: 'false', VITE_CS_AGENT_DISABLED: '1' }, reuseExistingServer: false,
  },
})
