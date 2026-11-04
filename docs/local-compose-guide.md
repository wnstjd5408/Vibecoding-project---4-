# Docker Compose로 로컬 앱 실행하기

프런트·백엔드 담당자 공통 안내다. 기존 Supabase CLI가 Auth·REST·Postgres와 DB 볼륨을 관리하고, Compose는 React(Vite)·FastAPI만 관리한다. PostgreSQL을 별도 설치하거나 Supabase를 중복 실행하지 않는다. 운영·Preview 배포용 구성은 아니다.

## 처음 준비

Git, Node.js 24(npx), uv(Python 3.12), Docker Desktop Linux 컨테이너와 Docker Compose가 필요하다. 앱 의존성은 이미지 안에 설치하지만 DB 준비 도구에는 호스트 Node·uv가 필요하다. 원격 Supabase 계정·키는 필요 없다. 본인 티켓의 전용 clone/worktree에서 진행한다.

```powershell
# 저장소 루트
docker compose version
cd backend
uv sync --frozen --python 3.12
uv run python -m scripts.local_compose setup
```

setup은 새 폴더에서 격리된 DB 설정·서비스 시작·합성 fixture·연결 점검을 수행하고 앱을 빌드한다. 첫 빌드는 다운로드 때문에 몇 분 걸릴 수 있다. 이미 로컬 환경 파일이 있는 폴더에서는 fixture를 덮어쓰지 않는다. DB 포트를 바꾸려면 **새 작업 폴더에서만** `setup --base-port 57320`처럼 지정한다. 기존 설정의 포트는 변경하지 않는다.

준비 후 **http://localhost:5173/login**을 연다. 기존 [합성 계정 안내](backend-local-guide.md)의 operator@example.test와 `.local-backend/.env`의 LOCAL_TEST_PASSWORD로 로그인한다. 키·비밀번호·쿠키·환경 파일을 로그나 채팅에 붙이지 않는다.

## 실제 연결 확인

브라우저 → Vite → Compose backend → 같은 worktree의 Supabase로 연결된다. 공개 앱 포트는 127.0.0.1:5173뿐이며 backend 8000은 Docker 내부에서만 사용한다. /api 프록시·Origin localhost:5173·Secure/HttpOnly 쿠키를 유지한다. 브라우저 주소를 127.0.0.1로 바꾸지 않는다.

1. 로그인 후 `/api/me`의 authenticated=true와 역할을 확인한다. health 성공만으로 DB/Auth 정상으로 판단하지 않는다.
2. 담당 기능의 승인된 AC를 실제 API로 확인한다. 계정 발급 화면은 그 화면이 구현된 커밋이 필요하다. mock 성공이나 다른 PR의 화면을 현재 main 검증으로 기록하지 않는다.
3. 초기 데이터·행 수는 기존 공통 가이드를 따른다. API로 추가한 데이터가 아래 종료·재시작 후에도 남는지 확인한다.

## 수정·재시작·종료

아래 명령은 모두 backend 폴더에서 실행한다.

```powershell
# 소스 변경 후 재빌드·실행, 멈춘 DB도 시작
uv run python -m scripts.local_compose up
# 앱만 종료, DB는 계속 실행
uv run python -m scripts.local_compose down
# 앱과 이 작업 폴더의 Supabase 종료, DB 데이터 유지
uv run python -m scripts.local_compose stop
```

소스를 이미지에 복사하므로 저장만으로 컨테이너에 반영되지 않는다. 수정 후 up을 실행한다. stop → up은 데이터를 초기화하지 않는다. Compose는 Supabase 네트워크·DB 볼륨을 소유하지 않는다. `down -v`, Docker 전체 정리, 원격 `db reset --linked`는 사용하지 않는다.

데이터 초기화는 별도 작업이다. 결과를 먼저 기록한 뒤 기존 `local_backend fixture → check`를 실행한다. fixture는 예약 데이터와 기본 네 계정을 복원하지만 E24 추가 계정을 지우지 않는다. 추가 계정은 공통 계정 정리 가이드가 포함된 커밋에서 지정 UUID로 정리하거나 기존 가이드의 새 worktree 재생성 절차를 따른다. 고객 자료는 넣지 않는다.

## 설정과 문제 해결

- `.local-backend/compose-backend.env`는 검증한 로컬 연결에서 생성한다. backend용 URL·키·Origin만 들어가고 테스트 비밀번호는 전달하지 않는다. 직접 편집하지 않는다.
- `docker compose config`, `docker inspect` 전체 출력에는 키가 포함될 수 있다. 공유하지 않는다. 보조 도구는 실패 원문을 숨긴다.
- Docker 실패: Desktop 실행·Linux 모드·로컬 context를 확인한다. 원격 DOCKER_HOST/DOCKER_CONTEXT는 거부한다.
- 빌드 실패: 레지스트리 연결·디스크 여유를 확인한다. 키 없는 빌드 단계만 별도 진단할 수 있다. 루트에서 `docker build -f backend/Dockerfile.local backend` 또는 `docker build -f frontend/Dockerfile.dev frontend`를 실행한다.
- 시작 실패: 5173 충돌·Docker 자원을 확인한다. 다른 세션의 서버는 강제 종료하지 않는다. 부분 시작은 down으로 이 프로젝트 앱만 정리한다.
- DB/네트워크 불일치: 현재 worktree에서 local_backend check를 실행한다. 다른 폴더의 .env를 복사하지 않는다.
- 스키마 변경: prepare는 마이그레이션을 복사한다. 새 worktree에서 setup으로 다시 준비한다. 앱 up만으로 스키마를 갱신하지 않는다.
- 403/세션 문제: localhost:5173과 실제 API 모드를 확인하고 쿠키 보안 속성을 끄지 않는다.

OS·버전·커밋, setup·로그인·기능 시험·stop/up 데이터 보존 결과를 Linear에 기록한다. 팀원 PC 재현과 Codex 환경 검증은 구분한다.

이번 환경의 직접 검증 결과와 미검증 범위는 [검증 기록](local-compose-verification.md)을 참고한다.

설계 참고: [Compose 외부 네트워크](https://docs.docker.com/compose/how-tos/networking/), [환경 파일](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/). 환경 파일은 backend 런타임에만 전달하고 이미지 빌드 문맥에서 비밀 파일을 제외한다.
