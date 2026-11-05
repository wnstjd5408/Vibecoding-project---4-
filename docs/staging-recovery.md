# staging 실패 감지·복구 검증

`Staging recovery verification`은 기존 배포를 읽기 전용으로 검사한다. 배포 생성, 트래픽 전환, 자동 롤백, DB 복원을 하지 않는다. 실제 시험 결과와 사람 수락은 릴리스 작업에 기록한다.

## 사람이 준비할 설정

1. 코드 PR을 리뷰하고 staging에 병합한다. GitHub `workflow_dispatch`는 기본 브랜치에도 workflow 파일이 있어야 실행할 수 있다. 따라서 **main 등록용 별도 검토 PR**도 필요하다. main으로 staging 전체를 병합하지 않는다. main 등록만으로 실행하지 않으며 실행 브랜치는 반드시 staging이다.
2. Vercel Trusted Sources에 **별도 규칙**을 추가한다. 기존 `Product tests` 규칙은 유지한다. 동일 계정·정확한 저장소, Branch `staging`, Workflow `Staging recovery verification`, 기본 audience, **Preview만** 허용한다. 현재 UI에는 GitHub Environment 입력란이 없다. Environment 승인은 GitHub에서 적용한다.
3. GitHub `staging-cd`의 사람 reviewer·관리자 우회 금지·staging branch 제한을 유지한다. 기존 Vercel token/project/team 설정을 재사용한다. 새 비밀값은 필요 없다.
4. repository variable `STAGING_RECOVERY_ALIAS`에 실제 staging 브랜치의 전체 Vercel hostname을 넣는다(https://와 경로 제외). `STAGING_RECOVERY_ENABLED`는 준비 중 false로 두고 시험 창을 확정한 후 true로 설정한다.
5. 실행자는 배포 ID와 40자리 SHA를 입력한다. workflow 실행 자체와 Environment 배포 승인은 별도 단계다. main 선택 또는 flag 비활성은 job skip이며 검증 성공이 아니다.

## 후보와 시험 창

현재·후보 배포 ID, SHA, Preview/staging, Ready, 원본 성공 CI, 앱·DB 마이그레이션·환경 설정 호환성, 담당자, 시작/종료 시각을 먼저 기록한다. 코드 차이가 없더라도 배포 시점의 환경변수와 DB 호환성이 같다고 단정하지 않는다. 비밀값은 기록하지 않는다.

검증기는 후보가 이전 SHA여도 허용하지만 **실행 코드의 staging HEAD가 실행 중 바뀌면 중단**한다. CD와 concurrency group을 공유한다. GitHub는 대기 작업을 대체할 수 있으므로 시험 창에는 새 push·다른 CD 실행·수동 alias 변경을 멈춘다.

## 실패 감지와 수동 복구 순서

1. `check_staging_alias=false`로 후보를 검사한다. 같은 프로젝트의 CD 표시·원본 CI run·SHA·Preview·Ready·고유 URL health를 검증한다. ERROR/BUILDING은 `BUILD_NOT_READY`, health 오류/timeout/보호 페이지는 `SMOKE_FAILED`로 실패한다. 실제 실패 배포가 없으면 실패 유발 방식과 영향을 별도 승인받는다. 모의 시험을 실제 장애로 기록하지 않는다.
2. 담당자가 실패 로그를 확인하고 후속 배포를 중단한다. `STAGING_CD_ENABLED=false`는 새 job만 막으며 진행 중 빌드를 취소하지 않는다. 실행 중 CD가 없는지 확인한다.
3. 후보가 검증되고 시험 창·영향이 승인되면 사람이 **Preview staging alias만** 이전 배포에 연결한다. Production의 Promote/Rollback 버튼을 사용하지 않는다. 앱 버전 전환은 DB/환경변수 복원이 아니다.
4. 같은 후보 ID·SHA, `check_staging_alias=true`로 실행하고 사람이 Environment 승인한다. alias의 project/deployment ID를 검사 전후 대조하고 고유 URL과 alias의 `/api/health`를 모두 검사한다. HTTP 200, JSON ok, private/no-store가 필요하다. 각 요청은 10초, 최대 3회·5초 간격이다.
5. 시험 목적이면 사람이 원래 정상 배포로 alias를 복원한 뒤 그 ID·SHA로 다시 검증한다. 복구 시작/종료·소요 시간·잔여 영향·실제 전환 담당자를 기록한다. 검증기의 Elapsed는 검사 시간이며 전체 복구 시간은 아니다.

## 중단 기준과 한계

SHA/환경/CI/alias 불일치, 후보 health 실패, staging HEAD 변경, 동시 배포, 예상하지 못한 사용자 영향이면 중단한다. 실패 기록을 숨기거나 보호를 풀지 않는다. 원상복구도 사람이 대상 ID를 재확인하고 수행한다.

이 workflow는 장애를 자동으로 만들거나 고치지 않는다. DB/Auth/AI·제품 사용자 흐름은 검사하지 않는다. 앱 코드가 같은 두 배포의 전환은 경로 복구 시험이며 기능 회귀 복구 증거가 아니다. 실제 실패·전환·복원 실행 전까지 부모 작업은 미완료다.
