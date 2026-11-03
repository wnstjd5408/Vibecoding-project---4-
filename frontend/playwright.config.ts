import { defineConfig } from '@playwright/test'

export default defineConfig({
  forbidOnly: Boolean(process.env.CI),
  testDir: './tests',
  testIgnore: ['notes.spec.ts', 'quizFlow.spec.ts'],
  fullyParallel: true,
  workers: 2,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: { baseURL: 'http://127.0.0.1:4183', browserName: 'chromium', viewport: { width: 390, height: 844 }, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4183 --strictPort',
    url: 'http://127.0.0.1:4183/dev/mockup',
    env: { VITE_API_MOCK: 'true' },
    reuseExistingServer: false,
  },
})
