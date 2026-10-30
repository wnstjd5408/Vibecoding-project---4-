# 백엔드 로컬 개발 환경 설정

이 가이드를 따라 하면 운영 계정이나 클라우드 관리자 권한 없이 즐겨찾기 API(MEG-89)와 신고 관리 API(MEG-83)를 개발할 수 있습니다. 내 PC에 테스트용 Supabase를 띄우고, 합성 계정과 데이터를 넣은 뒤 FastAPI에서 로그인과 DB 접근을 확인합니다.

설정에는 두 가지가 필요합니다. Docker Desktop이 로컬 DB와 인증 서비스를 실행하고, Python 보조 도구가 설정 파일 복사와 테스트 데이터 준비를 맡습니다. 보조 도구의 명령은 이 문서에 나오는 여섯 개뿐입니다.

## 1. 준비할 도구와 권한

| 준비물 | 확인 방법 | 용도 |
|---|---|---|
| Git | `git --version` | 저장소 받기, 브랜치와 PR 작업 |
| Node.js 24 | `node --version` | 고정 버전 Supabase CLI 실행 |
| uv | `uv --version` | Python 3.12와 잠긴 의존성 설치 |
| Docker Desktop | 앱을 실행한 뒤 `docker info --format '{{.ServerVersion}}'` | 로컬 DB, Auth, REST 실행 |
| Linear 명세 열람 권한 | MEG-89·83과 연결된 API spec 열기 | 요청·응답과 완료 조건 확인 |
| GitHub 저장소 접근 권한 | clone, 작업 브랜치 push, PR 작성 | 코드 제출 |

Windows에서는 Docker Desktop을 Linux 컨테이너 모드로 실행하세요. Docker 설치를 위해 PC 관리자 권한이 필요할 수 있지만, AWS·Vercel·운영 Supabase 관리자 권한은 필요하지 않습니다. 처음 실행할 때는 Python 패키지, CLI, Docker 이미지를 내려받으므로 인터넷 연결이 필요합니다.

Supabase 계정 로그인, 원격 프로젝트 연결, 운영 키 복사는 하지 않습니다. 로컬 키도 비밀값이므로 채팅·티켓·PR·스크린샷에 넣지 마세요. AI로 작업한다면 저장소 규칙에 따라 AI 전용 GitHub 계정과 세션 전용 worktree를 사용합니다.

## 2. 작업 폴더와 Python 환경 준비

새 작업 폴더를 만드는 예시입니다. 이미 전용 worktree가 있다면 그 폴더에서 시작하세요. 다른 작업이 진행 중인 폴더의 브랜치를 바꾸지 않습니다.

```powershell
git clone https://github.com/wnstjd5408/Vibecoding-project---4-.git
cd Vibecoding-project---4-
git switch -c meg-89-favorites-api
cd backend
uv sync --frozen --python 3.12
```

신고 관리 담당자는 브랜치 이름을 `meg-83-report-admin-api`로 바꿉니다. 아래 명령은 모두 **backend 폴더**에서 실행합니다. `--frozen`은 저장소의 `uv.lock`에 있는 버전을 그대로 설치합니다.

## 3. 내 작업 폴더 전용 DB 설정 만들기

```powershell
uv run python -m scripts.local_backend prepare
```

`Prepared isolated project; API port 55321`이 나오면 준비된 것입니다. 이 명령은 서비스를 시작하지 않고 저장소 루트의 `.local-backend/`에 다음 파일을 만듭니다.

| 파일 | 내용 |
|---|---|
| `supabase/config.toml` | 현재 작업 폴더에 고유한 프로젝트 이름과 로컬 포트 |
| `supabase/migrations/` | prepare 시점의 저장소 마이그레이션 사본 |
| `supabase/seed.sql` | 과목 이름만 넣는 기본 시드 사본 |

기본 포트는 API 55321, DB 55322, shadow DB 55320입니다. 다른 개발 환경이 이 포트를 쓰고 있다면 **prepare를 처음 실행할 때** 다른 번호를 고르세요.

```powershell
uv run python -m scripts.local_backend prepare --base-port 56320
```

이 경우 API는 56321, DB는 56322를 씁니다. 프로젝트 이름은 폴더 경로에 따라 달라지지만 포트는 직접 구분해야 합니다. 이미 `.local-backend/`가 있으면 덮어쓰지 않고 중단합니다.

이 폴더 전체는 git에서 제외됩니다. 원본 `supabase/config.toml`과 기본 시드는 바뀌지 않으며, 원격 프로젝트 연결 파일도 복사하지 않습니다.

## 4. 로컬 Supabase 시작

```powershell
uv run python -m scripts.local_backend start
```

처음에는 이미지 다운로드 때문에 몇 분 걸릴 수 있습니다. `Local Postgres/Auth/REST started; credentials hidden.`이 나오면 완료입니다. Supabase CLI는 **2.121.0**으로 고정되어 있고, 이 두 티켓에 필요한 Postgres·Auth·REST만 실행합니다. Storage·Studio·AI 서비스는 실행하지 않습니다.

처음 만든 DB에는 마이그레이션과 기본 과목 데이터가 적용됩니다. 기존 로컬 DB가 있다면 start는 그 DB를 다시 사용합니다. 최신 main을 받은 뒤 마이그레이션이 달라졌다면 아래 ‘환경을 새로 만들 때’를 따르세요.

## 5. 테스트 계정과 합성 데이터 넣기

```powershell
uv run python -m scripts.local_backend fixture
```

성공하면 `Synthetic fixture restored.`가 나옵니다. 로컬 Auth에 계정 4개를 만들고 역할과 활성 상태를 DB에 기록합니다. 기존 계정이 있으면 테스트 비밀번호를 맞춘 뒤 합성 데이터를 다시 준비합니다.

| 로그인 이메일 | 역할 | 사용할 때 |
|---|---|---|
| `operator@example.test` | 운영자 | 신고 목록·처리 허용 확인 |
| `member-a@example.test` | 일반 사용자 A | 즐겨찾기 추가·해제, 운영자 API 거부 확인 |
| `member-b@example.test` | 일반 사용자 B | 사용자 A와 데이터가 섞이지 않는지 확인 |
| `inactive@example.test` | 비활성 일반 사용자 | 로그인 거부 확인 |

방문자는 로그인하지 않은 요청으로 시험합니다. 네 계정의 공통 테스트 비밀번호는 처음 실행할 때 임의로 생성하며 화면에 출력하지 않습니다.

설정값은 저장소 루트의 **`.local-backend/.env`**에 저장됩니다. 브라우저에서 시험할 때는 로컬 편집기로 이 파일의 `LOCAL_TEST_PASSWORD`를 확인하세요. 파일을 공유하거나 git에 추가하지 않습니다.

| 변수 | 설정 방법 |
|---|---|
| `SUPABASE_URL` | 보조 도구가 이번 로컬 프로젝트 주소를 기록 |
| `SUPABASE_SECRET_KEY` | CLI가 돌려준 로컬 service-role 키를 기록 |
| `LOCAL_TEST_PASSWORD` | 보조 도구가 테스트 계정용으로 생성 |
| `ALLOWED_ORIGINS` | Vite 개발 주소 `http://localhost:5173` |

이 값들은 로컬 전용입니다. 운영·staging 키를 넣지 마세요. 보조 도구는 부모 셸에 원격 `SUPABASE_URL`이 남아 있거나 CLI 주소가 이번 프로젝트와 다르면 중단합니다. `.env` 파일을 쓰는 데 실패했다면 원인을 해결한 뒤 fixture를 다시 실행할 수 있습니다.

**fixture를 다시 실행하면 이 도구가 만든 테스트 계정의 신고·퀴즈와 예약 ID 범위의 합성 노트·용어·설명이 초기 상태로 돌아갑니다.** 관련 즐겨찾기도 되돌아갑니다. API 구현 시험 중 남긴 결과를 보존하려면 먼저 검증 결과만 기록하세요. 이 DB에는 보존할 실제 자료를 넣지 않습니다. SQL 파일을 운영 DB나 SQL Editor에 복사해 실행하지 마세요.

## 6. 로그인과 DB 연결 확인

```powershell
uv run python -m scripts.local_backend check
uv run pytest -q
```

`check`는 FastAPI 앱을 같은 Python 프로세스에서 호출하되, 인증과 DB 요청은 실제 로컬 Supabase로 보냅니다. 계정 역할, 로그인·로그아웃, 비활성 계정 거부, 방문자 상태, Origin 검사, 쿠키 속성, 속도 제한 SQL 함수, 데이터 행 수와 관계를 확인합니다.

마지막에 `PASS: real local Auth...`가 나오면 환경 점검을 통과한 것입니다. 이후에 실행하는 pytest는 제품 코드와 보조 도구의 단위 시험입니다. 두 결과를 구분해서 기록하세요.

Secure 쿠키를 그대로 시험하려고 `check`의 앱 주소는 `https://localhost`로 잡았습니다. 이는 ASGI 테스트 주소여서 인증서나 실제 HTTPS 서버가 필요하지 않습니다. 제품의 `Secure`·`HttpOnly` 설정은 바꾸지 않습니다.

행 수가 다르다는 오류가 나오면 API 시험으로 데이터가 바뀌었을 수 있습니다. fixture로 기준 상태를 복원하고 check를 다시 실행하세요. 이 점검은 초기 상태 확인용이며, 이미 작성한 제품 API의 기능 시험을 대신하지 않습니다.

## 7. 서버와 화면 실행

```powershell
uv run python -m scripts.local_backend serve
```

서버는 `http://127.0.0.1:8000`에서 실행됩니다. 이 명령이 `.local-backend/.env`를 해당 프로세스에만 읽어 들이므로 `backend/.env`에 키를 복사할 필요가 없습니다. 종료는 `Ctrl+C`입니다.

다른 터미널에서 서버 응답을 확인하세요.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

`status: ok`는 API 프로세스가 응답한다는 뜻입니다. DB와 Auth는 앞 단계의 check 결과로 확인합니다.

화면을 연결할 때는 frontend 폴더에서 다음을 실행합니다.

```powershell
npm ci
$env:VITE_API_MOCK = 'false'
npm run dev
```

브라우저는 **`http://localhost:5173`**으로 여세요. Vite가 `/api`를 백엔드로 전달합니다. 브라우저별 localhost Secure 쿠키 처리와 화면의 실제 API 연결은 별도 확인이 필요합니다. 쿠키 문제를 피하려고 제품의 Secure 속성을 끄지는 마세요. 가짜 응답 모드의 성공은 실제 서버 연결 증거가 아닙니다.

## 8. 두 티켓에서 사용할 데이터와 시험 순서

데이터의 날짜는 **2026-10-29·2026-10-30 KST**로 고정했습니다. 실행한 날의 날짜가 아닙니다. KST 경계 시험에서는 API 시계를 주입해 고정하거나, 오늘 추가된 행을 기존 고정 날짜 행과 구분하세요.

| 데이터 | ID와 초기 상태 |
|---|---|
| 노트 | 132001, 공개된 합성 노트 |
| 용어 | 132001~132004는 AI 용어, 132005는 사전 용어 |
| AI 설명 | 132001~132003은 유효, 132004는 무효화됨. 실제 모델 호출 없음 |
| 즐겨찾기 | A→132001, B→132002 |
| 추가 이력 | A→132001은 10/29·10/30, A→132003과 B→132002는 10/30 |
| 퀴즈 | 세트·문항 132001은 A 소유, 132002는 B 소유 |
| 열린 신고 | 132001~132003은 각각 같은 번호의 AI 설명, 132004·132005는 퀴즈 문항 |
| 처리된 신고 | 132006, 무효화된 AI 설명 132004 대상 |

기준 행 수는 profiles 4, notes 1, terms 5, ai_explanations 4, favorites 2, favorite_events 4, quiz_sets 2, quiz_items 2, reports 6입니다. 신고는 열린 것 5건, 처리된 것 1건입니다. `term_key_snapshot`은 각 설명에 `fixture alpha` 등의 합성 값으로 저장돼 있습니다.

아래 표는 **API 구현 후** 확인할 항목입니다. 이 가이드의 환경 점검이 통과했다고 아래 기능까지 통과한 것은 아닙니다. 미구현 엔드포인트는 미검증으로 남깁니다. 요청·응답의 원본은 Linear의 확인된 API spec v0.2입니다.

| 티켓·시험 | 입력 | 기대 결과 |
|---|---|---|
| MEG-89 추가 | A가 E08 `PUT /api/favorites/132005`, `favorited: true` | 200, `is_favorite: true`, A의 즐겨찾기와 당일 이력 생성 |
| MEG-89 반복·해제 | 같은 추가를 반복한 뒤 `favorited: false` | 중복 행 없음. 즐겨찾기만 해제되고 당일 이력 유지 |
| MEG-89 사용자 분리 | A가 자기 132001을 해제 | B의 132002와 이력 유지. 본문 사용자 ID로 소유자 변경 불가 |
| MEG-89 인증·Origin | 방문자 요청, 허용 Origin 없는 요청을 따로 실행 | 각각 401, 403. DB 변경 없음 |
| MEG-83 목록 | 운영자로 E25 `GET /api/admin/reports` | 기본 open 5건. `status=resolved`는 1건 |
| MEG-83 쪽 나누기 | `limit=2`, 반환된 cursor로 다음 요청 | 전체 열린 신고를 중복·누락 없이 조회 |
| MEG-83 생략·false | E26 `PATCH /api/admin/reports/132001`에 `status: resolved`; 132002는 `invalidate_explanation: false`도 지정 | 신고 처리, 두 설명은 유효 상태 유지 |
| MEG-83 true | 132003을 `status: resolved`, `invalidate_explanation: true`로 처리 | 연결된 설명 132003만 무효화 |
| MEG-83 권한 | 같은 유효 요청을 일반 사용자·방문자로 실행 | 각각 403·401, 신고와 설명 변경 없음 |

MEG-83은 운영자 API를 만드는 작업이지만 클라우드 관리자 계정은 필요하지 않습니다. 위 로컬 운영자 계정으로 시험하면 됩니다. 화면과의 연결, staging 적용은 담당자와 따로 확인합니다.

## 9. 작업 종료와 환경을 새로 만들 때

로컬 서비스만 멈추고 데이터는 남기려면 다음을 실행합니다.

```powershell
uv run python -m scripts.local_backend stop
```

다음 작업 때 start를 실행하면 같은 데이터를 사용합니다. Docker 전체를 정리하거나 다른 프로젝트의 컨테이너를 멈출 필요는 없습니다.

마이그레이션을 새로 적용하거나 포트를 바꾸려면 가장 간단한 방법은 **현재 환경을 stop한 뒤 새 worktree에서 prepare부터 다시 진행하는 것**입니다. 새 폴더 경로에 고유한 프로젝트가 생깁니다. 이전 데이터를 재사용하지 않으며, 원격 `db push`·`db reset --linked`는 필요하지 않습니다. 사용하지 않는 옛 로컬 볼륨의 삭제는 보존할 데이터가 없는지 확인한 뒤 별도로 합니다.

## 10. 막힐 때 확인할 것

보조 도구는 CLI 응답에 키가 섞일 수 있어 실패 원문을 그대로 출력하지 않습니다. 먼저 아래 항목을 확인하세요.

| 증상 | 확인·조치 |
|---|---|
| docker 실행 실패 | Docker Desktop이 실행 중인지, Linux 컨테이너 모드인지 확인합니다. `docker context show`로 로컬 문맥을 확인합니다. SSH/TCP 원격 Docker는 이 가이드에서 쓰지 않습니다. |
| start 실패, 포트 충돌 의심 | `docker ps --format '{{.Names}}'`로 실행 중인 컨테이너를 확인합니다. Windows에서는 `netsh interface ipv4 show excludedportrange protocol=tcp`로 예약 포트를 확인합니다. 새 worktree에서 다른 base-port로 준비합니다. |
| 원격 SUPABASE_URL 거부 | 이 터미널에 다른 환경의 변수가 남아 있는지 확인하고 새 터미널을 엽니다. 운영 URL을 로컬 도구에 넣지 않습니다. |
| 로컬 .env 불일치 | 다른 worktree의 파일을 복사했거나 로컬 키가 바뀌었을 수 있습니다. 새 worktree에서 환경을 다시 만듭니다. 키를 출력해 비교하지 않습니다. |
| 로그인 429 | 짧은 시간에 check나 로그인 실패를 반복했는지 확인하고 제한 창이 지난 뒤 다시 실행합니다. 제품의 제한을 끄지 않습니다. |
| Origin 403 | 상태 변경 요청에 `Origin: http://localhost:5173`이 있는지 확인합니다. 역할 거부 403과 구분합니다. |
| fixture 행 수 오류 | 제품 시험으로 바뀐 결과를 기록한 뒤 fixture → check를 실행합니다. |
| SQL 초기화 실패 | 최신 마이그레이션과 도구가 같은 커밋인지 확인합니다. 예약 ID 132001~132099를 다른 데이터에 사용하지 않습니다. SQL은 트랜잭션으로 적용되므로 실패한 데이터 변경은 롤백됩니다. Auth 계정은 남을 수 있으며 같은 fixture 명령으로 재시도할 수 있습니다. |

## 11. 인계할 때 남길 기록

담당자는 기준 커밋, OS·도구 버전, prepare → start → fixture → check 결과, fixture를 두 번 실행한 결과를 티켓에 남깁니다. 비밀번호나 키 대신 통과 여부와 오류 종류만 적습니다.

MEG-89·83을 넘기기 전에는 사람이 각 티켓의 작업 크기, 담당자, 범위와 AC, 시험 방법을 확정합니다. 두 티켓의 기존 ‘S, AI 제안’ 표기는 기능 변경 범위와 맞는지 확인해야 합니다. 원격 적용·staging 검증은 김준성에게 인계하며, 코드 작성자는 로컬 검증과 PR 제출까지 담당하는 방식으로 시작합니다.

이 가이드는 Windows에서 Python 3.12·uv와 로컬 Docker를 사용하는 절차입니다. 다른 OS에서의 재현과 브라우저별 로그인은 별도 검증으로 기록합니다. 공식 CLI의 시드와 마이그레이션 동작은 [Supabase 로컬 개발 문서](https://supabase.com/docs/guides/local-development/database-migrations)를 참고하세요.
