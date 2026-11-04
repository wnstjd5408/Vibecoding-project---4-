# staging CI 이후 배포

이 구성은 `staging` push에서 **같은 실행의 Product CI 성공 → Vercel Preview 배포 → Ready 확인** 순서로 동작한다. PR과 `main`에서는 배포 job을 실행하지 않는다. Production은 Git 연동을 유지하고 Deployment Checks로 운영 도메인 반영을 제어하는 별도 작업이다. PR Preview 정책도 그대로 유지한다.

**병합 주의:** `vercel.json`은 staging의 Git 자동 배포를 끈다. `STAGING_CD_ENABLED`는 기본적으로 비어 있어 CD도 실행되지 않는다. 아래 설정을 준비한 뒤 사람이 staging에 병합하고 활성화한다. 그 사이 새 staging 배포는 잠시 멈추며 기존 Ready 배포와 평가 이력은 보존된다. 이 문서는 원격 설정 완료나 실제 배포 성공의 증거가 아니다.

## 실행 계약

- `.github/workflows/product-ci.yml`의 `staging-cd`는 `product-ci`를 `needs`로 참조한다. 같은 실행의 네 제품 검사와 배포 제어 단위 테스트가 성공해야 시작한다. 별도의 이름이 같은 check를 신뢰하지 않는다.
- 실행 SHA를 checkout하고 API에도 `gitSource.ref=staging`, `gitSource.sha=<검사한 SHA>`를 함께 전달한다. `target`은 생략해 Preview를 사용한다. API의 `target=staging`은 Git 브랜치 지정과 다른 기능이므로 사용하지 않는다.
- 프로젝트의 저장소 연결, Production 브랜치 `main`, 시스템 환경변수 노출 설정을 확인한다. Ready 응답에서도 프로젝트·SHA·브랜치·Preview 환경을 확인한다. 이것만으로 DB/AI 연결이나 브랜치별 환경변수 값이 올바르다는 뜻은 아니다.
- 시작 및 생성 직전에 최신 staging SHA와 대조해 오래된 실행은 배포하지 않는다. 생성 후 staging이 전진할 수 있으므로 Ready 때도 대조하며, 달라졌으면 최신 환경 검증 성공으로 인정하지 않는다. 이미 시작된 검증된 SHA의 빌드가 잠시 브랜치 URL에 반영될 가능성은 있다. 이후 새 실행이 최신 SHA를 처리한다.
- staging push 실행과 배포 job은 자동 취소하지 않고 직렬화한다. GitHub concurrency는 FIFO나 모든 중간 버전의 배포를 보장하지 않는다. 대기 중인 오래된 실행은 생략될 수 있다. 배포할 때는 최신 버전인지 다시 확인한다.
- staging 배포 이력을 페이지 끝까지 확인한다(최대 2,000개, 초과 시 차단). 이전 SHA가 빌드 중이거나 상태가 불명확하면 새 배포를 만들지 않는다. 같은 SHA의 이 경로 배포가 있으면 재사용한다. 중복이거나 수동/Git 배포이면 사람 확인을 요구한다.
- POST는 한 번만 보낸다. 응답 유실·시간 초과 후 무작정 재생성하지 않는다. GitHub 재실행(`run_attempt > 1`)에서는 기존 배포만 확인한다. 조회 결과가 없으면 새 배포를 만들지 않는다. 최초 실행이 배포 POST 이전에 실패했더라도 이 보수적인 규칙을 적용한다.
- 최대 18분 동안 Ready를 기다린다. 실패·취소·차단·알 수 없는 상태는 실패다. 타임아웃이나 workflow 수동 취소가 원격 빌드를 취소하지는 않는다. 실행 중인 원격 배포를 확인하기 전 새 버전을 배포하지 않는다.
- Actions 요약에는 SHA·실행 링크·배포 ID·고유 URL을 남긴다. 원격 오류 본문·환경변수 값·토큰은 출력하지 않는다. API 인증정보는 리다이렉트로 전달하지 않는다. Ready는 런타임 smoke 성공이 아니다.

## 사람이 준비할 GitHub·Vercel 설정

1. GitHub 저장소 **Settings → Environments → New environment**에서 정확히 `staging-cd`를 만든다.
2. 해당 Environment의 **Deployment branches and tags → Selected branches and tags → Add deployment branch or tag rule**에서 유형 **Branch**, 이름 **staging**만 추가한다. 태그·다른 브랜치·와일드카드는 허용하지 않는다. `Protected branches only`는 main도 허용하므로 사용하지 않는다. 저장한 정책을 다시 확인한다.
3. 기존 staging ruleset의 `Product CI`, `Check PR metadata`, strict, 사람 Code Owner 승인 1명·새 push 시 승인 취소 조건을 유지한다. 배포마다 사람 승인도 원하는 경우 Environment의 Required reviewers에 사람을 지정할 수 있지만, PR 승인과 다른 추가 대기 단계다. `Staging CD`는 PR에서 의도적으로 생략되므로 필수 PR 검사에 추가하지 않는다.
4. Vercel에서 배포용 자동화 자격증명을 준비한다. 지원되는 범위 안에서 대상 팀·프로젝트 접근만 부여하고 만료·회수 담당자를 정한다. 일반 Vercel Access Token이 Preview만 또는 이 프로젝트만으로 제한된다고 가정하지 않는다. 실제 부여 가능한 권한을 확인하고 더 넓다면 그 한계를 기록한 뒤 활성화한다. 사람 관리자 토큰을 AI 실행 환경에 전달하지 않는다.
5. GitHub **staging-cd → Environment secrets**에 `VERCEL_TOKEN`을 직접 등록한다. Repository secret에는 두지 않는다. **Environment variables**에는 `VERCEL_PROJECT_ID`, `VERCEL_TEAM_ID`를 등록한다. DB/AI 비밀값은 Actions로 복사하지 않는다. 애플리케이션 비밀값은 기존 Vercel Preview의 `staging` 브랜치 범위를 유지한다.
6. Vercel **Project → Settings → Git**에서 연결 저장소·Production Branch `main`을 확인한다. **Environment Variables**에서 Preview Branch `staging` 값과 시스템 환경변수 노출을 확인한다. 특히 `VITE_API_MOCK`이 true가 아니고 운영 DB 키가 staging에 복사되지 않았는지 기존 환경 점검 기록과 대조한다. 기존 평가용 배포는 삭제하지 않는다.
7. GitHub **Settings → Secrets and variables → Actions → Variables → New repository variable**에 `STAGING_CD_ENABLED=false`를 등록한다. job의 `if`는 Environment 진입 전에 평가되므로 이 변수는 반드시 **Repository variable**이어야 한다.

GitHub 토큰 권한은 `contents: read`뿐이며 배포 제어 외의 PR 코드에는 Environment를 연결하지 않는다. Environment의 브랜치 제한은 PR이 workflow를 수정해도 배포 토큰을 얻지 못하게 하는 경계다. 파일의 조건식이나 Vercel `git.deploymentEnabled`만으로 접근 통제가 완성되는 것은 아니다.

## 전환 및 실제 검증 순서

1. 위 설정을 마친 뒤 사람이 PR을 검토하고 **staging에** 병합한다. 병합 직후 루트 `vercel.json`의 staging 자동 배포 비활성화를 확인한다. main으로 나중에 반영하더라도 이 설정은 staging에만 적용된다.
2. 그 staging push 실행에서 네 검사 및 `Product CI`가 성공하고 `Staging CD`는 disabled로 생략되는지 확인한다. 같은 SHA로 Git 자동 배포가 만들어지지 않았는지 Vercel에서도 확인한다. webhook 지연/기존 대기 배포가 남아 있다면 끝날 때까지 전환을 진행하지 않는다.
3. 승인된 staging 버전과 환경을 작업 기록에 남긴 뒤 Repository variable을 `STAGING_CD_ENABLED=true`로 바꾼다. 새 승인된 staging 변경의 push가 최초 CD 실행을 시작하게 한다. 설정 전 실행을 재실행해 새 배포를 만드는 방법은 지원하지 않는다. 재실행은 이미 생성된 배포를 추적할 때만 쓴다.
4. 해당 push의 Product CI 완료 시각보다 배포 생성이 뒤인지, 두 SHA가 같은지, 환경이 Preview/브랜치 staging인지, Vercel 생성이 한 건인지 확인한다. 고유 URL의 Ready와 `/api/health` 응답은 별도로 확인한다. 보호된 배포의 로그인 화면을 앱 성공으로 세지 않는다. DB·Auth·AI smoke는 승인된 별도 검증 범위를 따른다.
5. 동일 실행을 재실행해 새 배포가 늘지 않는지 확인한다. 실패·미완료 CI, stale SHA, API 실패의 로컬 모의 시험은 PR에 기록한다. 실제 원격 실패→수정 시험은 공개 가능한 시험 전용 이슈/PR로 분리하고, 보호된 브랜치 우회나 실패 PR 병합으로 만들지 않는다. 제품 CI가 실패한 실행에서 CD가 생략되고 Vercel 생성도 없는지 관찰해야 실제 차단 검증이 완료된다.
6. 환경·SHA·CI 실행·배포 ID·URL·성공/실패·미검증·사람 수락을 내부 릴리스 작업에 기록한다. 구성 PR 병합만으로 배포 검증이나 릴리스 전체를 완료 처리하지 않는다.

## 실패 시 중단과 복구

`STAGING_CD_ENABLED=false`로 **향후 실행**을 막는다. 이 변경은 이미 실행 중인 job이나 Vercel 빌드를 취소하지 않는다. GitHub 실행 요약과 Vercel 배포 목록에서 활성 요청을 먼저 확인한다. API POST 결과가 유실됐다면 동일 SHA를 조회해 기존 요청의 존재·종료 여부를 확정한다. 재실행은 기존 CD 배포를 재사용할 수 있지만, 결과를 찾을 수 없으면 차단된다. 확인 기록을 남긴 후 새 승인된 커밋으로 다시 시작한다.

자동 롤백·강제 alias 변경·Git 자동 배포 재활성화는 수행하지 않는다. 기존 Ready 배포와 고유 URL을 보존하고, 사람이 검증된 버전·환경과 복구 방법을 선택한다. Git 자동 배포로 되돌리려면 CI 이전 배포 위험이 다시 생기므로 별도 승인된 PR과 전환 기록이 필요하다. 수동 배포·다른 자동화가 동시에 staging을 변경하면 이 workflow의 직렬화 범위를 벗어나므로 전환/검증 중 사용하지 않는다.

## 로컬 검증

저장소 루트에서 `python -m unittest discover -s .github/scripts -p test_staging_cd.py -v`를 실행한다. 외부 API와 자격증명 없이 실패·성공·중복·stale·시간 초과·잘못된 환경·리다이렉트 차단을 모의 시험한다. 같은 명령이 Product backend unit에서도 실행된다. 실제 API 호환성·토큰 권한·Environment 정책·Git 자동 배포 중단·실제 배포 성공은 원격 검증이 필요하다.

근거: [Vercel Git 배포 설정](https://vercel.com/docs/project-configuration/git-configuration#git.deploymentenabled), [공식 REST API 스키마](https://openapi.vercel.sh/), [GitHub Environment 브랜치 제한](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments#deployment-branches-and-tags), [GitHub concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
