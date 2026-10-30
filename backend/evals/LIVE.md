# 소량 실제 호출 준비 상태

`live.py`는 Bedrock Converse 어댑터와 최대 3개 개발 슬롯의 예약·저장·재개 경계를 구현한다. 기존 fake 실행기와 제품 API는 바꾸지 않는다. 현재는 실행 가능한 live CLI를 제공하지 않는다.

## 실행 차단 조건

- 대상 모델의 검증된 입력 토큰 계산/상한이 없어 `input_bound`는 항상 거부한다. 문자 수나 추정 tokenizer를 실제 계산으로 대체하지 않는다.
- 승인된 환경의 Bedrock 클라이언트가 필요하다. `SDK_CONFIG`로 생성하고 `total_max_attempts=1`을 확인한다. 자격증명은 환경에서 제공하며 코드에 넣지 않는다.
- 동일 승인에는 하나의 비공개 원장 디렉터리를 재사용한다. 새 디렉터리를 만드는 행위까지 막는 전역 예산 서비스는 아니다. 여러 호스트/프로세스의 별도 원장을 합산하는 운영 기능은 범위 밖이다.

## 저장과 비용

호출 직전에 횟수와 예약액을 원자적으로 저장한다. 중단·사용량 불명·상한 초과는 수동 확인 전 재개를 막는다. 오류 문구나 자격증명은 기록하지 않는다. 출력과 usage는 비공개 디렉터리에 보존한다. 잘린 출력에도 usage를 버리지 않는다.

캐시 읽기는 일반 입력 단가, 쓰기는 입력의 1.25배로 보수적으로 계산한다. `cost_upper_estimate`는 usage 기반 추정치이며 AWS 청구 확정액이 아니다. 미확인 비용은 0으로 기록하지 않는다. 실측 입력 상한 초과는 사후 탐지일 뿐, 사전 토큰 검증을 대신할 수 없다.

## 남은 검증

실제 인증·모델 호출·정확한 토큰 계산 또는 입증된 보수 상한은 미검증이다. 출력 형식·출처 ID 검증과 개발용 T4 연결은 무과금으로 시험했다. CS 내용·출처의 사실적 뒷받침은 사람 검수 대상이다. 토큰 게이트를 우회해 실행하지 않는다.

## 인증 연결 순서

1. 저장소 배포 가이드에 따라 승인된 staging 환경을 사용한다. 운영 비밀값을 PR Preview나 로컬로 복사하지 않는다. AWS 로컬 프로필 파일이 있다는 사실만으로 평가용 인증이 승인·유효하다고 판단하지 않는다.
2. AWS IAM의 Vercel OIDC 공급자와 평가 역할을 확인한다. trust policy의 issuer·audience·subject를 실제 Vercel 팀·프로젝트·환경에 정확히 제한한다. 예제 ARN이나 subject를 그대로 사용하지 않는다. `sts:AssumeRoleWithWebIdentity`로 임시 자격증명을 발급한다.
3. 역할에는 대상 추론 프로필 및 해당 글로벌 추론 경로의 foundation-model에 필요한 `bedrock:InvokeModel`만 허용한다. Global 프로필의 목적 리전을 단일 서울 리전으로 가정하면 안 된다. 계정 SCP와 프로필 리소스는 AWS 관리자에게 확인한다.
4. 승인된 환경에 `AWS_ROLE_ARN`을 등록하고 플랫폼이 발급하는 `VERCEL_OIDC_TOKEN`을 사용한다. 토큰을 문서·채팅에 붙여 넣지 않는다. `live_auth.oidc_transport()`가 STS → 임시 자격증명 → SigV4 클라이언트를 만든다. STS와 Bedrock 모두 SDK 재시도는 0회다. Bearer로 자동 전환하지 않는다.
5. 인증 점검에 별도의 유료 ping을 쓰지 않는다. 토큰 게이트와 예산 점검이 완료된 뒤 첫 개발 슬롯으로 모델 권한까지 확인한다. 인증 실패·timeout도 원장을 확인하고 자동 재시도하지 않는다.

현재 코드는 인증 팩토리만 제공한다. staging에서 실행할 비공개 작업 경로·영속 원장 저장소는 아직 연결되지 않았다. 서버리스 임시 파일을 영구 원장으로 쓰지 않는다. 사람이 검토·병합하는 배포 절차를 건너뛰지 않는다. OIDC가 불가능할 때만 기존 `docs/ai-credentials.md`의 대체 키 절차를 검토한다.

## CountTokens 없이 상한을 입증하는 방법

**채택 조건:** 다음 둘 중 하나에 대한 모델 버전별 근거가 필요하다.

- 공급자가 공개한 정확한 tokenizer + Converse 메시지 직렬화/특수 토큰/숨은 입력 오버헤드 규칙. 전체 system/messages를 동일 규칙으로 계산한다.
- 공급자가 보장한 보수 상한. 예를 들어 UTF-8 byte 기반 BPE이고 모든 추가 토큰의 최대치 H가 입증된 경우에만 `입력 상한 = 모든 입력 텍스트의 UTF-8 byte 합 + H`를 쓸 수 있다. H를 임의의 여유분으로 정하지 않는다. 자료·JSON 문자열·역할·특수 토큰을 빠뜨리지 않는다.

확인할 산출물은 모델 ID/버전, tokenizer 이름·파일 해시, 직렬화 규칙, 공식 근거, 고정 프롬프트 해시, 각 실제 요청 해시와 계산 상한이다. 모델 별칭·프롬프트·직렬화 변경 시 증거를 무효화하고 재검증한다.

무과금 경계 시험은 한국어·영문·이모지·결합문자·코드·공백·JSON escape·인젝션 문자열, 상한 직전/동일/직후를 포함한다. 실제 3회 usage는 계산과의 일치 확인에 사용한다. 3개 실측의 최대치에 20% 등을 더한 값은 일반적인 상한 증명이 아니다.

현재 공식 근거에서 Luna의 tokenizer와 Converse 오버헤드 상한을 확보하지 못했다. 따라서 `input_bound`는 계속 거부한다. 지원하지 않는 CountTokens 호출, 다른 모델의 CountTokens, 임의의 tiktoken 인코딩을 대체 근거로 쓰지 않는다. 필요하면 공급자에 모델별 상한을 문의하거나 CountTokens 지원 모델의 품질·단가를 별도 검토한다. 모델 변경은 이번 승인에 포함하지 않는다.

## 출력 검증과 T4

`live_output.validate_output`은 JSON 필드, 한 줄 3개 요약, 비어 있지 않은 설명, 출처 ID 허용 목록과 본문 `[n]`의 일치, 생성 URL 금지를 검사한다. 사용한 출처 목록은 입력 자료에서 가져와 하단에 표시할 수 있는 구조로 저장한다. UI 콜아웃 렌더링은 이 평가 도구 범위 밖이다. 형식 실패는 재생성 없이 error로 저장한다.

```powershell
uv run python -m evals dev-review-template --dataset <private-cases.jsonl> --state <private-state.json> --output <new-private-reviews.json>
uv run python -m evals dev-report --dataset <private-cases.jsonl> --state <private-state.json> --reviews <private-reviews.json> --output <new-private-report.json>
```

개발 슬롯을 `D01:1`처럼 바꿔 기존 T4 검수 양식·판정 함수를 사용한다. 사람 검수가 없으면 pending, 호출 실패·상한 초과는 0점/X다. 정상 출력은 기존 사실·개념·조건·명료성·완결성의 5점과 O/X를 검수하며, 출력 해시가 바뀌면 옛 검수는 거부한다. 개발 3건은 최종 120건에 섞지 않으며 `golden_status=NOT_EVALUATED`, `product_status=INCOMPLETE`로 남긴다.

공식 근거: [모델 기능](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-luna.html), [SDK 재시도](https://docs.aws.amazon.com/boto3/latest/guide/retries.html).
