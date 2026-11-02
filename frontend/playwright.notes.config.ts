import { defineConfig } from '@playwright/test'

// VITE_API_MOCK를 끄고 브라우저의 실제 fetch 경로를 합성 HTTP 응답으로 검증한다.
export default defineConfig({
  testDir: './tests', testMatch: 'notes.spec.ts', fullyParallel: true, workers: 2, retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report-notes' }]],
  use: { baseURL: 'http://127.0.0.1:4184', browserName: 'chromium', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4184 --strictPort',
    url: 'http://127.0.0.1:4184', env: { VITE_API_MOCK: 'false' }, reuseExistingServer: false,
  },
})
