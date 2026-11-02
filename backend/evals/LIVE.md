# Staging 소량 평가 실행

## 범위와 준비

GPT-6 Luna 개발 D01~D03만 실행한다. 봉인 자료와 승인된 실행 identity는 바꾸지 않는다. 제품 AI 설명 API나 최종 평가가 아니다. 예산 금액과 실제 입력·출력은 비공개 파일/원장에 둔다.

1. 사람이 staging Supabase에 `sql/shared_ledger.sql`을 최초 한 번 적용하고 승인 행을 등록한다. 기존 행이나 횟수는 초기화하지 않는다.
2. Vercel Preview의 staging 브랜치에 `EVAL_APPROVAL_ID`를 등록한다. 기존 `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `AWS_ROLE_ARN`, `AI_AUTH_MODE=oidc`, 앱 세션/Origin 설정이 필요하다. 플랫폼 발급 `VERCEL_OIDC_TOKEN`을 사용한다.
3. 사람이 검토한 코드를 staging에 배포한다. 환경변수 변경 뒤 새 배포가 필요하다. Production 배포는 필요하지 않다.
4. staging 앱의 활성 운영자 계정으로 로그인한다. Supabase 키나 AWS 토큰을 요청 본문에 넣지 않는다.
5. 배포 함수가 STS·원장 통신과 단일 모델 호출(read timeout 60초)을 처리할 실행 시간을 제공하는지 확인한다. 플랫폼 timeout이 짧으면 먼저 배포 설정을 검토한다. 중단 후 자동 재전송하지 않는다.

## 요청 파일 만들기 (무과금)

backend에서 실행한다. 입력/출력은 저장소 밖 비공개 경로다.

```powershell
uv run python -m evals.staging --dataset <cases.jsonl> --manifest <manifest.json> --config <config.json> --output <new-private-request.json>
```

자료·봉인·설정을 검증하고 요청 파일을 새로 만든다. 출력한 identity_hash가 승인 행과 같아야 한다. 네트워크 호출은 없고 기존 파일을 덮어쓰지 않는다. 본문은 cases, manifest, config이며 최대 2MB다. 자료/채점 근거를 public 저장소나 로그에 남기지 않는다. 모델에는 선택한 용어·문맥·generation_evidence만 전송한다.

## 비공개 HTTP 계약

로그인한 staging 운영자는 `/api/internal/evals/console`에서 요청 JSON 파일을 선택하고 무과금 사전 점검을 제출한다. 통과한 다음 슬롯만 실행 버튼이 열린다. 실행 후 결과를 확인하고 다음 슬롯 전 사전 점검을 다시 수행한다. 결과 조회는 추론을 만들지 않으며 state JSON을 다운로드할 수 있다. 파일 선택/화면 진입만으로 호출되지 않는다. 결과는 텍스트로 표시하고 브라우저 저장소에 보관하지 않는다. 오류 시 자동 재시도 없이 원장을 확인한다.

화면과 스크립트 GET에도 staging/운영자 조건이 적용된다. 제품 메뉴에는 연결하지 않는다. 무과금 JS 시험은 backend에서 `node tests/eval_console_checks.cjs`로 실행한다. 아래 실행 API는 POST다.

모든 경로는 POST, 동일 요청 파일을 JSON 본문으로 받는다. 활성 운영자의 기존 세션 쿠키와 허용된 staging Origin 헤더가 필요하다. Swagger에는 표시하지 않는다. `VERCEL_ENV=preview`, `VERCEL_GIT_COMMIT_REF=staging`, 승인 ID, OIDC 모드가 맞지 않으면 404다. URL을 숨기는 것은 인증을 대신하지 않는다.

| 경로 | 동작 |
|---|---|
| `/api/internal/evals/preflight` | 봉인·설정·승인 해시·원장 상태 확인 후 STS 인증. 예약·Converse 호출 없음. ready, next_slot, provider_calls 반환. 모델 권한은 unverified |
| `/api/internal/evals/run/D01` | 첫 슬롯 단 한 번 실행 |
| `/api/internal/evals/run/D02` | D01 성공 후 두 번째 슬롯 실행 |
| `/api/internal/evals/run/D03` | D02 성공 후 세 번째 슬롯 실행 |
| `/api/internal/evals/status` | 원장 결과를 T4용 state JSON으로 조회. STS·모델 호출·예약 없음 |

D01 결과 확인 후 D02, D03 순서로 요청한다. 서버리스 실행 시간을 고려해 요청당 한 슬롯만 처리한다. identity는 전체 세 슬롯으로 계산하므로 기존 승인 SQL은 바꾸지 않는다. run/status 응답은 비공개 파일로 저장한다. 자동 재전송 루프는 만들지 않는다.

인증 거부는 401/403, 잘못된 본문은 422/413, 원장·인증 교환·실행 거부는 503이다. 503은 재시도 지시가 아니다. status/SQL로 먼저 확인한다. 오류에 원문·비밀값·원격 오류 내용을 넣지 않는다. API 응답은 private, no-store다.

## 중복·중단 처리

공유 DB가 비용/횟수의 원본이다. 예약 RPC는 승인 행을 잠그고 슬롯 고유성·허용 슬롯·해시·3회·예산·in-flight/unknown을 검사한다. 실행 진입점은 앞 슬롯의 error도 후속 실행 차단으로 처리한다. 사전 조회는 동시성을 보장하지 않으며, 실제 호출 직전 RPC가 최종 차단한다.

다른 서버 인스턴스나 새로운 임시 디렉터리에서도 새 호출 권한은 생기지 않는다. 예약 뒤 중단·결과 저장 실패는 started로 남아 수동 확인 전 추가 호출을 막는다. unknown/over_limit도 자동 재호출하지 않는다. 임시 파일은 요청 종료 시 제거하고, 완료 출력과 usage는 DB에 보존한다. 응답을 잃으면 status로 조회한다. 미저장 출력 복구를 보장하지 않는다.

## CountTokens 없는 비용 관리

`luna-service-envelope-2026-11-02`는 서비스 컨텍스트 전체 1,050,000과 장문 최대 입력 단가, 출력 상한 8,192로 보수적으로 예약한다. 실제 입력 토큰 수 추정이 아니다. UTF-8 요청 16,000 bytes 제한은 별도 payload 제한이며 토큰 수로 환산하지 않는다. 초과하면 자르지 않고 거부한다. 기존 input_bound 경로는 계속 거부한다.

모델/정책/설정을 바꾸면 identity가 달라져 기존 승인에서 실행되지 않는다. 실제 usage와 캐시 항목을 보존하고 cost_upper_estimate를 계산한다. AWS 청구 확정액은 아니며 캐시 의미·단가는 첫 실측 시 대조한다. STS와 추론 SDK의 자동 재시도는 없다.

## T4 연결

status 응답을 비공개 state.json으로 저장한다.

```powershell
uv run python -m evals dev-review-template --dataset <cases.jsonl> --state <state.json> --output <new-reviews.json>
uv run python -m evals dev-report --dataset <cases.jsonl> --state <state.json> --reviews <reviews.json> --output <new-report.json>
```

JSON·세 요약·출처 ID는 기계적으로 검증한다. 사실·핵심 개념·조건·명료성·완결성 5점과 O/X는 사람 검수 대상이다. 미검수는 pending이다. 개발 결과는 golden_status=NOT_EVALUATED, product_status=INCOMPLETE다.

## 검증 한계와 해제

로컬 모의 테스트는 인증 거부·staging 제한·원장 장애·중복/동시 요청·3슬롯 개별 실행·결과 조회·unknown/잘림/상한 초과 후 차단을 검증한다. 실제 staging DB 권한·OIDC trust·모델 접근·플랫폼 실행 시간은 배포 후 확인해야 한다. 원격 SQL은 사람이 적용한다. 평가 후 staging EVAL_APPROVAL_ID를 제거하고 재배포해 경로를 닫는다. 원장과 봉인 자료는 삭제하지 않는다.
