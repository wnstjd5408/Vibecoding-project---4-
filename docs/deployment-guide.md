# 배포 환경과 헬스체크 가이드

공개 가능한 설정 방법을 정리한 문서다. 실제 프로젝트 주소·배포 ID·커밋별 검증 결과는 접근이 제한된 내부 배포 기록에서 확인한다. 아래 `<production-origin>`, `<staging-origin>`, `<preview-origin>`은 `https://호스트` 형태의 실제 출처로 바꿔 사용한다. 요구사항과 완료 판단의 원본은 승인된 Linear 명세와 작업 기록이다.

## 환경 구분

| 용도 | Git 브랜치 | Vercel 환경 | 주소 표기 |
|---|---|---|---|
| 운영 | `main` | Production | `<production-origin>` |
| 프론트·백엔드 통합 테스트 | `staging` | Preview, 브랜치 지정 | `<staging-origin>` |
| 변경 사항별 리뷰 | 이슈별 작업 브랜치·PR | Preview | `<preview-origin>` |

Staging은 Hobby에서 제공하는 Preview 배포에 `staging` 브랜치를 연결한 구성이다. 별도 Custom Environment를 만들지 않는다. 운영 브랜치가 `main`인지 프로젝트 설정에서 확인한다. Staging의 고정 브랜치 URL은 브랜치의 최신 배포로 바뀌므로, 검증 기록에는 배포 고유 URL과 커밋 SHA도 남긴다.

Vercel은 기본 Production·Preview 환경을 제공하며, Preview 브랜치와 브랜치별 환경변수로 테스트 환경을 구성할 수 있다. Custom Environments는 Pro·Enterprise 대상이다. [Vercel 환경 구성](https://vercel.com/docs/deployments/environments), [배포 URL](https://vercel.com/docs/deployments/generated-urls)

Hobby는 비상업적 개인 용도에 한정된다. 환경 분리 기능 지원 여부와 실제 프로젝트의 이용 조건 충족 여부는 각각 확인한다. 이 문서는 상업적 운영을 무료 플랜으로 승인하는 근거가 아니다. [Vercel Fair Use Guidelines](https://vercel.com/docs/limits/fair-use-guidelines#commercial-usage)

## 환경변수 설정

Vercel 프로젝트의 **Settings → Environment Variables**에서 환경을 선택해 등록한다. 값은 저장소·PR·로그에 복사하지 않는다. 전체 변수 이름과 용도는 [아키텍처의 환경변수 목록](architecture.md#8-외부-의존성--환경변수)을 따른다.

| 이름 | Production | Preview의 `staging` 브랜치 | PR Preview |
|---|---|---|---|
| `ALLOWED_ORIGINS` | `<production-origin>` | `<staging-origin>` | 필요한 경우 해당 테스트 출처만 명시 |
| `VITE_API_MOCK` | 미설정 또는 `false` | 미설정 또는 `false` | 실제 연동 검증은 미설정 또는 `false` |
| `SUPABASE_URL` | 운영 프로젝트 URL | 스테이징 프로젝트 URL | 필요한 경우 승인된 테스트 프로젝트만 사용 |
| `SUPABASE_SECRET_KEY` | 운영 프로젝트 Secret Key | 스테이징 프로젝트 Secret Key | 운영 키 사용 금지 |
| AI 자격증명 | 운영 전용 | 필요 시 별도 테스트 자격증명 | 승인된 테스트 자격증명만 사용 |

1. Production의 `ALLOWED_ORIGINS`를 설정한다.
2. Preview를 선택하고 Git Branch를 `staging`으로 지정해 같은 이름의 변수를 등록한다. 같은 이름의 Preview 공통값보다 브랜치별 값이 우선한다.
3. 운영 비밀값을 Preview 공통값으로 복사하지 않는다. 브랜치·배포 분리만으로 DB·Auth·AI 자원이 분리되는 것은 아니다. 테스트 자원과 권한은 별도로 준비하고 검증한다.
4. 변경한 환경과 브랜치를 대상으로 새 배포를 만든다. 환경변수 변경은 기존 배포에 소급 적용되지 않는다. [Vercel 환경변수](https://vercel.com/docs/environment-variables)

`ALLOWED_ORIGINS`는 `scheme://host[:port]` 목록을 쉼표로 구분한다. 경로·질의 문자열·와일드카드는 허용하지 않는다. 상태 변경 요청의 Origin 검사와 CORS에 사용된다. Production에서 누락하면 서버 시작 자체가 실패한다. Preview에서 누락하면 로컬 개발 출처가 기본값이므로, GET 헬스체크 성공만으로 Preview의 상태 변경 API가 정상이라고 판단하지 않는다. 기준 구현은 [`backend/app/config.py`](../backend/app/config.py)다.

### Supabase 운영·스테이징 연결

Supabase는 서울(`ap-northeast-2`)의 별도 프로젝트 두 개로 운영과 스테이징을 구분한다. Vercel 함수 지역은 기존 도쿄(`hnd1`) 설정을 유지한다. Supabase 프로젝트를 분리하면 DB·Auth·Storage도 각각 별도로 관리되며, 환경변수 등록만으로 스키마나 데이터가 복제되지는 않는다.

1. 각 Supabase 프로젝트의 **Settings → API Keys**에서 백엔드용 Secret Key를 확인하거나 생성한다. Supabase 키의 표시 이름은 용도를 구분하는 이름으로 정한다(예: `vercel-production-backend`, `vercel-staging-backend`).
2. Vercel에는 두 항목 모두 **동일한 변수 이름 `SUPABASE_SECRET_KEY`**로 등록한다. 운영 키는 **Production만**, 스테이징 키는 **Preview Branches → staging만** 선택한다. 스테이징 항목에 Production이 함께 선택되어 있지 않은지 확인한다. 표시 이름과 애플리케이션이 읽는 환경변수 이름은 서로 다르다.
3. 키는 사람이 Vercel에 직접 입력하고 타입은 **Secret**으로 저장한다. `SUPABASE_URL`은 각 키와 같은 프로젝트의 URL을 **Config**로 등록한다. 키 값은 채팅·이슈·PR·로그에 기록하지 않고, 프론트엔드 변수로 전달하지 않는다.
4. 변수 이름·타입·환경·브랜치 범위를 확인한 뒤 각 환경을 재배포한다. Secret Key를 읽어 확인하는 대신 실제 백엔드 요청의 성공 여부로 인증과 연결을 검증한다. [Supabase API Keys](https://supabase.com/docs/guides/getting-started/api-keys)

이전할 때는 원본의 테이블별 행 수, Auth 사용자, Storage 버킷·파일과 마이그레이션 이력을 먼저 확인한다. 사용자 데이터가 없더라도 스키마 적용 후 테이블·RLS·함수·제약을 대조한다. 데이터가 있으면 승인된 백업·복원 절차와 별도 Storage 파일 이전이 필요하다. 운영 사용자 데이터를 스테이징에 자동 복제하지 않는다. 원본은 이전 검증과 사람의 전환 수락 전까지 보존한다.

검증은 다음 세 단계로 나누어 기록한다.

| 단계 | 확인하는 것 | 성공만으로 보장하지 않는 것 |
|---|---|---|
| 설정 | 변수 이름·타입·환경 범위, 스키마 대조 | 입력한 키의 유효성, 실제 DB 연결 |
| 서버 기동 | 배포 Ready 및 `/api/health`의 200 JSON 응답 | DB·Auth·AI 연결 |
| 실제 연동 | 해당 환경 백엔드에서 승인된 DB 조회와 Auth 흐름 수행 | 다른 환경의 정상 동작 |

DB 조회 엔드포인트가 아직 없으면 실제 연결 검증은 미완료로 남긴다. 헬스체크 계약을 외부 의존성 검사로 바꾸거나, 키 등록만으로 연결 성공을 선언하지 않는다.

## 배포와 운영 반영

루트 [`vercel.json`](../vercel.json)은 Services(Beta)로 `frontend/`의 Vite와 `backend/`의 FastAPI를 함께 배포한다. 함수 지역 설정값은 `hnd1`이며 실제 실행 지역은 배포·런타임 정보로 별도 확인한다. `/api/*` 경로는 그대로 백엔드에 전달한다. `/health`도 백엔드로, 나머지는 프론트로 연결한다. 프론트의 깊은 경로는 `index.html`로 연결한다.

1. 이슈별 브랜치에서 PR을 열고 코드·문서 검증 결과를 기록한다. PR Preview에서 해당 변경을 확인한다.
2. 사람의 검토를 거쳐 테스트할 변경을 `staging`에 반영한다. PR 병합은 사람이 수행하며 에이전트는 병합·auto-merge·우회 병합을 하지 않는다. 테스트 브랜치를 강제로 덮어쓰지 않는다.
3. Vercel에서 대상이 Preview이고 Git 브랜치가 `staging`인지 확인한 뒤 아래 절차로 검증한다.
4. `main` 반영 PR은 저장소 규칙에 맞는 이슈 ID 브랜치에서 만든다. `staging`에서 `main`으로 직접 PR을 만들면 브랜치 메타데이터 규칙을 충족하지 못한다. 사람 Code Owner가 검토·승인한 PR을 병합한다. Staging에서 검증한 커밋과 PR head가 다르면 같은 코드가 검증됐다고 간주하지 않고 변경분을 확인·재검증한다. Production 배포의 커밋이 병합 결과와 일치하는지 확인하고 운영에서도 재검증한다.
5. 환경·브랜치·커밋·배포 ID·검증 시각·결과·미검증 항목·사람의 출시 수락을 내부 배포 기록에 남긴다.

Vercel의 Git 연동 배포와 GitHub Actions 검사는 서로 다른 작업이다. 빌드 Ready나 PR 메타데이터 검사 성공만으로 제품 테스트 통과를 뜻하지 않는다. 현재 자동화 범위와 수동 검증 명령은 [GitHub Actions 가이드](github-actions.md)를 따른다.

## 프론트 헬스체크 사용법

동일 출처의 상대경로 `GET /api/health`를 호출한다. 인증 쿠키나 DB·Auth·AI 자격증명은 필요하지 않다. 단, Production의 서버 기동 설정은 충족해야 한다.

```ts
const response = await fetch('/api/health', { cache: 'no-store' })
const body = await response.json()
const healthy = response.status === 200 && body.status === 'ok'
```

기존 프론트 코드에서는 공통 `apiFetch`를 사용한다.

```ts
apiFetch<{ status: string }>('/api/health')
```

정상 응답은 `200 {"status":"ok"}`, `Cache-Control: private, no-store`다. API 서버가 응답한다는 의미이며 DB·Auth·AI 연결, 로그인, 제품 API의 정상 동작을 보장하지 않는다. 기존 `/health`는 호환용이고 신규 연동은 `/api/health`를 사용한다.

### 실제 배포 확인

1. 내부 배포 기록에서 검증할 환경의 주소와 커밋을 확인한다.
2. 보호된 배포는 Vercel 로그인 또는 권한자가 발급한 공유 링크로 접근한다. 공유 링크·우회 토큰을 공개 저장소나 로그에 남기지 않는다. 접근 권한이 없다는 이유로 보호 설정을 해제하지 않는다.
3. `<staging-origin>/dev/foundation` 또는 검증 대상 출처의 같은 경로를 연다.
4. 응답 출처가 **실제 백엔드**인지 확인한다. `VITE_API_MOCK=true`의 가짜 `ok`는 연결 증거가 아니다. Vite 환경변수는 빌드에 반영되므로 변경 후 새 빌드가 필요하다.
5. 브라우저 Network에서 `/api/health`의 요청 출처, HTTP 200, JSON 본문, 캐시 헤더를 확인한다. 인증 페이지 HTML을 성공 응답으로 세지 않는다.
6. 첫 화면과 `/dev/foundation` 새로고침도 확인한다. 화면 렌더링을 확인하지 못했다면 HTTP 확인과 구분해 기록한다. 데모의 다른 미구현 API에서 발생하는 오류는 헬스체크와 별도로 기록한다.

로그인 보호가 없는 주소 또는 별도로 접근이 승인된 환경에서는 다음처럼 HTTP 응답을 확인할 수 있다. 일반 `curl`에는 브라우저의 Vercel 로그인 세션이 전달되지 않는다.

```bash
curl -i '<staging-origin>/api/health'
```

### 실패 시 확인 순서

| 증상 | 확인할 항목 |
|---|---|
| 로그인 화면·리다이렉트·접근 거부 | Vercel 배포 보호와 접근 권한. 앱의 인증 오류와 구분 |
| 500 / `FUNCTION_INVOCATION_FAILED` | 함수 Runtime Logs와 서버 시작 오류. Production의 `ALLOWED_ORIGINS` 누락·형식 검사 |
| `/api/health`에서 404 또는 HTML | 배포 커밋, 루트 `vercel.json`, `/api` 경로 보존, 실제 요청 주소 |
| 헬스체크는 성공하나 상태 변경 API 실패 | 해당 환경의 `ALLOWED_ORIGINS`, 실제 Origin, API별 인증·외부 의존성 |
| 화면만 `ok`, 네트워크 요청 없음 | `VITE_API_MOCK`와 현재 빌드의 응답 출처 |

Ready 상태는 빌드 완료를 나타내며 함수 호출 성공을 보장하지 않는다. 설정을 수정한 뒤 올바른 환경으로 재배포하고 동일 검증을 반복한다. 장애 시 사람 운영자가 알려진 정상 배포와 변경 내용을 확인해 복구를 결정하며, 프론트·백엔드 배포 복구가 DB 변경까지 되돌리지는 않는다.

## 검증 상태와 남은 작업

2026-10-29 내부 작업 기록 기준으로 운영·스테이징의 Supabase 스키마 구성과 `ALLOWED_ORIGINS`·`SUPABASE_URL`·`SUPABASE_SECRET_KEY`의 환경별 등록이 확인됐다. 재배포 후 두 환경 모두 Ready 및 `/api/health`의 200 JSON 응답을 확인했다. 이전에 기록된 Production의 `ALLOWED_ORIGINS` 누락 장애는 해소됐다.

실제 Vercel 백엔드의 DB 조회, Secret Key 유효성, Auth 설정·로그인 흐름 및 AI 필수 환경변수·연결은 아직 검증 완료로 기록하지 않았다. 전체 완료 여부는 이 항목들과 사람의 수락을 포함해 판단한다.

이 문서의 작성 또는 병합은 위 작업의 완료 선언이 아니다. 최신 상태는 내부 배포 기록에서 확인하고, 운영 설정과 재배포 후 검증 증거가 모인 뒤 사람이 해당 이슈의 완료를 수락한다. 플랫폼 정책의 공식 문서는 Context7과 원문으로 2026-10-28 확인했다.
