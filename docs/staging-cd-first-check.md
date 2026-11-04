# 최초 staging CD 검증 체크리스트

배포 후 자동 health 검사의 활성화·접근 설정·판정 기준은 [staging smoke 가이드](staging-smoke.md)를 따른다.

이 문서는 최초 CD 실행에 사용할 새 staging 커밋을 준비하는 공개 산출물이다. **문서 병합이나 PR CI 성공만으로 실제 배포 검증을 완료하지 않는다.** 실제 실행 결과와 사람 수락은 내부 검증 작업에 기록한다. 기본 배포 계약과 오류 처리는 [staging CD 가이드](staging-cd.md)를 따른다.

## 1. 활성화 전에 확인할 것

- [ ] `staging-cd` Environment의 Deployment branches and tags가 **Selected branches and tags**, **Branch `staging` 한 개**, **Tag 0개**다.
- [ ] Required reviewers에 사람 Code Owner `wnstjd5408`이 지정돼 있다. **Allow administrators to bypass configured protection rules**는 꺼져 있다.
- [ ] 이번 최초 검증에서는 **Prevent self-review**를 켜지 않는다. 사람이 직접 병합해 시작한 실행을 같은 사람이 배포 승인할 수 있도록 한다. AI 작성자와 사람 PR 승인자의 분리는 유지하며, 배포 승인까지 다른 사람 한 명을 더 요구하는 정책은 아니다.
- [ ] Environment variables의 `VERCEL_PROJECT_ID`, `VERCEL_TEAM_ID`가 대상 프로젝트·팀과 일치하고 Environment secret `VERCEL_TOKEN`이 등록돼 있다. 토큰의 실제 대상 팀·권한·만료일은 사람이 확인한다. 토큰 값을 기록하지 않는다.
- [ ] staging 브랜치의 Git 자동 배포가 꺼져 있고, 기존 활성 배포가 없다. 준비 중 Repository variable `STAGING_CD_ENABLED`는 `false`다.

GitHub 화면에서는 **Settings → Environments → staging-cd → Deployment protection rules**에서 reviewer와 우회 조건을 지정하고 **Save protection rules**로 저장한다. 저장된 조건을 다시 조회한 뒤 진행한다. Required reviewers는 PR 승인과 별도이며 배포 job이 Environment에 접근할 때 적용된다.

## 2. 새 커밋으로 시작하고 승인 대기를 확인한다

1. 이 문서 PR의 최신 head에 대한 `Product CI`와 `Check PR metadata`가 성공했는지 확인한다. PR의 `Staging CD` 생략은 정상이다. PR Preview 성공을 staging CD 성공으로 기록하지 않는다.
2. 사람이 사전 조건과 최초 실행 대상을 확인한 뒤 Repository variable `STAGING_CD_ENABLED`를 `true`로 바꾼다. 검증 중에는 다른 staging 변경·수동 배포를 동시에 진행하지 않는다.
3. 사람이 문서 PR을 승인하고 staging에 squash merge한다. **병합 후 staging SHA**와 새 `push` 실행 ID를 기록한다. PR head/merge-test SHA와 혼동하지 않는다.
4. 새 push의 네 제품 검사와 `Product CI`가 성공하고 `Staging CD`가 **Waiting for review** 상태가 되는지 확인한다. 승인하기 전에 Vercel에서 이 병합 SHA의 배포가 **0건**인지 확인한다. 배포가 이미 있거나 승인 없이 job이 시작됐다면 승인하지 않고 원인을 확인한다.
5. GitHub **Actions → 해당 Product tests 실행 → Review deployments**에서 `staging-cd`와 대상 SHA를 확인하고 사람이 **Approve and deploy**한다. 관리자 우회나 AI 계정 승인은 사용하지 않는다.

현재 구현은 새 배포가 없는 재실행에서 POST를 차단한다. 따라서 비활성 상태로 끝난 과거 실행을 재실행해 최초 배포를 만들지 않는다. 활성화 전에 실수로 병합했다면 그 실행을 억지로 우회하지 말고 새 승인된 커밋을 준비한다.

## 3. 생성·Ready·앱 응답을 구분해 확인한다

| 단계 | 통과 기준 | 결과를 남길 곳 |
|---|---|---|
| 생성 순서 | CI 완료와 사람 배포 승인 뒤 Vercel 배포가 생성된다 | 실행 및 배포 시각 |
| 버전·환경 | 실행 SHA = staging 병합 SHA = 배포 `gitSource.sha`, ref는 `staging`, 환경은 Preview | SHA, 브랜치, 환경, 배포 ID |
| 중복 | 같은 SHA의 staging 배포가 한 건이며 다른 Git 자동 배포가 없다 | 배포 목록 조회 결과 |
| Ready | `Staging CD`와 해당 Vercel 배포가 성공/Ready다 | 실행 결과와 고유 배포 URL |
| 앱 기동 | 그 고유 URL의 `/api/health`가 HTTP 200, JSON `{"status":"ok"}`, `Cache-Control: private, no-store`를 반환한다 | 요청 결과와 검사 시각 |

health는 요청당 최대 10초, 최대 3회, 재시도 간격 5초로 확인한다. 로그인 화면·HTML·다른 URL로의 리다이렉트·비정상 상태 코드는 성공으로 세지 않는다. 보호된 배포라면 기존의 승인된 접근 방법을 사용하고, 검사 편의를 위해 배포 보호를 끄거나 새로운 우회 자격증명을 만들지 않는다. 접근할 수 없으면 health를 미검증으로 남긴다.

health는 앱 기동만 확인한다. DB·Auth·AI 정상 동작, 사용자 쓰기 흐름, 비용 발생 시험을 포함하지 않는다. 실제 실패 CI 차단도 이번 성공 실행이나 승인 대기 확인으로 대체하지 않는다. 별도 실패→수정 시험은 시험 전용 이슈/PR로 준비하며 실패 PR을 병합하지 않는다.

## 4. 재실행과 실패 처리

최초 성공 결과를 기록한 뒤 같은 실행을 재실행해 기존 CD 배포를 재사용하는지 확인한다. 필요한 배포 승인은 다시 사람이 처리한다. 배포 ID가 같고 새 배포가 늘지 않아야 한다. GitHub가 이미 완료한 배포를 재사용하는 사실과 새로운 배포 성공을 구분한다.

실패·시간 초과·SHA 불일치·중복이 발견되면 **새 배포 시도를 멈추고 `STAGING_CD_ENABLED=false`로 되돌린다.** 이 변수 변경은 이미 시작된 job이나 원격 빌드를 취소하지 않는다. 기존 요청이 진행 중인지 먼저 조회한다. 결과가 불명확한 POST를 반복하거나 자동 롤백하지 않는다. 기존 Ready 배포와 평가 이력을 보존하고, 새 커밋 또는 복구가 필요하면 사람이 대상과 방법을 정한다.

## 5. 완료 기록

실제 결과는 접근이 제한된 원 작업에 다음 항목으로 기록한다. 이 공개 체크리스트에 비밀값이나 내부 운영 기록을 채워 넣지 않는다.

- 기준 SHA, CI 실행 ID/URL, 검사 결과와 완료 시각
- Environment 보호 조건, 사람 승인자와 승인 시각
- 배포 ID, 고유 URL, SHA·브랜치·환경, 생성/Ready 시각
- health 결과와 한계, 재실행 전후 배포 개수·ID
- 실패·미검증 항목, 후속 작업, 사람의 결과 수락

문서 산출물 이슈와 실제 배포 검증 작업은 별도로 완료 판단한다. 실제 검증 작업은 모든 요구사항과 사람 수락이 확인되기 전까지 완료로 바꾸지 않는다.
