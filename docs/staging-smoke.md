# staging 배포 후 health 검사

Vercel Ready와 실제 앱 응답을 별도로 판정한다. `STAGING_SMOKE_ENABLED=true`인 staging CD 실행은 Ready 확인 후 같은 배포 ID를 다시 조회하고, 검증된 고유 URL의 `GET /api/health`만 호출한다. PR·main·실패 CI·오래된 staging 실행에서는 이 경로가 실행되지 않는다.

## 판정

- 동일 프로젝트, GitHub SHA, staging ref, Preview, CD 표시, Ready를 먼저 확인한다. 검사 전후 staging HEAD도 일치해야 한다.
- HTTP 200, JSON `{"status":"ok"}`, JSON Content-Type, Cache-Control의 `private`와 `no-store`를 모두 요구한다. 공개/공유 캐시는 거부한다.
- 요청당 최대 10초, 최대 3회, 재시도 사이 5초다. 리다이렉트를 따라가지 않으며 로그인 HTML·오류·timeout은 실패다.
- 결과는 `SMOKE_PASSED`, `SMOKE_FAILED`, 비활성 시 `SMOKE_NOT_RUN`으로 Ready와 구분한다. 사전 조건 오류도 step/job 실패다. 응답 원문, OIDC 토큰, 인증 헤더는 로그에 남기지 않는다.
- 실패해도 이미 생성한 Ready 배포를 삭제하거나 롤백하지 않는다. 기존 배포 재실행은 같은 ID를 대상으로 다시 검사한다. DB/Auth/AI와 제품 쓰기 흐름은 검증하지 않는다.

## 사람이 적용할 설정

구성 PR만으로 접근 권한을 바꾸지 않는다. 처음에는 repository variable `STAGING_SMOKE_ENABLED`를 미설정 또는 `false`로 유지한다. `STAGING_CD_ENABLED`와 별도 스위치이며 smoke 비활성은 health 성공이 아니다.

Vercel 프로젝트 **Settings → Deployment Protection → Trusted Sources → External Services → Add → GitHub Actions**에서 다음처럼 제한한다.

1. 해당 저장소의 GitHub 소유 계정과 **정확한 저장소 하나**를 선택한다. 계정 전체 허용으로 남기지 않는다.
2. Branch는 `staging`, GitHub Actions environment는 `staging-cd`로 제한한다.
3. Applies to environments는 **Preview만** 선택한다. Production과 다른 환경은 허용하지 않는다.
4. 기본 audience `https://github.com/<저장소 소유 계정>`을 사용한다. issuer는 `https://token.actions.githubusercontent.com`이다. 저장 후 repository/ref/environment/audience 제한이 반영됐는지 확인한다.
5. 보호 설정은 유지한다. 공개 예외·장기 bypass secret·임시 공유 링크를 만들지 않는다. 이 규칙은 해당 프로젝트의 Preview에 접근을 허용하므로 다른 PR Preview 접근 가능성도 사람이 검토한다. 앱 자체 인증을 대신하지는 않는다.
6. 사람이 범위를 수락하고 저장한 뒤 `STAGING_SMOKE_ENABLED=true`로 바꾼다. 새 승인된 staging 버전의 CI·사람 배포 승인을 거쳐 실제 성공/실패를 확인한다. 과거 실행은 당시 workflow를 쓰므로 새 코드를 검사하지 못한다.

Workflow는 승인된 `staging-cd` job에만 `id-token: write`를 준다. Python이 GitHub OIDC endpoint에서 짧은 수명 토큰을 받고 검증된 배포 호스트에만 `x-vercel-trusted-oidc-idp-token` 헤더로 전송한다. 토큰은 메모리와 curl 표준입력으로만 전달한다. curl 사용자 설정은 비활성화하고 리다이렉트는 금지한다.

## 검증과 복구

격리 테스트는 정상·오류·timeout·재시도, 잘못된 SHA/환경/URL, 오래된 HEAD 및 비밀값 비노출을 확인한다. 실제 Trusted Sources 설정, 네트워크 접근 및 배포의 smoke 성공은 별도 실행 근거가 필요하다. 로컬 모의 테스트를 실제 배포 성공으로 기록하지 않는다.

smoke 실패 시 원인을 확인할 때까지 후속 배포를 중단한다. 필요하면 사람이 `STAGING_CD_ENABLED=false`로 새 실행을 막는다. 이는 실행 중 원격 빌드를 취소하지 않는다. smoke 스위치를 끄더라도 실패 기록을 성공으로 바꾸지 않는다. 실제 실패 CI 차단 시험·복구 시험·Production 출시는 별도다.

근거: [Vercel Trusted Sources 공식 문서](https://vercel.com/docs/deployment-protection/methods-to-bypass-deployment-protection/trusted-sources). 실제 작업 결과와 사람 수락은 부모 검증 티켓에서 추적한다.
