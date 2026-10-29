import { existsSync } from 'node:fs'
import { defineConfig } from '@playwright/test'

// 배포된 환경(staging·운영)에 붙는 e2e. 목업 시험(playwright.config.ts)과 달리 개발 서버를 띄우지 않는다.
// 주소·시험 계정·접근 링크는 커밋하지 않는 .env.e2e.local(또는 환경변수)에서 읽는다.
if (existsSync('.env.e2e.local')) process.loadEnvFile('.env.e2e.local')

export default defineConfig({
  testDir: './e2e-deployed',
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL,
    browserName: 'chromium',
    // 요청 본문(비밀번호)이 남는 trace·스크린샷·영상은 만들지 않는다.
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
