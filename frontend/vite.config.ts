import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 개발 서버가 /api 요청을 백엔드로 넘겨 브라우저에는 같은 출처로 보이게 한다(API spec v0.2 1.1절).
// 쿠키가 교차 사이트가 되지 않고, 백엔드의 Origin 검사(기본 허용 출처 http://localhost:5173)도 그대로 통과한다.
// localhost 대신 127.0.0.1을 쓴다. 백엔드(fastapi dev)는 IPv4로만 열려 있어 Node가 localhost를 ::1로 풀면 연결이 거부된다.
const API_TARGET = 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 헬스체크를 포함한 /api/*를 경로 변경 없이 넘긴다.
      '/api': { target: API_TARGET },
    },
  },
})
