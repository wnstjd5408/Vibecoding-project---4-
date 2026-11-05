# 공통 로컬 온보딩 검증 기록

2026-11-03, Codex 실행 환경에서 직접 수행했다. 팀원 PC 설치 완료나 Vercel Preview 검증을 뜻하지 않는다. 절차 원본은 [공통 가이드](backend-local-guide.md)다.

## 실행 환경

- Windows, Python 3.12.15, uv 0.12.23, Node 24.19.0, Docker 29.8.2.
- Supabase CLI: 기존 도구 고정 버전 2.121.0. 독립 worktree에서 prepare --base-port 56320 → start → fixture → check.
- 백엔드 기준 main: `5dbadcc20a4f303af516556016cde194b1284d02` + 이번 로컬 보조 도구. 제품 코드는 수정하지 않았다.
- 화면: PR #69의 `c5f3eb2753e0180cca3c71a1cb1dde6cf1e735b1`을 별도 검증 worktree에서 npm ci 후 실행. 아직 main에 없는 화면이므로 두 기준을 구분한다.
- 실제 서버: FastAPI 127.0.0.1:8000, Vite localhost:5173, Supabase 127.0.0.1:56321. VITE_API_MOCK=false.
- 브라우저: Playwright Chromium 156.0.8078.4, headless. 응답 대체·mock 없이 화면 조작과 실제 API 응답을 검사했다.

## 직접 확인한 결과

| 항목 | 결과 |
|---|---|
| 초기 fixture/check | 실제 Auth 로그인·로그아웃, 역할·비활성·방문자, Origin, Secure/HttpOnly, REST·행 수·관계 통과 |
| 운영자 브라우저 로그인 | 실제 로그인 200 뒤 인증된 화면 접근 통과 |
| E24 422 | 72바이트 초과 비밀번호, initial_password 필드와 비밀번호 위치 오류 안내, 입력 유지 통과 |
| E24 201 | 성공 결과 이메일·표시 이름, 비밀번호 미표시 및 새 폼에서 비밀번호 초기화 통과 |
| E24 409 | 같은 이메일 중복 안내, 입력 유지 통과 |
| 발급 계정 로그인 | 새 브라우저 컨텍스트에서 로그인하고 /api/me authenticated=true, role=member 확인 |
| Auth·profiles | 201 응답 ID로 합성 이메일·이름·member·is_active 확인 |
| 정리·재실행 | 발급 → inspect → cleanup → fixture → check를 두 회 수행. 두 번째 생성과 로그인도 통과 |
| 삭제 보호 | 기본 운영자 UUID로 cleanup을 시도하면 Auth identity 불일치로 거부. 기본 fixture 계정 유지 |
| 보조 도구 회귀 검사 | test_local_backend.py + test_local_account.py: 23 passed |
| 백엔드 전체 회귀 검사 | uv run pytest -q: 1631 passed, 82 skipped (51.47s). 건너뛴 검사는 통과로 세지 않음 |

신규 E24 입력에 `.test`를 쓰면 이메일 검증에서 422가 발생한다. fixture의 Auth 직접 생성 계정과 달라서 신규 입력은 `onboarding-e24@example.com`으로 수정해 검증했다. 비밀값은 무시되는 로컬 환경 파일에서만 읽었으며 요청 본문·키·쿠키·비밀번호를 기록하지 않았다. 원격 DB 쓰기와 AI 호출은 하지 않았다.

## 남은 확인

- 팀원 각자의 PC·브라우저에서는 미검증이다. 각자 가이드를 실행하고 OS·버전·SHA·통과/실패 단계·재개 조건을 Linear 온보딩 표에 기록해야 한다.
- Vercel Preview·원격 테스트 환경, 다른 브라우저·OS는 미검증이다.
- 이 기록의 E24 통과를 다른 API의 AC 통과로 확대하지 않는다. 화면 PR이 main에 병합되면 실제 사용할 최종 조합에서 확인한다.
