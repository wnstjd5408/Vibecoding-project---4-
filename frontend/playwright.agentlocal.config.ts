import { defineConfig } from '@playwright/test'

// 로컬 실제 백엔드·DB·Auth에 붙는 CS Agent e2e (MEG-240). 모델(Bedrock)만 시험용 가짜다.
// 먼저 backend에서 `uv run python -m scripts.local_backend prepare|start|fixture`로 로컬 Supabase를 준비한다.
// 합성 노트는 시험마다 시험이 직접 다시 넣는다(tests-local/agentLocal.spec.ts의 beforeEach).
// 노출 중단 플래그를 끈 빌드(VITE_CS_AGENT_DISABLED 빈 값)라 노트 선택 버튼이 'AI에게 질문'이다.
const WEB = 'http://127.0.0.1:4188'
const API = 'http://127.0.0.1:8188'

export default defineConfig({
  testDir: './tests-local', testMatch: ['agentLocal.spec.ts'], fullyParallel: false, workers: 1, retries: 0, reporter: 'list',
  use: { baseURL: WEB, browserName: 'chromium', viewport: { width: 1280, height: 800 }, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: [
    {
      command: `uv run --frozen python -m scripts.local_agent_e2e serve --port 8188 --origin ${WEB}`,
      cwd: '../backend', url: `${API}/api/health`, timeout: 180_000, reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4188 --strictPort',
      url: WEB, env: { VITE_API_MOCK: 'false', VITE_CS_AGENT_DISABLED: '', API_PROXY_TARGET: API }, reuseExistingServer: false,
    },
  ],
})
