import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './tests', testMatch: 'quizFlow.spec.ts', fullyParallel: true, workers: 2,
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:4186', browserName: 'chromium', viewport: { width: 390, height: 844 }, screenshot: 'only-on-failure' },
  webServer: { command: 'npm run dev -- --host 127.0.0.1 --port 4186 --strictPort', url: 'http://127.0.0.1:4186', env: { VITE_API_MOCK: 'false' }, reuseExistingServer: false },
})
