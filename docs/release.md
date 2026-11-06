# 출시 절차 (릴리스 흐름 v3)

이 문서는 여러 개발건을 STG에서 묶어 검증하고 STG에서 수락한 것과 같은 코드를 Production에 내보내는 순서를 정한다. 결정의 원본은 Linear MEG-216의 결정 기록(ADR-1~3)이고 2026-11-05 첫 출시(MEG-220)에서 처음 끝까지 실행했다. 이 문서는 공개 가능한 요약이다. 실제 주소·배포 ID·계정 정보는 적지 않고 Linear 릴리스 이슈에 기록한다.

## 먼저 읽을 것

- **같은 버전은 같은 전체 트리다.** 후보 R, STG에 반영한 커밋 S, main 병합 커밋 P의 git 트리가 모두 T로 같아야 한다. Production은 운영 환경변수로 새로 빌드한다. Vercel promote로 STG 배포를 운영에 올리지 않는다.
- **main PR은 후보 브랜치 `meg-<번호>-release`에서만 연다.** [Release tree check](github-actions.md#release-tree-check)가 브랜치 이름, 보호 태그, 최신 main 포함 여부, 트리 일치를 확인한다. 문서·Terraform 변경도 예외 없이 후보에 실어 보낸다.
- **후보를 확정한 때부터 출시를 마칠 때까지 main과 staging에 다른 병합을 하지 않는다.**
- **사람이 하는 일과 AI가 하는 일을 나눈다.** 병합, 보호 태그 생성, 원격 DB 적용, ruleset·Vercel 설정, 출시 결정은 사람이 한다. AI는 브랜치와 PR을 만들고 검사·기록을 맡으며 병합·승인·원격 DB 쓰기·태그 생성은 하지 않는다.
- **막히면 출시하지 않는다.** "출시 중단 조건"에 하나라도 해당하면 멈추고 사람에게 알린다.

## 1. 브랜치와 환경

| 이름 | 만드는 곳 | 용도 | 보호 |
|---|---|---|---|
| `meg-<번호>-<설명>` | main 또는 통합 브랜치 | 기능·수정 작업. PR 대상은 통합 브랜치 | 없음 |
| `meg-<번호>-integration` | 출시 시작 시점의 main 끝 | 이번 출시에 넣을 기능 PR을 모은다 | `integration-protection` ruleset(staging과 같은 규칙) |
| `meg-<번호>-release` | 통합 브랜치 끝 | 후보 R. main PR의 출발 브랜치 | Release tree check |
| `meg-<번호>-staging-batch` | 최신 staging 끝 | staging을 R 내용으로 덮어쓰는 STG 반영 PR의 출발 브랜치 | 없음 |
| 태그 `stg-accepted/meg-<번호>` | STG 반영 병합 커밋 S | 사람이 STG 결과를 수락했다는 기록 | `stg-accepted-protection` tag ruleset(관리자만 생성) |

| 환경 | 배포 경로 | 확인 방법 |
|---|---|---|
| dev | 로컬, PR CI(`Product tests`), PR Preview(목 모드) | 단위·격리 SQL·목 기반 E2E |
| STG | `staging` push → Product CI 성공 → `staging-cd`가 Preview 배포 생성 | 배포 고유 URL과 STG 고정 주소, 배포용 E2E |
| Production | `main` push → Vercel Git 빌드 → Deployment Checks(`Product CI`, `Release tree check`) 통과 → 운영 도메인 할당 | 운영 smoke |

환경변수와 프로젝트 설정은 [배포 가이드](deployment-guide.md), 검사와 워크플로는 [GitHub Actions 문서](github-actions.md), STG 배포와 복구는 [staging CD](staging-cd.md)·[staging 복구](staging-recovery.md)를 따른다.

## 2. 출시 순서

한 번의 출시는 아래 10단계다. 괄호 안은 실행 주체다.

1. **통합 브랜치를 만든다 (AI 또는 사람).** 최신 main 끝에서 `meg-<번호>-integration`을 만든다. `integration-protection`의 필수 검사 규칙에 "생성 시 필수 검사를 요구하지 않음"이 켜져 있어야 만들 수 있다.
2. **기능 PR을 모은다 (작성자 → 사람 병합).** 기능 PR의 base를 통합 브랜치로 둔다. Product CI와 Code Owner 승인을 받은 뒤 squash로 병합한다. main을 base로 열린 PR은 base를 통합 브랜치로 바꾼다. 앞선 PR이 병합되면 남은 PR은 최신화(Update branch)가 필요하고 그때 이전 승인이 풀리므로 다시 승인한다.
3. **후보 R을 확정한다 (AI).** 통합 브랜치 끝에서 `meg-<번호>-release`를 만들고 아래 "후보 기록"을 남긴다. 트리 T는 `git rev-parse <R>^{tree}`로 구한다. 이때부터 main·staging 병합을 멈춘다.
4. **STG에 반영한다 (AI가 PR, 사람 병합).** 최신 staging에서 `meg-<번호>-staging-batch`를 만들고 추적 파일 전체를 R과 같게 맞춘다.

   ```bash
   git switch -c meg-<번호>-staging-batch origin/staging
   git read-tree -u --reset origin/meg-<번호>-release
   git write-tree                    # T와 같아야 한다
   git commit -m "chore(MEG-<번호>): staging에 후보 R 전체 내용 반영"
   ```

   staging 대상 PR을 열고 사람이 squash로 병합한다. 병합 뒤 staging 끝 커밋 S의 트리가 T인지 확인한다. 병합하면 `staging-cd`가 STG 배포를 만든다.
5. **STG DB에 마이그레이션을 적용한다 (사람).** 후보에 STG 미적용 마이그레이션이 있으면 E2E 전에 적용한다. 방법과 알려진 문제는 "6. DB 변경"을 따른다.
6. **STG 고정 주소를 새 배포로 옮긴다 (사람 또는 사람이 승인한 AI).** `staging-cd`는 배포만 만들고 STG 고정 주소(staging 브랜치 alias)를 옮기지 않는다. 배포 고유 URL은 허용 출처(`ALLOWED_ORIGINS`)에 없어서 로그인 같은 POST 요청이 `403 origin_not_allowed`로 막힌다. 고정 주소를 새 배포에 연결하고 되돌릴 때를 위해 이전 대상 배포 ID를 기록한다.
7. **STG E2E를 하고 사람이 수락한다 (AI 실행, 사람 수락).** 고정 주소에서 배포용 E2E를 실행한다.

   ```bash
   cd frontend
   npx playwright test -c playwright.deployed.config.ts
   ```

   주소·시험 계정·Vercel 공유 링크는 커밋하지 않는 `.env.e2e.local`에서 읽는다. 공유 링크는 주소 뒤에 `?_vercel_share=` 토큰이 붙은 형태여야 하며 배포 주소만 넣으면 Vercel 로그인 화면으로 넘어간다. 지금 자동 시험은 로그인 흐름(`e2e-deployed/auth.spec.ts`)뿐이므로 나머지 핵심 흐름은 사람이 확인하거나 미검증으로 기록한다. 사람이 결과를 수락하면 다음 단계로 간다.
8. **보호 태그를 만든다 (관리자).** GitHub 저장소의 Releases → New release에서 태그 `stg-accepted/meg-<번호>`, Target `staging`(= S), Pre-release로 발행한다. 발행 전에 Target이 `main`이 아닌지 반드시 확인한다. AI 계정이나 AI 계정으로 인증된 PC에서 `git push`로 만들면 tag ruleset이 거부한다. 발행 뒤 태그 커밋의 트리가 T인지 확인한다.
9. **main PR로 출시한다 (AI가 PR, 사람 병합).** `meg-<번호>-release` → `main` PR을 열고 `Release tree check` 통과를 확인한다. 사람이 출시를 결정하고 squash로 병합한다. 병합 뒤 main 커밋 P의 트리가 T인지, main push의 Release tree check와 Product CI가 통과했는지, 운영 도메인이 새 배포로 넘어갔는지 확인한다.
10. **운영 smoke를 하고 정리한다 (AI·사람).** 최소 범위는 `/api/health`, 로그인, 핵심 읽기(노트 열기·용어 설명), 핵심 쓰기(퀴즈 답 제출, 운영자 노트의 가벼운 수정 후 복원), 주요 외부 연동(AI 호출 1회)이다. 운영 데이터는 삭제하지 않는다. smoke는 전체 E2E를 대신하지 않는다. 끝나면 결과를 릴리스 이슈에 기록하고 통합 브랜치를 지운다(아래 운영 규칙).

## 3. 운영 규칙

- 병합 중지: 후보 확정부터 운영 smoke까지 main과 staging에는 이번 후보의 PR만 병합한다. 문서와 Terraform 변경도 다음 후보로 미룬다.
- 긴급 수정: 진행 중인 후보를 중단하고 긴급 수정을 반영한 최신 main 기준으로 새 번호의 후보를 다시 만든다. 보호 태그는 만든 뒤 옮기거나 지울 수 없으므로 번호를 재사용하지 않는다.
- 기능이 하나뿐일 때: 통합 브랜치를 후보로 써도 된다. 조건은 최신 main을 포함할 것, 다른 변경이 없을 것, 후보 확정 뒤 추가 개발을 멈출 것, STG 검증을 똑같이 거칠 것이다.
- 통합 브랜치 정리: 통합 브랜치는 PR을 병합해도 자동 삭제되지 않으며 ruleset이 삭제를 막는다. 출시를 마치면 관리자가 `integration-protection`을 잠시 비활성화하고 브랜치를 지운 뒤 다시 활성화한다. 우회 대상은 추가하지 않는다. 후보 브랜치와 STG 반영 브랜치는 PR 병합 때 자동 삭제되므로 R·S의 SHA와 T는 병합 전에 기록한다.
- Linear 상태: 제목에 이슈 번호가 든 PR이 병합될 때마다 Linear 연동이 그 이슈를 Done으로 바꾼다. AC가 남아 있으면 In Progress로 되돌리고 이유를 남긴다.

## 4. 기록 양식

기록은 해당 릴리스 이슈(MEG-21 하위)의 댓글로 남긴다. 공개 PR에는 비밀값·내부 주소·고객 원문을 쓰지 않는다.

### 후보 기록 (3단계)

| 항목 | 내용 |
|---|---|
| 후보 브랜치·R | `meg-<번호>-release`, 커밋 SHA |
| 트리 T | `git rev-parse <R>^{tree}` 결과 |
| 기준 main | SHA와 R이 main보다 뒤처지지 않았는지(behind 0) |
| 포함·제외 | 통합 브랜치에 병합된 PR 목록, 이번에 빼는 PR과 이유 |
| DB 변경 | 없음 / 있음(파일명, STG·PRD 적용 상태, 적용 담당) |
| 복구 후보 | 현재 운영 배포 ID와 SHA |

### 출시 기록 (4~10단계)

| 항목 | 내용 |
|---|---|
| STG 반영 | PR 번호, S의 SHA, tree(S) = T 여부, STG 배포 ID, 고정 주소 이전 대상 |
| STG E2E | 실행한 시험과 결과, 사람이 확인한 흐름, 미검증 흐름, 수락한 사람과 시각 |
| 보호 태그 | 태그 이름, 가리키는 커밋, 만든 사람 |
| main 반영 | PR 번호, P의 SHA, tree(P) = T 여부, Release tree check 실행 링크 |
| 운영 | Production 배포 ID, 운영 도메인 이동 확인, smoke 결과, 복구 후보 |

출시 승인 버튼은 따로 두지 않는다. 사람이 STG 결과를 수락하고(보호 태그), main PR을 승인·병합하는 것이 출시 결정이다.

## 5. 출시 중단 조건

다음 중 하나라도 해당하면 출시를 멈추고 사람에게 알린다.

- 후보·STG·main 어느 단계든 `Product CI`가 실패·취소·미실행이다.
- tree(S), 태그 커밋 트리, tree(P) 중 하나라도 T와 다르다.
- 후보 확정 뒤 main이나 staging에 다른 변경이 병합됐다.
- STG에 필요한 마이그레이션이 적용되지 않았거나, 적용 이력과 실제 DB가 어긋난다.
- STG E2E가 실패했거나 사람이 수락하지 않았다.
- 복구 후보(현재 운영 배포)를 확인하지 못했다.

## 6. DB 변경

- 순서: 확장 → 새 앱 → 제거로 나눈다. 새 앱이 쓰는 열·함수는 먼저 추가하고 옛 것은 새 앱이 운영에 오른 뒤 다음 출시에서 지운다.
- 대조: 후보를 구성할 때와 환경에 적용하기 직전에 저장소 마이그레이션 목록을 STG·PRD의 적용 이력과 비교한다. 이미 적용된 파일의 내용이나 적용 이력은 고치지 않는다. 저장소 파일 버전과 PRD 적용 버전이 다르면 내용을 바꾸지 않고 파일 이름을 PRD 적용 버전에 맞춘다(MEG-220 사례).
- 적용(사람): 최신 staging을 꺼낸 작업 폴더에서 저장소에 고정된 CLI를 쓴다. 오래된 체크아웃에서 실행하면 원격에만 있는 버전 때문에 거부된다.

  ```bash
  npx supabase link --project-ref <STG 프로젝트 ref>
  npx supabase db push --dry-run   # 적용 예정 목록을 먼저 확인
  npx supabase db push
  ```

- STG의 알려진 문제: STG 이력에 평가용 `20261102050018_eval_shared_ledger`가 있는데 저장소에는 이 버전의 마이그레이션 파일이 없다(평가 SQL을 수동 적용한 이력). 그래서 `db push`가 `Remote migration versions not found in local migrations directory`로 거부된다. 이때는 다음처럼 한다.
  1. STG 대시보드 SQL Editor에서 적용할 마이그레이션 파일 내용을 순서대로 실행한다.
  2. 모두 성공한 뒤에만 `npx supabase migration repair --status applied <버전> ...`으로 이력을 추가한다. 순서가 바뀌면 이력과 실제 DB가 어긋난다.
  3. CLI가 제안하는 `migration repair --status reverted`와 `db pull`은 쓰지 않는다. 앞의 것은 기존 이력을 고치고 뒤의 것은 저장소 파일을 바꿔 트리 T가 달라진다.

  근본 해결(이력 정리 또는 저장소 파일 추가)은 별도 결정이 필요하다.
- 복구와 백업: 앱을 되돌려도 이미 적용된 DB 변경은 남는다. 되돌리기보다 전진 수정을 먼저 검토한다. 백업 확인과 복구 판단 기준은 MEG-195에서 정한다.

## 7. 복구

- STG: STG 고정 주소를 이전 배포로 다시 연결한다. 자세한 검증 절차는 [staging 복구](staging-recovery.md)를 따른다.
- Production: 사람이 운영 도메인을 이전 운영 배포로 되돌린다. DB 변경과 바뀐 환경변수는 되돌아가지 않는다. 자동 롤백과 승인 없는 강제 승격은 쓰지 않는다.
- 되돌린 경우 사유·대상 배포·SHA·결과를 릴리스 이슈에 기록한다.

## 8. 이 문서가 보장하지 않는 것

- 배포용 자동 E2E는 로그인 흐름 하나다. 노트·퀴즈·운영자 흐름은 사람이 확인하거나 미검증으로 남는다.
- `Release tree check`는 main 필수 검사로 연결돼 있지 않다(2026-11-05 기준). 후보가 아닌 PR도 main에 병합될 수 있고 그 경우 Deployment Checks가 운영 도메인 할당만 막는다.
- STG 고정 주소 이동과 STG DB 적용은 아직 손으로 한다.
- 이 문서의 병합은 출시 승인이 아니다. 각 출시의 완료는 릴리스 이슈의 AC와 사람의 수락으로 판단한다.
