import { defineConfig } from '@playwright/test'

// 가짜 API(VITE_API_MOCK=true)로 화면을 시험한다. 노출 중단 플래그(VITE_CS_AGENT_DISABLED, MEG-259)에 따라 서버를 둘 띄운다.
//  - agent-disabled(4183): 플래그를 켠 빌드. 노트 선택 버튼이 기존 'AI 설명'(E09)이라 AI 설명·로그인 안내 등 기존 시험이 여기서 돈다.
//  - agent-enabled(4185): 플래그를 끈 빌드(운영 기본값과 같다). 노트 선택 버튼이 'AI에게 질문'이다. 위키 플래그는 꺼져 있다.
//  - agent-wiki(4187): agent-enabled에 위키 플래그(VITE_CS_AGENT_WIKI_ENABLED, MEG-254)를 켠 빌드. 위키 시험(WIKI_SPECS)만 돈다.
//    agentWiki.spec.ts는 agent-enabled에서도 돌아 플래그를 끈 동작을 함께 본다.
const AGENT_ENABLED_SPECS = ['agentPanel.spec.ts', 'agentEntry.spec.ts', 'agentViewModes.spec.ts', 'agentExceptions.spec.ts', 'agentMobileBoards.spec.ts', 'agentWiki.spec.ts', 'agentPanelResize.spec.ts']
// agentWikiFlagOn.spec.ts는 플래그를 켠 빌드에서만 뜻이 있어 agent-wiki에서만 돈다(CI는 건너뛴 시험을 실패로 본다).
const WIKI_SPECS = ['agentWiki.spec.ts', 'agentWikiFlagOn.spec.ts']
// 단계별 지도 가이드(MEG-289). 공개 목록은 비어 있으므로 두 서버 모두 시험용 목록(VITE_GUIDES_E2E, src/guides/fixtures/e2e)을 쓴다.
//  - guides(4189): 가이드 플래그(VITE_GUIDES_ENABLED)를 켠 빌드. 가이드 시험과, 연결이 붙은 노트에서 기존 노트·용어 시험을 다시 돈다(PRD AC-11).
//  - agent-disabled(4183): 가이드 플래그를 끈 빌드. guidesOff.spec.ts가 연결과 경로가 없는지 본다.
const GUIDE_SPECS = ['guides.spec.ts', 'noteRead.spec.ts', 'termSheet.spec.ts']
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
      testIgnore: ['notes.spec.ts', 'notionImport.spec.ts', 'quizFlow.spec.ts', 'agentTransport.spec.ts', 'guides.spec.ts', ...AGENT_ENABLED_SPECS, ...WIKI_SPECS],
      use: { ...SHARED, baseURL: 'http://127.0.0.1:4183' },
    },
    {
      name: 'agent-enabled',
      testMatch: AGENT_ENABLED_SPECS,
      use: { ...SHARED, baseURL: 'http://127.0.0.1:4185' },
    },
    {
      name: 'agent-wiki',
      testMatch: WIKI_SPECS,
      use: { ...SHARED, baseURL: 'http://127.0.0.1:4187' },
    },
    {
      name: 'guides',
      testMatch: GUIDE_SPECS,
      use: { ...SHARED, baseURL: 'http://127.0.0.1:4189' },
    },
  ],
  webServer: [
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4183 --strictPort',
      url: 'http://127.0.0.1:4183/dev/mockup',
      env: { VITE_API_MOCK: 'true', VITE_CS_AGENT_DISABLED: '1', VITE_CS_AGENT_WIKI_ENABLED: '', VITE_GUIDES_ENABLED: '', VITE_GUIDES_E2E: '1' },
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4185 --strictPort',
      url: 'http://127.0.0.1:4185/dev/mockup',
      env: { VITE_API_MOCK: 'true', VITE_CS_AGENT_DISABLED: '', VITE_CS_AGENT_WIKI_ENABLED: '' },
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4187 --strictPort',
      url: 'http://127.0.0.1:4187/dev/mockup',
      env: { VITE_API_MOCK: 'true', VITE_CS_AGENT_DISABLED: '', VITE_CS_AGENT_WIKI_ENABLED: '1' },
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4189 --strictPort',
      url: 'http://127.0.0.1:4189/dev/mockup',
      env: { VITE_API_MOCK: 'true', VITE_CS_AGENT_DISABLED: '1', VITE_CS_AGENT_WIKI_ENABLED: '', VITE_GUIDES_ENABLED: '1', VITE_GUIDES_E2E: '1' },
      reuseExistingServer: false,
    },
  ],
})
