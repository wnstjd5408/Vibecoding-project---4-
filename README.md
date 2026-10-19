# Vibecoding project 4

clone한 뒤 아래 [설정](#설정) 1~3단계를 순서대로 진행한다. 약 10분 걸린다.

## 필요한 도구

| 도구 | 용도 |
|---|---|
| [Git](https://git-scm.com/) | 버전 관리 |
| [GitHub CLI](https://cli.github.com/) (`gh`) | 로그인, PR 생성 |
| [Node.js](https://nodejs.org/) 24 + npm | 프론트엔드(`frontend/`, React) |
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
3. 브라우저에서 `http://localhost:5173`을 연다. "백엔드 상태" 줄 끝에 `ok`가 보이면 정상이다.

환경변수 이름은 `backend/.env.example`, `frontend/.env.example`에 있다. 지금은 값 없이도 실행된다. Supabase는 아직 연결하지 않았다.

| 검사 | 위치 | 명령 |
|---|---|---|
| 백엔드 테스트 | `backend/` | `uv run pytest` |
| 프론트엔드 린트 | `frontend/` | `npm run lint` |
| 프론트엔드 빌드 | `frontend/` | `npm run build` |

## 기여 규칙

1. 브랜치 이름은 `<이슈ID소문자>-<짧은-설명>` 형식이다. 예: `meg-12-first-experiment`
2. PR 제목은 `<type>(<이슈ID>): <설명>` 형식이고 type은 `feat`, `fix`, `docs`, `chore` 중 하나다. 제목과 브랜치의 이슈 ID가 같아야 하고, PR 본문에 이슈 ID를 적고 템플릿의 빈 AC·검증 줄을 채워야 한다. 하나라도 틀리면 `Check PR metadata` 검사가 실패한다.
3. main에는 직접 푸시할 수 없다. PR을 열고 리뷰 승인을 받은 뒤 squash로 머지한다.
4. API 키, 토큰, 비밀번호는 커밋하지 않는다. 비밀값은 환경변수로 쓰고 `.env`는 `.gitignore`가 막아 둔다.
5. AI 에이전트에게 작업을 맡길 때는 [AGENTS.md](AGENTS.md)를 따르게 한다.

이슈 관리, 알림, 리뷰 담당 같은 팀 운영 방식은 팀 내부 문서에서 안내한다.
