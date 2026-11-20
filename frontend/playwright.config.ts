import { defineConfig } from '@playwright/test'

// 가짜 API(VITE_API_MOCK=true)로 화면을 시험한다. 노출 중단 플래그(VITE_CS_AGENT_DISABLED, MEG-259)에 따라 서버를 둘 띄운다.
//  - agent-disabled(4183): 플래그를 켠 빌드. 노트 선택 버튼이 기존 'AI 설명'(E09)이라 AI 설명·로그인 안내 등 기존 시험이 여기서 돈다.
//  - agent-enabled(4185): 플래그를 끈 빌드(운영 기본값과 같다). 노트 선택 버튼이 'AI에게 질문'이다.
const AGENT_ENABLED_SPECS = ['agentPanel.spec.ts', 'agentEntry.spec.ts']
const SHARED = { browserName: 'chromium', viewport: { width: 390, height: 844 }, trace: 'retain-on-failure', screenshot: 'only-on-failure' } as const

export default defineConfig({
  forbidOnly: Boolean(process.env.CI),
  testDir: './tests',
  fullyParallel: true,
  workers: 2,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  projects: [
    {
      name: 'agent-disabled',
      testIgnore: ['notes.spec.ts', 'notionImport.spec.ts', 'quizFlow.spec.ts', 'agentTransport.spec.ts', ...AGENT_ENABLED_SPECS],
      use: { ...SHARED, baseURL: 'http://127.0.0.1:4183' },
    },
    {
      name: 'agent-enabled',
      testMatch: AGENT_ENABLED_SPECS,
      use: { ...SHARED, baseURL: 'http://127.0.0.1:4185' },
    },
  ],
  webServer: [
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4183 --strictPort',
      url: 'http://127.0.0.1:4183/dev/mockup',
      env: { VITE_API_MOCK: 'true', VITE_CS_AGENT_DISABLED: '1' },
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4185 --strictPort',
      url: 'http://127.0.0.1:4185/dev/mockup',
      env: { VITE_API_MOCK: 'true', VITE_CS_AGENT_DISABLED: '' },
      reuseExistingServer: false,
    },
  ],
})
