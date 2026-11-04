# 현재 위키 설명 프롬프트 기준선

내부 개발 기준선은 `wiki_v044.py`와 `prompts/wiki_v044/`의 세 프롬프트다.
요청 조립과 구조 검증을 같은 버전으로 관리한다. 모듈은 모델을 호출하지 않는다.

| 단계 | 입력 | 역할 |
|---|---|---|
| evidence | term, sources | 정의·예시 가능 여부 |
| correction | term, user_note(unverified), sources | 확인된 교정과 미해결 주장 분리 |
| generation | 위 입력과 조립된 policy | 근거 기반 설명과 한계 안내 |

정의가 없더라도 근거의 명세 사실로 예시·교정이 가능하면 limited 응답으로 제공한다.
미해결 주장은 `open_claims`의 ID와 `limitations.claim_id`를 연결한다.
프롬프트는 새 전문용어의 짧은 풀이, 근거의 확신 수준 보존, 구체적인 활용 예시를 요구한다.
노트 자체는 기술 근거로 승격하지 않는다.

## 무과금 요청 준비

backend 디렉터리에서 실행한다. 입력과 결과는 저장소 밖 비공개 경로를 사용한다.

```sh
python -m evals.wiki_v044_prepare evidence --input INPUT.json --output EVIDENCE_REQUEST.json
python -m evals.wiki_v044_prepare correction --input INPUT.json --output CORRECTION_REQUEST.json
python -m evals.wiki_v044_prepare generation --input INPUT.json --policy POLICY.json --output GENERATION_REQUEST.json
```

INPUT.json은 `term`, `user_note: {text, trust: "unverified"}`, `sources: {"1": "근거"}`다.
generation의 policy는 `definition_available`, `example_mode`, `correction`, `open_claims`를 포함한다.
정책은 `assemble()`로 검증·조립하며, `prepare_prediction()`은 주입된 transport로 두 판정 단계를
연결하고 생성 요청까지 준비한다. 테스트에서는 mock만 사용한다.
실제 transport를 연결하려면 호출 승인·영속 원장·횟수 제한·실패 보존을 먼저 연결해야 한다.

출력 파일은 기존 파일을 덮어쓰지 않는다. 출력에는 전체 입력이 포함되므로 공개 PR에 첨부하지 않는다.
request_hash는 모델·설정·시스템 프롬프트·스키마·본문 전체의 canonical JSON 해시다.
evidence 캐시는 동일 버전/요청에 한해 프로세스 내 재사용하며 교정 입력은 재사용하지 않는다.

## 검증과 한계

```sh
python -m pytest tests/test_wiki_v044.py -q
```

기존 Product backend unit CI가 이 파일을 포함한다. 별도 모델 자격증명은 사용하지 않는다.
교정문의 URL·인라인 인용, 별칭 타입·공백·중복, claim ID·구절 중복,
예시·정의·한계 안내 구조를 확인한다. `note_quote`는 원문으로 보존한다.
URL 검사는 명시적 scheme/WWW/프로토콜 상대 링크를 대상으로 하며 모든 난독화 링크를 탐지하지 않는다.

구조 PASS는 의미 품질 PASS가 아니다. 잘못된 정의, 지지되지 않는 인용, 다른 쟁점에 대한 안내,
판정기의 미해결 주장 누락은 별도 의미 검수가 필요하다. 응답은 `semantic_status=NOT_EVALUATED`로 기록한다.

기존 `wiki_live.py`는 이전 Markdown 출력과 승인·원장을 재현하는 경로다. 이 버전으로 묵시적으로
교체하지 않는다. 새 분리 정책은 단계 수와 출력 스키마가 다르므로 과거 승인으로 호출할 수 없다.
제품 API·DB·봉인 데이터·과거 평가 점수는 이 변경에 포함하지 않는다.
