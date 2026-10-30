# 골든 셋 형식·검증기

## 사람 채점 집계

`python -m evals review-template --dataset CASES --state PRIVATE_STATE --output PRIVATE_REVIEW`
은 채점 대기 양식을 만든다. `report --dataset CASES --state PRIVATE_STATE --reviews PRIVATE_REVIEW --output PRIVATE_REPORT --seed 0`
은 사람이 작성한 판단만 집계한다. 모든 출력은 새 파일이며 기존 파일을 덮어쓰지 않는다.
리뷰는 출력 해시·자료 버전·검수자·근거·고유 주장 ID/판정·필수 항목별 bool·중대 오류 수·5항목 O/X를 포함한다.
미검수는 null로 남긴다. 합계 4/5와 주장 정확도 95%를 별개로 보고한다.
각 회차/위험 구간의 응답 평균과 주장 가중값, 분자/분모를 출력한다.
중대 오류·필수 항목 누락·호출 실패는 평균과 관계없이 FAIL이다.
적절한 무사실 예외는 정확도 N/A이고 미검수·미합의는 INCOMPLETE이다.
독립 검수는 중대 오류/불일치 전부와 나머지 20%를 seed로 고정한다.
두 번째 검수자와 합의 기록이 없으면 PASS하지 않는다.
현재 제품 통합·사용자 이해도는 검증하지 않으므로 product_status는 INCOMPLETE로 남긴다.
fake 결과의 PASS는 집계 논리 시험이며 AI 품질 통과가 아니다.

## 오프라인 실행기

`python -m evals run --dataset CASES --manifest MANIFEST --config CONFIG --output-dir PRIVATE_DIR --dry-run`
은 버전·입력 상한·예산과 예정 슬롯을 검사한다. `--fake`는 같은 계약으로 모의 출력만 저장한다.
live 옵션이나 공급자 연결은 없다. RunConfig JSON 필드는 runner.py를 따른다.
기본 토큰 계산은 문자 수 기반 **시험용**이다. 실제 모델 토큰·단가·품질 검증으로 사용하지 않는다.
최대 입력/출력 기준 전체 슬롯 예약액이 예산을 넘으면 호출 전에 거부한다.
state.json은 비공개 경로에 원자적으로 저장되며 설정·입력 해시가 다른 재개는 거부한다.
완료/실패 슬롯은 재호출하지 않는다. started/unknown은 자동 재실행하지 않고 검토를 요구한다.
강제 프로세스 종료로 .lock이 남으면 프로세스 종료와 상태를 사람이 확인한 뒤 잠금만 해제한다.
불명 슬롯을 pending으로 바꾸지 않는다. 재시험이 필요하면 별도의 run_id/디렉터리로 실행한다.
모의 비용은 설정 단가 기반 시뮬레이션이며 실제 과금액이 아니다. usage 불명은 예약액을 유지한다.

이 도구는 **오프라인 자료 검사**만 한다. AI 호출, 의미 자동 채점, 95% 정확도 판정은 하지 않는다. 실제 자료와 검수 결과는 저장소 밖 접근 제한 폴더에 보관한다. 저장소에는 합성 시험만 둔다.

## 실행 (backend에서 PowerShell)

```powershell
$env:EVAL_DATA_DIR = 'C:/path/to/private/dataset'
uv run python -m evals validate --dataset "$env:EVAL_DATA_DIR/cases.jsonl"
uv run python -m evals validate --dataset "$env:EVAL_DATA_DIR/cases.jsonl" --final
uv run python -m evals freeze --dataset "$env:EVAL_DATA_DIR/cases.jsonl" --reviewer '검수자 식별자' --output "$env:EVAL_DATA_DIR/manifest.json"
uv run pytest tests/test_eval_dataset.py -q
```

- `validate`: 부분 초안도 검사한다. 빈 세트·잘못된 값·분할 누출은 실패.
- `validate --final`: **개발 20개와 최종 후보 40개를 모두 포함한 파일**을 받는다. 전체 개수 및 최종 위험별 분포까지 검사한다. 사람 검수 여부와 무관하게 형식만 검사한다.
- `freeze`: 전체 구성과 모든 사례의 `review_status=approved`, 비어 있지 않은 `reviewer`를 요구한다. 초안은 거부한다. 새 매니페스트만 쓰며 기존 파일은 덮어쓰지 않는다. Git 저장소 내부 출력 경로(연결 worktree 포함)를 거부한다.
- 종료 코드: 성공 0, 자료/파일/검수 오류 1, 명령 인자 오류 2. 오류에는 행 번호·고정 오류 코드만 출력하며 원문·필드 값은 출력하지 않는다.
- 네트워크 라이브러리·앱·Bedrock 모듈을 import하지 않는다. `run --live` 등 모델 실행 명령은 없다.

## JSONL v1

UTF-8 또는 UTF-8 BOM, 줄마다 객체 하나. 빈 줄은 무시한다. 중복 JSON 키·NaN·알 수 없는 필드·필수 필드 누락은 실패한다. Python dataclass 정의는 `schema.Case`가 원본이다.

| 필드 | 형식/의미 |
| --- | --- |
| case_id | 세트 내 고유 ID, 영문/숫자로 시작, 이후 영문/숫자/._-, 최대 100자 |
| group_id | 동일 개념·근접 변형을 묶는 ID. 개발/최종 양쪽에 걸치면 실패 |
| source_id | 원본 노트 ID(합성은 synthetic ID). 개정이 달라도 개발/최종에 나누면 실패 |
| split | dev / final |
| risk_bucket | 아래 분포표의 값 |
| subject | 실제 과목 또는 합성 과목. 비어 있지 않은 문자열 |
| note_revision | 1 이상 정수. bool·문자열 불가 |
| source_text, term | 비어 있지 않은 문자열. term은 실제 선택한 원문 |
| start, end | 유니코드 코드포인트 기준 시작 포함·끝 제외. `source_text[start:end] == term`. UTF-16 단위가 아님 |
| expected_response | answer / qualified / abstain |
| required_concepts | 반드시 보존할 의미/예외 대응. 비어 있지 않은 문자열 목록 |
| required_conditions | 필수 조건 목록. 조건이 없으면 빈 목록, 필드 생략은 불가 |
| forbidden_errors | 금지할 오해/중대 오류 목록, 하나 이상 |
| generation_evidence | 생성 입력으로 제공할 검수 근거, 없으면 빈 목록 |
| grading_evidence | 사람이 채점할 때 대조할 근거/출처, 하나 이상. 생성 프롬프트에 넣지 않음 |
| comprehension_questions | 하나 이상 객체. 각 객체는 question과 key_points(2개 문자열)만 가짐 |
| author | 작성자 식별자 |
| reviewer | 검수자 식별자. draft에서는 빈 문자열 가능, approved에서는 필수 |
| review_status | draft / approved |
| provenance | synthetic / curated (실제 자료에서 선정) |

리스트 안 빈 문자열과 같은 항목의 정확한 중복은 거부한다. 질문별 2개 key_points는 각 1점의 채점 기준이다. source_text는 노트 전체가 아니라 추출한 입력 문맥이므로 같은 source_id + note_revision에서 서로 다른 문맥을 사용할 수 있다. 동일 본문의 교차 분할도 거부한다. 자동 검사는 의미가 유사한 문장을 찾아주지 못하므로 group_id와 과목 대표성은 사람이 검수한다. revision은 양의 정수만 검사하며 실제 앱 최신 개정·문맥과의 대조는 통합 단계다.

### 최종 후보 40개 분포

| risk_bucket | 개수 | expected_response |
| --- | --- | --- |
| basic | 8 | answer |
| polysemy | 8 | answer |
| conditions | 8 | answer |
| precision | 8 | answer |
| insufficient | 2 | qualified / abstain |
| incorrect_source | 2 | qualified / abstain |
| input_boundary | 2 | qualified / abstain |
| injection | 2 | qualified / abstain |

자료 내 지시문 사례도 공격 문장은 따르지 않고 용어를 설명하는 **qualified** 응답으로 둔다. 자동 시스템 거부와 올바른 용어 설명은 실제 평가 때 구별한다. 입력 상한 사례는 실제 상한이 확정되기 전에는 합성 초안이고, 길이 테스트 합격 증거가 아니다.

## 검수와 봉인

1. 작성자는 사례를 draft, reviewer 빈 값으로 둔다.
2. 사람은 출처·문맥·필수 항목·금지 오해·질문·분할·대표성을 검수한다. 잘못된 원문 사례는 의도적 오류임을 확인하고, 생성 입력에 교정 근거가 없다면 확인 필요 대응을 기대한다.
3. 검수자가 실제로 확인한 사례만 approved로 바꾸고 본인 식별자를 기록한다. 이 CLI는 인증 시스템이 아니며 검수 행위 자체를 증명하지 않는다.
4. 모든 자료 검수 후 `validate --final`, `freeze`를 실행한다. 표본이 합성이면 봉인하더라도 실제 서비스 대표성이 검증됐다는 뜻이 아니다.
5. 매니페스트는 사례별 내용 해시, 정렬된 해시 맵 기반 dataset_version, UTC 시각, 과목/출처/분할 집계만 담는다. 행 순서를 바꿔도 버전은 같고 사례 내용·검수 메타데이터가 바뀌면 달라진다.
6. 봉인 뒤 사례를 수정하면 다시 draft로 되돌려 검수하고 새 파일명으로 봉인한다. 이전 매니페스트는 보존한다. 향후 실행기는 입력 해시와 봉인 버전을 대조해야 한다.
7. 최종 사례를 프롬프트 개선에 쓰면 개발 세트로 이동시키고 새 홀드아웃을 보충한다.

**형식 검사 성공 ≠ CS 내용 검수 완료 ≠ AI 품질 평가 통과.** 이 패키지는 처음 두 단계 사이에서 실수를 줄이는 도구다.
