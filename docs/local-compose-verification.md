# Compose 로컬 검증 기록

2026-11-03 Codex 실행 환경에서 직접 수행했다. 팀원 PC 재현·원격 Preview 검증은 포함하지 않는다.

## 기준

- 독립 worktree, main `5dbadcc20a4f303af516556016cde194b1284d02`에 이번 Compose 변경을 적용.
- Windows / Docker 29.8.2 / Compose 5.5.1 / Node 24.19.0 / Python 3.12.15 / uv 0.12.23 / Supabase CLI 2.121.0.
- 새 로컬 DB: base-port 57320, 기존 prepare → start → fixture → check 수행. 새 setup의 호출 순서는 단위 검사로 확인했으며 실제 환경 구성 요소는 각각 실행했다.
- backend와 frontend 이미지를 실제 빌드하고 localhost:5173으로 접속. backend에는 호스트 공개 포트가 없다.

## 결과

| 항목 | 직접 확인 |
|---|---|
| 이미지 시작 | 두 앱 healthcheck 통과. 최초 backend에서 evals 패키지 누락으로 실패해 필요한 소스를 추가하고 재빌드 후 통과 |
| 실제 DB 연결 | 기존 check의 Auth·REST·역할·비활성·Origin·쿠키·행 수 점검 통과 |
| 브라우저 로그인 | Playwright Chromium으로 운영자 로그인, /api/me 인증·역할과 Secure/HttpOnly 쿠키 확인 |
| E24 실제 API | 인증된 브라우저의 같은 출처 fetch로 72바이트 초과 422(initial_password), 신규 201, 중복 409 확인 |
| 발급 계정 로그인 | 별도 브라우저 컨텍스트에서 신규 계정 로그인·member 역할 확인 |
| 전체 종료·재시작 | local_compose stop → up 후 신규 계정 재로그인, 동일 Auth/profile UUID와 합성 용어 5개 유지 확인 |
| 준비 명령 재실행 | 기존 환경에 local_compose setup 재실행 후 같은 UUID·프로필·용어 유지. 추가 합성 계정만 확인 후 정리 |
| 이미지 분리 | backend 이미지를 네트워크 없이 실행해 app.main import 성공, /app/.env 없음 확인 |
| 공개 포트 | frontend 5173/tcp → 127.0.0.1:5173, backend 호스트 포트 없음 |
| 회귀 검사 | local_backend + local_compose 관련 검사 26 passed, frontend lint·build 및 git diff --check 통과 |

현재 main에는 계정 발급 폼이 없으므로 이번 E24 검증은 **브라우저에서 실제 API를 호출한 검증**이다. 폼 오류 위치·입력 유지 검증으로 주장하지 않는다. PR #69 화면을 이 PR에 복사하거나 제품 기능을 변경하지 않았다. 기존 PR #69 화면 검증은 별도 온보딩 기록을 참고한다.

프런트 빌드는 기존 큰 번들 경고를 출력했지만 종료 코드는 0이다. 전체 제품·모든 브라우저·Linux/macOS·팀원 PC·Preview는 미검증이다. 외부 DB 쓰기와 AI 호출은 하지 않았고 비밀값은 ignored 로컬 환경 파일에만 저장했다. 상태 검사 성공은 담당 기능 전체 AC 통과를 뜻하지 않는다.
