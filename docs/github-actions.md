# GitHub Actions와 배포 검사

Staging 보호의 설정안·MEG-168 제품 CI 의존성·관리자 적용 및 안전한 차단 시험은 [Staging 브랜치 보호](staging-protection.md)를 따른다. 설정 파일의 존재나 PR 병합은 실제 ruleset 적용을 뜻하지 않는다.

이 문서는 저장소의 워크플로와 제품 CI 연결 절차를 설명한다. 기준은 [Product tests](../.github/workflows/product-ci.yml), [PR metadata](../.github/workflows/pr-metadata.yml), [Infra CD](../.github/workflows/infra-cd.yml), [DB Backup](../.github/workflows/db-backup.yml), [운영 절차](harness/ops.md)다. 워크플로 파일과 원격 required checks 설정은 별개이며, 필수 검사 연결은 사람이 확인한다.

## 현재 자동화 범위

| 실행 주체 | 실행 조건 | 확인하거나 수행하는 것 | 보장하지 않는 것 |
|---|---|---|---|
| GitHub Actions: Product tests | main·staging·기능 통합 브랜치(`meg-<번호>-integration`) 대상 PR, main·staging push. 문서도 실행 | 단위·격리 SQL·lint/build·합성 화면 시험, 미실행/skip 차단 | 실환경 DB·로그인·AI, 배포 차단, 사람의 출시 승인 |
| GitHub Actions: PR metadata | PR 생성·수정·재오픈·새 커밋·리뷰 준비 전환 | 제목·소스 브랜치·본문 형식 | 제품 테스트, AC 충족, 배포 정상 동작 |
| GitHub Actions: Release tree check | main 대상 PR(`pull_request_target`)과 main push | 후보 브랜치·STG 수락 태그·전체 트리 일치 | STG E2E의 실제 내용, 필수 검사·Deployment Checks 연결(사람 설정) |
| GitHub Actions: Infra CD | `main`의 지정된 Terraform 파일 변경 push 또는 수동 실행 | Terraform plan, 변경이 있으면 승인 절차 후 저장된 plan 적용 | 프론트·백엔드 배포 및 API 정상 동작 |
| GitHub Actions: DB Backup | 매주 월요일 03:00 KST 예약 실행 또는 수동 실행 | 운영 DB 덤프와 이미지 파일을 비공개 S3 버킷에 업로드, 이미지 파일·표 행 대조 | 백업 내용의 복원 가능성(복원 시험은 사람이 따로 한다) |
| Vercel Git integration | 연결된 브랜치의 배포 이벤트와 프로젝트 설정 | Vercel 빌드·배포 | GitHub Actions 제품 테스트 실행, 런타임 헬스체크 성공 |

Vercel의 PR 배포 상태나 봇 댓글은 Vercel 연동에서 제공한다. 이 저장소에는 Vercel CLI로 앱을 배포하는 GitHub Actions 워크플로가 없다. Production·Staging 구성과 헬스체크 절차는 [배포 가이드](deployment-guide.md)를 따른다.

## PR metadata

`pull_request_target`의 `opened`, `edited`, `reopened`, `synchronize`, `ready_for_review` 이벤트로 실행한다. 기본 브랜치의 워크플로를 사용하므로 PR에서 검사 코드를 수정해도 병합 전 검사에는 반영되지 않는다. PR 코드를 checkout하거나 실행하지 않고 제목·본문·소스 브랜치명만 검사한다. 워크플로 권한은 `permissions: {}`다.

필수 검사 이름은 **Check PR metadata**다. 검사 항목은 다음과 같다.

- 제목: `<type>(MEG-N): <설명>`. type은 `feat`, `fix`, `docs`, `chore` 중 하나다.
- 소스 브랜치: `meg-<번호>-<짧은-설명>`. 설명은 소문자·숫자·하이픈으로 작성한다.
- 제목과 브랜치의 이슈 ID 일치, 본문에 해당 이슈 ID 존재.
- `[MEG-N]` 자리표시자, 내용 없는 AC 항목, 내용 없는 `검증:` 항목이 남지 않았는지 확인.

예: 브랜치 `meg-123-api-docs`, 제목 `docs(MEG-123): API 사용 가이드 추가`. 본문은 [PR 템플릿](../.github/pull_request_template.md)을 채운다. 검사 통과와 별도로 리뷰어가 이슈 범위, AC별 검증 근거, 미검증 항목을 확인한다.

### Staging에서 운영으로 반영할 때의 제한

**`staging`을 소스 브랜치로 하는 `staging → main` PR은 현재 브랜치명 검사에 실패한다.** 대상 브랜치에 따른 예외가 없으므로 `meg-<번호>-<설명>` 규칙을 만족해야 한다. Vercel의 Staging 배포가 성공해도 이 제한은 사라지지 않는다.

운영 반영은 릴리스 흐름 v3(MEG-216)를 따른다. main PR은 STG에서 검증한 릴리스 후보 브랜치 `meg-<번호>-release`에서만 연다. 아래 Release tree check가 이를 확인한다. 단계별 순서와 기록 양식은 [출시 절차](release.md)를 따른다. 어느 경우든 필수 검사를 우회하지 않는다.

## Release tree check

릴리스 흐름 v3(MEG-216)에서는 STG에서 수락한 전체 트리만 main에 들어간다. [Release tree check](../.github/workflows/release-tree-check.yml)는 모든 main PR과 main push에서 다음을 확인하고, 하나라도 어긋나면 실패한다.

1. PR의 출발 브랜치가 이 저장소의 `meg-<번호>-release`다.
2. 태그 `stg-accepted/meg-<번호>`가 있다. 태그는 묶음 E2E를 수락한 뒤 관리자가 STG 반영 PR의 병합 커밋에 만든다. STG 반영은 staging을 후보의 전체 내용으로 덮어쓰므로 이 커밋의 트리는 후보와 같아야 한다.
3. PR이 최신 main을 포함한다(`heads/main`의 SHA 기준 `behind_by == 0`).
4. PR head(또는 main 병합 커밋)의 트리가 태그 커밋의 트리와 같다.

PR 검사는 `pull_request_target`이라 PR의 기준(base) 커밋에 있는 workflow와 스크립트(`.github/scripts/release_tree_check.py`)만 실행하고 PR 코드는 받지 않는다. push 검사도 병합 직전 main(`github.event.before`)의 스크립트를 쓴다. 따라서 후보가 자신을 판정하는 스크립트를 바꿀 수 없다. 권한은 `contents: read`, `pull-requests: read`뿐이며 비밀값을 쓰지 않는다. 태그를 PR을 연 뒤에 만들었다면 해당 PR의 Release tree check를 다시 실행한다. 검사는 실행 시점의 태그를 읽는다. 병합 직후에는 커밋과 PR의 연결이 늦게 보일 수 있어 push 검사는 최대 35초 동안 다시 조회한다.

이 검사가 실제로 막으려면 사람이 아래를 설정해야 한다(MEG-218).

- main ruleset의 필수 검사에 `Release tree check`를 더한다. 기존 strict(최신 base 필수) 설정과 squash 전용 병합을 유지한다. strict가 없으면 main이 바뀐 뒤에도 PR의 이전 통과 결과가 남는다.
- Vercel Deployment Checks에 `Release tree check`를 Blocking으로 등록한다.
- tag ruleset으로 `stg-accepted/*`의 생성·수정·삭제·강제 이동을 모두 막고 관리자만 우회하게 한다. 생성만 막으면 쓰기 권한이 있는 계정이 태그를 다른 커밋으로 옮길 수 있다.
- main ruleset의 우회(bypass) 대상은 비워 둔다. push 검사는 PR 없이 직접 push한 변경을 실패로 처리하지만, 우회 권한이 있으면 병합 자체를 막지 못한다.

남은 위험도 있다. 같은 이름의 검사를 다른 workflow가 보고할 수 있다는 기존 지적(실제 재현은 안 함)이 있으므로 `.github/workflows/` 변경은 Code Owner가 검토한다. "최신 main 포함"은 이력만 확인하므로, 후보가 main 변경을 되돌린 내용이라도 STG에서 수락한 트리라면 통과한다. 이런 되돌림은 STG 반영 PR과 main PR의 Code Owner 리뷰에서 걸러야 한다.

이 검사를 처음 main에 넣은 병합(MEG-218, PR #161)의 push 검사는 스크립트를 찾지 못해 실패했다. push 검사는 병합 직전 main의 스크립트를 쓰는데, 그 커밋에는 스크립트가 아직 없었기 때문이다. 이 실패는 첫 병합에서만 생기고 이후 push에서는 반복되지 않는다.

그 뒤 첫 v3 출시 전의 main push는 후보 브랜치가 아니므로 검사가 실패한다. Vercel Deployment Checks에 `Release tree check`를 Blocking으로 등록해 두었다면 이 push의 Production 배포는 운영 도메인을 할당받지 못한다. 출시 전에 main에 병합하는 변경이 있으면 이 점을 고려한다.

## Infra CD

자동 실행 조건은 `main` push 중 다음 경로의 변경이다.

- `infra/*.tf`
- `infra/.terraform.lock.hcl`

`infra/README.md`나 예시 파일만 바뀌면 자동 실행하지 않는다. `infra/github-oidc/` 등 하위 폴더의 역할 코드도 이 경로 필터의 대상이 아니다. PR 트리거는 없으며 PR 검토 단계에서는 로컬 plan을 사용한다. `workflow_dispatch`로 수동 실행할 수도 있으나 Environment와 OIDC의 브랜치 제한은 별도로 적용된다.

`Plan` 작업은 `infra-plan` Environment에서 OIDC로 AWS에 연결해 Terraform plan을 만든다. 변경이 없으면 `Apply`를 건너뛴다. 변경이 있으면 plan을 비공개 상태 버킷에 저장하고, `Apply` 작업은 `infra-apply` Environment의 사람 승인 후 동일 plan을 내려받아 적용한다. 필수 승인자는 YAML이 아니라 GitHub Environment 설정에서 구성하므로 실제 설정도 확인해야 한다.

동시 실행 그룹은 `infra-cd`이며 진행 중인 실행을 새 실행이 취소하지 않도록 설정되어 있다. 각 작업의 제한 시간은 20분이다. 상태가 달라져 저장된 plan을 적용할 수 없으면 실패를 조사하고 새 plan과 승인을 거친다.

Environment에서 사용하는 비밀값 이름은 `AWS_ROLE_ARN`, `TF_STATE_BUCKET`, `TF_VARS_JSON`이다. 값·계정 식별자·전체 Terraform 출력·plan 파일을 공개 로그나 PR에 붙이지 않는다. 워크플로는 요약과 리소스 주소를 출력하고 plan을 공개 아티팩트 대신 비공개 버킷에 보관한다. 설정·운영 상세는 [인프라 가이드](../infra/README.md)의 “CD로 적용” 절을 따른다.

## DB Backup

[DB Backup](../.github/workflows/db-backup.yml)은 `schedule`(매주 일요일 18:00 UTC)과 `workflow_dispatch`로만 실행한다. PR·push 트리거는 없다. `db-backup` Environment(배포 브랜치 `main`만)에서 OIDC로 백업 전용 역할을 받아 S3에 올린다. 이 역할은 업로드만 할 수 있고 백업을 읽거나 지울 수 없다.

Environment 비밀값 이름은 `AWS_ROLE_ARN`, `BACKUP_BUCKET`, `SUPABASE_DB_URL`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`이고, 변수 이름은 `GLOSSARY_IMAGE_BUCKET`, `NOTE_IMAGE_BUCKET`이다. 공개 로그에는 파일 이름·크기·시각과 이미지 대조 개수만 남기고 덤프 내용·행 수·CLI 출력은 남기지 않는다. 설정·복원 절차는 [인프라 가이드](../infra/README.md)의 "DB·이미지 백업" 절을 따른다.

## 제품 테스트 CI (MEG-168)

`Product tests`는 `pull_request`의 병합 결과와 main·staging push 커밋을 검사한다. PR 대상에는 main·staging과 함께 기능 통합 브랜치(`meg-*-integration`)가 들어간다. 통합 브랜치 보호(ruleset)는 사람이 따로 설정한다(MEG-219). checkout의 기본 ref를 사용하고 자격증명을 저장하지 않는다. 경로 필터가 없어 문서 PR도 결과가 보고된다. 동일 PR/브랜치의 이전 실행은 취소하며, 네 job 중 실패·취소·skip이 하나라도 있으면 최종 **Product CI**는 성공하지 않는다. CI 자체에는 배포 명령이 없고 Vercel Git 연동은 별도로 동작한다.

| check 이름 | 실행 범위 |
|---|---|
| Product backend unit | `tests/`에서 `integration/`과 `test_account_issuance_local.py`를 제외한 pytest 전체 |
| Product backend SQL | `tests/integration/` 전체. 격리된 PostgreSQL에서 실제 SQL 함수 검사 |
| Product frontend build | lint와 TypeScript·Vite build |
| Product frontend E2E | 기본 Playwright + notes 전용 설정. 로컬 서버와 합성 데이터만 사용 |
| Product CI | 위 네 결과가 모두 success인지 확인하는 최종 필수 검사 후보 |

### 재현 명령과 미실행 방지

버전은 workflow의 Node·uv 설정과 `backend/.python-version`, 두 잠금 파일을 따른다. Playwright와 Chromium은 `npm ci`로 설치된 Playwright 버전이 선택한다.

백엔드 (`backend/`):

```bash
uv sync --locked
uv run --no-sync pytest tests --ignore=tests/integration --ignore=tests/test_account_issuance_local.py --junitxml=unit-results.xml -q
uv run --no-sync python scripts/check_test_report.py unit-results.xml
```

SQL은 workflow에 고정된 PostgreSQL 이미지로 `--network none` 컨테이너를 만들고 `pg_isready`로 준비 완료를 기다린다. 공개 포트를 열지 않으며 컨테이너 내부 연결만 허용한다. `AI_LEDGER_TEST_CONTAINER`, `GLOSSARY_SQL_TEST_CONTAINER`, `NOTION_IMPORT_TEST_CONTAINER`를 그 컨테이너 이름으로 설정한 뒤 아래 명령을 실행한다. 실행 종료 시 성공·실패와 관계없이 **직접 만든 해당 컨테이너만** 제거한다. 로컬의 기존 DB나 원격 Supabase를 사용하지 않는다.

```bash
uv run --no-sync pytest tests/integration --junitxml=sql-results.xml -q
uv run --no-sync python scripts/check_test_report.py sql-results.xml
```

프론트 (`frontend/`, Bash 예시):

```bash
uv sync --locked --directory ../backend
npm ci
npm run lint
npm run build
npx --no-install playwright install --with-deps chromium
CI=true PLAYWRIGHT_JUNIT_OUTPUT_FILE=test-results/mock.xml npm run test:e2e -- --reporter=list,junit
python ../backend/scripts/check_test_report.py test-results/mock.xml
CI=true PLAYWRIGHT_JUNIT_OUTPUT_FILE=test-results/notes.xml npm run test:e2e:notes -- --reporter=list,junit
python ../backend/scripts/check_test_report.py test-results/notes.xml
```

notes 시험 일부는 Python의 Notion 변환기로 합성 입력을 만들므로 E2E job에도 uv·Python·백엔드 잠금 의존성을 설치한다. 원격 Notion이나 DB를 호출하지 않는다.

각 테스트 명령이 성공한 뒤 JUnit 검사를 실행한다. 보고서 누락·파싱 오류·0개 testcase·skip·실패·error는 모두 거부한다. 필수 실행에만 적용하며 기본 로컬 pytest의 opt-in 동작은 바꾸지 않는다. 테스트 수는 현재 커밋의 결과로 기록하며 과거 숫자를 하드코딩하지 않는다. `test.only`는 CI에서 거부한다.

`test_account_issuance_local.py`는 별도 일회용 Supabase를 요구하므로 이 CI에서 명시적으로 제외한다. `e2e-deployed/`는 배포 주소·시험 계정을 요구하는 별도 실환경 검증이다. 두 항목은 Product CI 성공으로 검증됐다고 보고하지 않는다. Windows에서 심볼릭 링크 권한이 없어 로컬 백업 시험이 skip되면 보고서 검사도 실패한다. Ubuntu CI 결과와 구분하여 기록한다.

### 권한과 필수 검사 연결

PR job은 `contents: read`만 사용한다. 운영 비밀값·GitHub Environment·OIDC·배포 권한을 제공하지 않는다. Actions는 전체 commit SHA에 고정하고 의존성은 잠금 파일로 설치한다. 결과 파일·브라우저 trace를 공개 아티팩트로 업로드하지 않는다. 기존 metadata의 `pull_request_target`에는 제품 코드를 추가하지 않는다.

사람이 실제 실행을 확인한 뒤 main ruleset에서 다음을 적용한다. 파일 병합만으로 자동 설정되지 않는다.

1. **Product CI**, 출처 **GitHub Actions**(실제 check의 app ID 대조)를 추가한다. 기존 **Check PR metadata**는 유지한다.
2. 최신 main과 합친 검사 결과를 요구하도록 strict 설정을 검토·적용한다. 승인 1명·Code Owner·새 push 승인 취소·AI 우회 불가를 유지한다.
3. 별도 실패 시험 PR에서 실패/미완료 시 병합 차단, 수정 후 검사 성공, 문서 변경 결과를 확인하고 시험 PR은 병합 없이 닫는다.
4. staging의 같은 검사 연결은 MEG-169에서 수행한다. 이슈 ID 소스 브랜치로 staging 대상 PR을 열어 결과를 확인한다.

이름과 출처 앱을 지정해도 동일 앱이 실행하는 다른 workflow까지 고정하지는 못한다. 사람은 workflow 변경 자체를 검토해야 한다. Product CI는 실환경 DB·Auth·AI 검증이나 운영 배포 게이트가 아니다. `/api/health` 또한 API 기동만 확인하며 DB 연결을 보장하지 않는다.

## 결과 확인과 실패 대응

1. PR의 **Checks**에서 `Check PR metadata`와 외부 배포 검사를 각각 확인한다. GitHub Actions 실행 상세에서는 실패한 작업·단계와 해당 커밋을 확인한다.
2. Metadata 실패는 로그에 표시된 제목·본문·소스 브랜치 형식을 고친다. `staging` 브랜치 자체가 원인이면 재실행만으로 해결되지 않으므로 위 운영 반영 절차를 따른다.
3. Infra CD 실패는 `Plan` 또는 `Apply` 중 어느 단계인지 확인한다. Environment 승인 대기와 실패를 구분하고, OIDC·상태 버킷·입력 설정은 권한 있는 담당자가 확인한다. 숨겨진 출력을 공개 로그로 풀지 않는다.
4. Vercel 빌드 실패는 해당 배포의 build logs를 확인한다. 배포가 Ready인데 `/api/health`가 500이면 runtime logs와 대상 환경의 설정을 확인한다. 빌드 성공만으로 서버 기동 성공을 판단하지 않는다.
5. 수정 후 필요한 검사를 다시 실행하고 AC별 결과와 남은 미검증 항목을 PR에 기록한다. 사람 Code Owner가 승인하고 병합한다. 에이전트는 병합·auto-merge·우회 병합을 하지 않는다.

GitHub Actions의 기존 실행을 재실행하면 원래 이벤트의 `GITHUB_SHA`와 `GITHUB_REF`를 재사용한다. 수정 내용을 검증할 때는 새 이벤트·수정 커밋에 해당하는 실행 결과를 확인한다. [GitHub 공식 문서: 워크플로 및 작업 재실행](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)
