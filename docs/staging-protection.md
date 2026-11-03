# Staging 브랜치 보호 적용과 검증

이 문서는 MEG-169의 설정 산출물(MEG-176)이다. JSON을 병합해도 GitHub 설정은 바뀌지 않는다. 실제 설정 적용·차단 시험·사람 수락은 MEG-169에서 추적한다.

## 환경과 변경 범위

- **Stage:** `staging`의 Vercel Preview. 승인된 테스트 DB·계정으로 연동 검증한다. 이 작업은 코드 유입 통제만 다룬다.
- **PRD:** `main`의 Production. 별도 출시 승인·버전·배포·복구 검증이 필요하다. staging 검사 성공으로 Production 버전 검증을 대신하지 않는다.
- 제품/평가 코드, 환경변수 값, 배포 설정, main ruleset, 동결된 하네스는 변경하지 않는다. staging 전체 초기화나 main 전체 동기화도 하지 않는다.

## 설정안

[staging-protection.json](../.github/rulesets/staging-protection.json)은 GitHub repository ruleset 생성용 본문이다. 자동 적용 워크플로는 없다.

| 항목 | 설정안과 이유 |
|---|---|
| 대상 | `refs/heads/staging`만, 제외 패턴 없음, `active` |
| 우회 | `bypass_actors: []`. AI·관리자·앱을 우회 목록에 추가하지 않는다 |
| PR | 필수, 승인 최소 1명, Code Owner 필수, 새 push 시 오래된 승인 취소 |
| 소유자 | 대상 브랜치 `.github/CODEOWNERS`의 사람 소유자를 적용 전에 확인한다 |
| 이력 보호 | 삭제와 force push 차단. 선형 기록 규칙은 추가하지 않는다 |
| 병합 방식 | `squash`. 현재 저장소가 squash만 허용하며 기존 이슈별 반영 흐름을 유지한다. 기존 merge 커밋을 재작성하지 않는다 |
| 필수 검사 | `Check PR metadata`, `Product CI`, 각각 GitHub Actions 앱 ID `15368` |
| 최신 기반 | `strict_required_status_checks_policy: true`. staging이 바뀌면 소스 브랜치에 최신 staging을 반영하고 다시 검사한다 |
| 생성 예외 | `do_not_enforce_on_create: false` |

strict는 CI 비용과 재검사 횟수를 늘릴 수 있다. 최신 **main**을 가져오라는 뜻이 아니다. 최신 **staging**만 해당 이슈 브랜치에 반영하며, 제품/평가 변경 범위를 확인한다. 검사 이름·앱 고정은 워크플로 정의 변조 방지의 대체물이 아니다. 사람이 CI 정의와 CODEOWNERS 변경도 검토해야 한다.

## MEG-168 의존성과 적용 순서

1. 사람이 MEG-168 PR #121의 최종 버전·성공 실행·미검증 항목을 검토한다. main 필수 검사 연결은 MEG-168 범위이며 이 작업에서 main 설정을 바꾸지 않는다.
2. MEG-168에서 수락한 제품 CI를 **staging 기반 이슈 브랜치**에 필요한 파일/수정만 반영해 별도 PR로 검토한다. workflow, JUnit 검증기, 필수 테스트, Playwright 설정/안정화 수정, 필요한 Python 변환기 의존성 설치가 함께 필요하다. staging의 기존 테스트·평가 변경은 유지한다. main 전체를 합치지 않는다.
3. 해당 staging PR에서 실제 `Product CI`와 `Check PR metadata`의 성공, 앱 ID와 head/merge SHA를 확인한다. 실패→수정 시험 PR은 별도 시험 이슈에 연결하고 병합 없이 닫는다. 수락한 CI 반영 PR만 사람이 승인·병합한다.
4. **staging에 제품 workflow가 반영된 뒤** 사람 관리자가 아래 설정안을 검토하고 적용한다. 아직 검사 결과를 만들 수 없는 상태에서 required check를 먼저 활성화해 PR을 막지 않는다. 기존 보호를 낮추는 임시 우회는 하지 않는다.
5. 규칙 GET 응답·실효 규칙·계정 권한을 다시 조회한다. 문서만 바뀐 staging PR에서도 두 검사가 보고되는지, pending/실패/승인 없음/stale 상태에서 병합이 차단되는지 확인한다. 성공과 사람 승인 후 병합 가능 상태까지만 확인하고 시험 PR은 닫는다. 에이전트는 병합 API를 시험 호출하지 않는다.
6. 비배포 임시 브랜치에서 직접 push/force push/삭제 차단을 별도로 확인한다. 설정 확인과 실제 거부 시험 결과를 구분해 MEG-169에 남긴다.

`staging → main`이나 `main → staging`을 소스 브랜치 그대로 PR하면 metadata의 이슈 ID 브랜치 규칙을 충족하지 않는다. `meg-<이슈번호>-<설명>` 브랜치를 사용한다. AI 계정이 작성하고 사람이 승인·병합한다. 사람이 자기 계정으로 작성한 PR은 자기 승인할 수 없으며 승인 수를 낮추지 않는다.

## 사람이 직접 적용할 항목

AI 실행 환경에 관리자 자격증명을 넣지 않는다. 김준성이 별도의 관리자 환경에서 Repository **Settings → Rules → Rulesets**를 연다.

1. 동일 이름/대상의 규칙이 이미 있으면 중복 생성하지 말고 기존 정책과 차이를 먼저 검토한다. main ruleset의 변경은 하지 않는다.
2. 대상·우회·승인·squash·strict·두 검사와 앱을 위 표대로 확인한다. JSON import를 지원하는 화면에서 파일을 가져오거나 해당 항목을 입력한다.
3. 적용 전후 JSON과 적용 시각, ruleset ID, 대상 staging SHA를 비공개 작업 기록에 남긴다. 관리 API 403이나 조회 응답의 필드 누락을 보호 성공으로 해석하지 않는다.

관리자의 별도 터미널에서 REST로 적용할 때도 검토한 파일만 사용한다. 아래 POST는 **생성**이므로 이미 존재하면 실행하지 않는다. 기존 규칙 수정은 현재 ID와 전체 응답을 먼저 대조한 뒤 별도 검토한다.

```powershell
# 사람 관리자 전용: 위 선행 조건과 설정안을 수락한 후 1회 생성
gh api --method POST repos/wnstjd5408/Vibecoding-project---4-/rulesets --input .github/rulesets/staging-protection.json
```

이 PR의 병합이나 로컬 검증 성공은 위 설정의 적용 증거가 아니다.

## 읽기 전용 검증

Python 표준 라이브러리만 사용하며 네트워크 호출이나 설정 변경을 하지 않는다. 저장소 루트에서 실행한다.

```powershell
python tools/check_staging_ruleset.py
python -m unittest discover -s tools -p "test_check_staging_ruleset.py" -v
```

첫 명령은 **제안 파일** 검사다. 실제 설정은 관리자 GET 응답을 별도의 비공개 임시 경로에 저장한 뒤 확인한다. `<ruleset-id>`는 적용 결과의 실제 ID로 바꾼다.

```powershell
gh api repos/wnstjd5408/Vibecoding-project---4-/rulesets/<ruleset-id> | Set-Content -Encoding utf8 $env:TEMP/staging-ruleset-after.json
python tools/check_staging_ruleset.py $env:TEMP/staging-ruleset-after.json --actual
gh api repos/wnstjd5408/Vibecoding-project---4-/rules/branches/staging
gh api repos/wnstjd5408/Vibecoding-project---4-/branches/staging --jq '{name,protected,sha:.commit.sha}'
```

`--actual`은 bypass 목록의 명시적 빈 배열과 `current_user_can_bypass: never`, 양의 정수 `id`, `source_type: Repository`, `source: wnstjd5408/Vibecoding-project---4-`도 요구한다. 임시 시험 저장소의 응답이나 출처를 알 수 없는 파일은 실제 대상의 적용 증거로 통과시키지 않는다. 권한 때문에 필드가 보이지 않으면 실패하며 관리자가 조회한 증거가 필요하다. AI 계정에서도 `current_user_can_bypass`를 별도로 조회한다. 응답의 추가 시각 등은 허용하되 보호 항목 누락·다른 대상·중복 규칙·다른 검사/앱·strict 해제는 거부한다. 오프라인 파일 검사는 응답의 진위나 최신성을 보장하지 않으므로 관리자가 방금 조회한 원본을 사용한다.

이 검증기는 **단일 ruleset의 구성**을 대조한다. 다른 ruleset/기존 branch protection의 중첩, CODEOWNERS의 실제 승인자 자격, 서버의 push 거부, 실제 CI 내용, 배포 차단은 보장하지 않는다. 전체 실효 규칙도 사람이 확인한다.

## 안전한 차단 시험과 정리

실제 staging에는 직접 push·force push·삭제를 시도하지 않는다. 거부를 기대하는 시험도 설정이 틀리면 반영될 수 있다.

1. 별도 공개 가능한 시험 산출물 이슈를 만든다. 관리자가 **배포/웹훅/비밀값/유료 실행이 발생하지 않음**을 확인한 임시 저장소 또는 임시 브랜치를 준비한다. 현재 Vercel Git integration이 연결된 원본 저장소에 새 브랜치를 만드는 것만으로 비배포가 보장되지는 않는다. 비배포 확인 전에는 생성·push 시험을 하지 않는다.
2. 규칙 적용 전 임시 대상 ref를 준비한다. 관리자가 위 JSON에서 이름과 대상 ref만 바꾼 동등 ruleset을 적용한다. 변경점과 그 외 동일성을 기록한다. 임시 대상에는 작업 결과가 없어야 한다.
3. 우회 없는 쓰기 계정으로 새 커밋 직접 push, 비 fast-forward 업데이트, 삭제를 각각 시도한다. 매번 서버 거부 결과와 원격 SHA/존재 여부가 유지되는지 확인한다. no-op push나 `--dry-run`은 서버 거부 증거로 인정하지 않는다.
4. PR 경로에서도 미완료·실패 검사, Code Owner 승인 없음, 새 push 후 승인 취소, 최신 base 반영 전/후 상태를 기록한다. 시험 브랜치의 대상 이름에 맞춘 CI 트리거와 동일한 검사 앱이 필요하다. 검사 실패가 없는데 다른 규칙 때문에 막힌 상태를 검사 차단의 증거로 쓰지 않는다.
5. 시험 PR은 병합 없이 닫는다. 사람이 임시 규칙만 해제한 뒤 임시 브랜치/저장소를 정리한다. staging 규칙은 유지한다. 정리 확인과 시험 이슈의 실제 상태를 남긴다.

임시 환경 거부 시험은 staging 자체의 파괴 시험이 아니다. staging의 실제 구성 증거와 별개로 기록한다. 승인된 안전한 시험 환경/관리자 적용이 없으면 부모 MEG-169의 AC-3은 미검증이다. MEG-176의 AC-3은 이 절차의 문서화와 검증 결과 기록을 다룬다.

## 2026-11-03 읽기 전용 확인

- GitHub 작성 계정은 `DustinCodingai`, 저장소 권한은 `WRITE`. main의 `current_user_can_bypass`는 `never`였다.
- main ruleset ID `25226738`은 활성, 승인 1명/Code Owner/새 push 승인 취소, squash/선형 기록, metadata만 필수, strict는 false였다. 이 작업에서는 바꾸지 않았다.
- staging은 `90ad798eeebfff39920aeee57450905c535385a4`, `protected: false`, 실효 rules API는 빈 배열이었다. 기존 branch protection 조회는 404였다.
- 조회 시 main 전용 13개, staging 전용 23개 커밋이 있었다. staging의 평가·렌더링 이력을 보존하기 위해 이 PR은 그 staging SHA에서 시작했다. 다른 세션 변경은 다시 조회해 출처를 구분한다.
- MEG-168 PR #121은 OPEN/미병합. head `0f536b5c4b251544efa83d0819f26193ea7162be`의 `Product CI`와 metadata가 앱 `15368`에서 성공했다. 이는 검사 식별 근거이며 staging 필수 검사 적용 근거는 아니다.
- 기존 MEG-175의 staging 시험 PR #123은 CI 성공 후 미병합 종료됐다. 새 규칙 하의 실패/strict/문서 전용 PR 시험을 대체하지 않는다.

## 환경변수 점검과 후속 결정

Vercel 플러그인은 해당 팀 조회를 403으로 거부했으나 기존 CLI의 프로젝트·팀을 명시한 목록 조회는 성공했다. 값은 복호화·다운로드하지 않았다. 아래는 **이름과 범위**만의 기록이다.

| 확인한 적용 범위 | 변수 이름 |
|---|---|
| Production과 Preview(staging)에 각각 존재 | `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `ALLOWED_ORIGINS`, `AWS_ROLE_ARN`, `AI_AUTH_MODE`, `GLOSSARY_IMAGE_BUCKET` |
| Preview(staging) 전용 | `EVAL_APPROVAL_ID` |
| Production 및 일반 Preview 공통 | `NOTE_IMAGE_BUCKET`, `AI_DAILY_BUDGET_USD`, `AI_MONTHLY_BUDGET_USD`, `AI_INPUT_USD_PER_MTOK`, `AI_OUTPUT_USD_PER_MTOK` |
| PR 브랜치 예외 | DB 연결/키·허용 출처·mock·일부 버킷 변수의 브랜치별 override가 존재 |

브랜치별 예외의 정확한 목록은 MEG-169 작업 기록에 둔다. 사용자별 운영 정보나 값은 공개 PR에 복사하지 않는다. **범위가 분리되어 있다는 것만 확인했으며 실제 Stage/PRD DB·키가 다른지는 검증하지 않았다.** 일반 Preview 공통 변수도 이름만으로 운영 자원 접근 가능 여부를 판단하지 않는다.

후속 이슈에서 사람이 각 예외의 연결 DB/사용 목적/활성 시험 여부/담당자/유지 또는 삭제 결정을 확인한다. 다른 세션의 진행 중 검증 변수를 자동으로 지우지 않는다. 이 작업은 비밀값 교체나 환경변수 삭제를 하지 않는다.

## 근거

- [GitHub rulesets REST API](https://docs.github.com/en/rest/repos/rules): required status check 출처 앱, strict, PR 및 ref 규칙의 필드 정의.
- [GitHub rulesets의 규칙](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets): 승인·검사·force push 규칙과 제한.
- [Vercel 환경변수](https://vercel.com/docs/environment-variables): 환경 및 Preview 브랜치별 범위.
