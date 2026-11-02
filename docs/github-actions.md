# GitHub Actions와 배포 검사

이 문서는 저장소의 현재 워크플로를 설명한다. 제품 테스트 CI 추가나 브랜치 정책 변경은 포함하지 않는다. 기준은 [PR metadata](../.github/workflows/pr-metadata.yml), [Infra CD](../.github/workflows/infra-cd.yml), [DB Backup](../.github/workflows/db-backup.yml), [운영 절차](harness/ops.md)다.

## 현재 자동화 범위

| 실행 주체 | 실행 조건 | 확인하거나 수행하는 것 | 보장하지 않는 것 |
|---|---|---|---|
| GitHub Actions: PR metadata | PR 생성·수정·재오픈·새 커밋·리뷰 준비 전환 | 제목·소스 브랜치·본문 형식 | 제품 테스트, AC 충족, 배포 정상 동작 |
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

운영 반영은 이슈별 브랜치에서 `main`으로 PR을 열어 필수 검사와 사람 Code Owner 승인을 받고 사람이 병합하는 기존 절차를 따른다. Staging에서 검증한 변경과 운영 PR의 커밋·차이를 확인하고 검증 근거를 PR에 남긴다. Staging 전체를 한 번에 승격하는 절차는 현재 자동화되어 있지 않다. 필요하면 별도 이슈에서 브랜치·릴리스 정책을 결정하며, 필수 검사를 우회하거나 이 문서 작업에서 워크플로를 변경하지 않는다.

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

## 제품 테스트의 현재 상태

현재 워크플로 세 개에는 `pytest`, 프론트 lint·build, 배포 후 헬스체크를 수행하는 제품 테스트 CI가 없다. Vercel 빌드 성공이나 metadata 검사 통과를 제품 테스트 통과로 기록하지 않는다.

변경 범위에 맞는 검증을 로컬에서 실행하고 PR에 결과를 남긴다.

| 작업 디렉터리 | 검증 명령 |
|---|---|
| `backend/` | `uv sync`, `uv run pytest` |
| `frontend/` | `npm install`, `npm run lint`, `npm run build` |

배포 후에는 대상 환경·배포 커밋을 확인하고 `GET /api/health`가 `200 {"status":"ok"}`인지 별도로 확인한다. 이 응답은 API 서버의 응답 가능 여부만 뜻하며 DB·Auth·AI 연결 정상 여부를 보장하지 않는다.

제품 테스트 CI 도입은 별도 범위다. [운영 절차](harness/ops.md)의 CI 규칙에 따라 관련 테스트를 실행하고 실제 보고된 검사 이름을 required checks에 연결해야 한다. 이 문서는 CI가 추가되었거나 그 요구를 충족했다고 선언하지 않는다.

## 결과 확인과 실패 대응

1. PR의 **Checks**에서 `Check PR metadata`와 외부 배포 검사를 각각 확인한다. GitHub Actions 실행 상세에서는 실패한 작업·단계와 해당 커밋을 확인한다.
2. Metadata 실패는 로그에 표시된 제목·본문·소스 브랜치 형식을 고친다. `staging` 브랜치 자체가 원인이면 재실행만으로 해결되지 않으므로 위 운영 반영 절차를 따른다.
3. Infra CD 실패는 `Plan` 또는 `Apply` 중 어느 단계인지 확인한다. Environment 승인 대기와 실패를 구분하고, OIDC·상태 버킷·입력 설정은 권한 있는 담당자가 확인한다. 숨겨진 출력을 공개 로그로 풀지 않는다.
4. Vercel 빌드 실패는 해당 배포의 build logs를 확인한다. 배포가 Ready인데 `/api/health`가 500이면 runtime logs와 대상 환경의 설정을 확인한다. 빌드 성공만으로 서버 기동 성공을 판단하지 않는다.
5. 수정 후 필요한 검사를 다시 실행하고 AC별 결과와 남은 미검증 항목을 PR에 기록한다. 사람 Code Owner가 승인하고 병합한다. 에이전트는 병합·auto-merge·우회 병합을 하지 않는다.

GitHub Actions의 기존 실행을 재실행하면 원래 이벤트의 `GITHUB_SHA`와 `GITHUB_REF`를 재사용한다. 수정 내용을 검증할 때는 새 이벤트·수정 커밋에 해당하는 실행 결과를 확인한다. [GitHub 공식 문서: 워크플로 및 작업 재실행](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)
