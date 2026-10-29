# Vibecoding project 4

clone한 뒤 아래 [설정](#설정) 1~3단계를 순서대로 진행한다. 약 10분 걸린다.

## 필요한 도구

| 도구 | 용도 |
|---|---|
| [Git](https://git-scm.com/) | 버전 관리 |
| [GitHub CLI](https://cli.github.com/) (`gh`) | 로그인, PR 생성 |
| [Node.js](https://nodejs.org/) 24 + npm | 프론트엔드(`frontend/`, React). 버전은 루트 `.nvmrc`에 고정했다. `nvm use`(fnm은 `fnm use`)로 맞춘다 |
| [uv](https://docs.astral.sh/uv/) | 백엔드(`backend/`, FastAPI). Python 3.12가 없으면 `uv`가 내려받는다 |

## 설정

1. **clone** (3분)
   ```bash
   git clone https://github.com/wnstjd5408/Vibecoding-project---4-.git
   cd Vibecoding-project---4-
   ```
2. **GitHub 로그인** (3분)
   ```bash
   gh auth login
   ```
3. **커밋 작성자 설정** (4분). 공개 저장소라 커밋에 적힌 이메일이 그대로 공개된다. GitHub Settings → Emails에서 "Keep my email addresses private"를 켜고 `...@users.noreply.github.com` 주소를 쓴다.
   ```bash
   git config user.name "<GitHub 아이디>"
   git config user.email "<noreply 주소>"
   ```

줄바꿈은 `.gitattributes`가 LF로 맞추므로 따로 설정하지 않는다.

## 실행

터미널 두 개를 연다. 백엔드를 먼저 켠다.

1. **백엔드** (`http://localhost:8000`)
   ```bash
   cd backend
   uv sync
   uv run fastapi dev app/main.py
   ```
2. **프론트엔드** (`http://localhost:5173`)
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
3. 브라우저에서 `http://localhost:5173/dev/foundation`을 연다. "1. /api 요청" 줄 끝에 `응답: ok`가 보이면 프런트가 백엔드까지 이어진 것이다. 백엔드만 따로 보려면 터미널에서 `curl http://localhost:8000/api/health`를 실행해 `{"status":"ok"}`가 오는지 본다. `frontend/.env.local`에 `VITE_API_MOCK=true`를 두면 백엔드 없이도 `ok`가 나오므로 연결 확인에는 쓰지 않는다.

환경변수 이름은 `backend/.env.example`, `frontend/.env.example`에 있다. 지금은 값 없이도 실행된다. Supabase는 아직 연결하지 않았다.

| 검사 | 위치 | 명령 |
|---|---|---|
| 백엔드 테스트 | `backend/` | `uv run pytest` |
| 프론트엔드 린트 | `frontend/` | `npm run lint` |
| 프론트엔드 빌드 | `frontend/` | `npm run build` |

## 프런트에서 API 부르기

화면 코드는 FastAPI(`/api`)만 부른다. Supabase와 AI는 화면에서 직접 부르지 않는다. 아래는 `/api/health`를 예로 든 사용법이다. 배포된 환경에서 확인하는 절차는 [배포 가이드](docs/deployment-guide.md)를 따른다.

```ts
import { apiFetch, isApiError } from '../api/client.ts' // 경로는 부르는 파일 위치에 맞춘다

try {
  const health = await apiFetch<{ status: string }>('/api/health') // { status: 'ok' }
} catch (error) {
  if (isApiError(error, 'login_required')) {
    // 로그인 안내 시트를 띄운다
  } else {
    throw error
  }
}
```

| 하고 싶은 일 | 쓰는 곳 |
|---|---|
| API 부르기 | `frontend/src/api/client.ts`의 `apiFetch<T>(path)`. 경로는 API spec의 것(`/api/me` 등)을 그대로 쓴다. 성공하면 본문을, 실패하면 `ApiError`를 던진다 |
| 오류 구분 | `isApiError(error, code)`처럼 `code`(필요하면 `detail`)로 가른다. `message`는 영어 고정 문구라 화면에 띄우거나 분기에 쓰지 않는다. 서버가 아니라 클라이언트가 만드는 `code`는 `network_error`, `unexpected_response`다 |
| 가짜·실제 응답 전환 | `frontend/.env.example`의 `VITE_API_MOCK` 한 곳. `true`면 가짜 응답을, 아니면 개발 서버 프록시(`frontend/vite.config.ts`)를 거친 실제 백엔드를 쓴다. 값을 바꾸면 `npm run dev`를 다시 시작한다. 부르는 코드는 바꾸지 않는다 |
| 가짜 응답 | `frontend/src/api/mocks/handlers.ts`. `/api/health`, `/api/auth/login`·`logout`, `/api/me`, `/api/notes`, `/api/notes/{id}`, `/api/glossary/{id}`, `/api/term-views`, `/api/favorites/{id}`가 있고 합성 데이터만 쓴다. 가짜 로그인 상태는 `frontend/src/api/mocks/session.ts`의 `setMockSession`으로 바꾼다 |
| 로그인 상태 | `frontend/src/auth/useAuth.ts`의 `const { status, role, displayName, refresh } = useAuth()`. `role`은 `'visitor'`, `'member'`, `'operator'` 중 하나다. 일반 사용자는 `'user'`가 아니라 `'member'`다(서버 계약 값). 로그인·로그아웃 뒤에는 `refresh()`를 부른다 |
| 화면 경로 | `frontend/src/routes/paths.ts`에 경로 이름이 있다. 사용자(모바일)는 `userRoutes.tsx`, 운영자(PC)는 `operatorRoutes.tsx`다. 아직 없는 화면은 `frontend/src/pages/Placeholder.tsx`로 이어져 있고 해당 화면 티켓이 그 줄의 `element`를 바꾼다 |

2026-10-29 기준 실제 백엔드에는 `/api/health`만 있다. 아직 없는 엔드포인트를 실제 모드로 부르면 `404`와 `code`가 `not_found`인 오류가 오므로, 그 화면은 `VITE_API_MOCK=true`로 가짜 응답을 받으며 만든다. 백엔드에 엔드포인트가 생기면 이 문장의 날짜와 내용을 고친다.

`/dev/foundation`(`frontend/src/pages/FoundationDemo.tsx`)이 위 호출·오류 구분·로그인 상태를 한 화면에서 보여 주는 샘플이다. 화면을 만들기 전에 이 파일을 열어 보면 쓰는 모양을 바로 볼 수 있다.

## 기여 규칙

1. 브랜치 이름은 `<이슈ID소문자>-<짧은-설명>` 형식이다. 예: `meg-12-first-experiment`
2. PR 제목은 `<type>(<이슈ID>): <설명>` 형식이고 type은 `feat`, `fix`, `docs`, `chore` 중 하나다. 제목과 브랜치의 이슈 ID가 같아야 하고, PR 본문에 이슈 ID를 적고 템플릿의 빈 AC·검증 줄을 채워야 한다. 하나라도 틀리면 `Check PR metadata` 검사가 실패한다.
3. main에는 직접 푸시할 수 없다. PR을 열고 리뷰 승인을 받은 뒤 squash로 머지한다.
4. API 키, 토큰, 비밀번호는 커밋하지 않는다. 비밀값은 환경변수로 쓰고 `.env`는 `.gitignore`가 막아 둔다.
5. AI 에이전트에게 작업을 맡길 때는 [AGENTS.md](AGENTS.md)를 따르게 한다.
6. 작업 전에 [docs/decisions.md](docs/decisions.md)에서 지금까지의 제품·기술 결정을 확인한다. 원본은 Linear이고 이 파일은 공개 요약이다.

이슈 관리, 알림, 리뷰 담당 같은 팀 운영 방식은 팀 내부 문서에서 안내한다.
