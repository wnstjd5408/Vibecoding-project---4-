import { defineConfig } from '@playwright/test'

// 로컬 실제 백엔드·DB·Auth에 붙는 퀴즈 e2e (MEG-207). Bedrock은 시험용 가짜다.
// 먼저 backend에서 `uv run python -m scripts.local_backend start`와 `fixture`를 실행해 로컬 Supabase를 준비한다.
// 합성 퀴즈 세트는 시험 직전에 시험이 직접 넣는다(tests-local/quizLocal.spec.ts).
const WEB = 'http://127.0.0.1:4187'
const API = 'http://127.0.0.1:8187'

export default defineConfig({
  testDir: './tests-local', fullyParallel: false, workers: 1, retries: 0, reporter: 'list',
  use: { baseURL: WEB, browserName: 'chromium', viewport: { width: 390, height: 844 }, screenshot: 'only-on-failure' },
  webServer: [
    {
      command: `uv run --frozen python -m scripts.local_quiz_e2e serve --port 8187 --origin ${WEB}`,
      cwd: '../backend', url: `${API}/api/health`, timeout: 180_000, reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4187 --strictPort',
      url: WEB, env: { VITE_API_MOCK: 'false', API_PROXY_TARGET: API }, reuseExistingServer: false,
    },
  ],
})
