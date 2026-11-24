# WRAG-DEV 무과금 위키 검색 평가

CS Agent 위키 검색(`WikiRetriever`, `wiki-keyword-v1`)을 고정한 사전 스냅숏에 돌려 E1~E6을 잰다(MEG-251, 내부 위키 우선 RAG 설계 v0.3 5~7절). 모델·DB·네트워크를 부르지 않는다. 목표값은 아직 없으므로(MEG-163 W8) 결과는 언제나 `MEASURED`·`NOT_JUDGED`다. **측정값이 좋다는 것은 위키 플래그를 켜도 된다는 뜻이 아니다.** 켤지는 T4d(MEG-253)에서 사람이 정한다.

## 실행 (backend에서 PowerShell)

```powershell
uv run python -m evals.wiki_retrieval validate --snapshot tests/fixtures/wrag_dev/snapshot.json --cases tests/fixtures/wrag_dev/cases.jsonl
uv run python -m evals.wiki_retrieval run --snapshot tests/fixtures/wrag_dev/snapshot.json --cases tests/fixtures/wrag_dev/cases.jsonl --output C:/path/outside/repo/result.json --k 5
uv run pytest tests/test_eval_wiki_retrieval.py tests/test_agent_wiki_search.py -q
```

- `validate`: 형식과 스냅숏 대조만 한다. 검수 완료나 품질 판단이 아니다.
- `run`: 검증을 통과한 뒤 측정해 새 파일에 쓴다. 기존 파일을 덮어쓰지 않고, Git 작업 폴더 안(연결 worktree 포함)에는 쓰지 않는다.
- `--k`: 1~5(근거 문단 상한). E3·E4는 상위 k개로 잰다. E1·E5·E6은 검색이 돌려준 문단 전체로 잰다.
- 종료 코드: 성공 0, 자료·파일 오류 1, 인자 오류 2. 오류는 `line N: 코드` 형식이며 사례 원문을 출력하지 않는다.
- 이 명령은 앱의 검색 함수(`app.agent_wiki_search`)를 import해 그대로 돌린다. 골든 셋 검증기(`python -m evals`)와 달리 앱 코드를 쓰지만, DB 래퍼는 쓰지 않고 스냅숏을 메모리에서 넘긴다.

## 자료 보관

- 저장소에는 합성 자료만 둔다(`tests/fixtures/wrag_dev`). 실제 사전에서 뽑은 스냅숏과 실제 사례, 측정 결과는 저장소 밖 접근 제한 폴더에 둔다.
- `provenance`가 `curated`인 스냅숏이나 사례가 Git 작업 폴더 안에 있으면 명령이 거부한다(`curated_inside_git`).
- 결과 파일에는 사례 ID, 경로, 문단 ID·절 이름·원문 해시, 개수만 들어간다. 질문·선택·사전 원문은 넣지 않는다.

## 스냅숏 `wrag-snapshot-v1`

`{"format": "wrag-snapshot-v1", "provenance": "synthetic"|"curated", "terms": [행...]}`. 행은 `terms` 테이블 행에 `glossary_entries` 내장을 붙인 모양이다(`SupabaseClient.list_wiki_entries` 응답과 같다): `id`, `key`, `label`, `source`, `glossary_revision`, `glossary_entries`(`{"body_markdown": ...}` 또는 `null`).

- 지운 항목(`source = 'ai'`, `glossary_entries` 없음)과 어긋난 행도 그대로 넣는다. 검색이 이런 행을 빼는지(S1)와 E6 누출을 재는 데 쓴다.
- 실제 DB에서 만들 때는 DB 필터를 거치지 않은 행(지운 항목 포함)을 사람이 비공개 경로로 내보낸다. 이 명령은 DB를 읽지 않는다.
- `glossary_revision`은 T4a(MEG-249) 열이다. 그 마이그레이션 전 DB에는 없으므로 실제 스냅숏은 T4a 적용 뒤에 만든다.

## 사례 `wrag-dev-v1` (JSONL)

줄마다 객체 하나. 모든 필드가 필수이고 알 수 없는 필드·중복 키·NaN은 실패한다.

| 필드 | 형식/의미 |
| --- | --- |
| case_id | 고유 ID. 영문/숫자로 시작, 이후 영문/숫자/._-, 최대 100자. 예: `WRAG-DEV-001` |
| provenance | synthetic / curated |
| author, reviewer, review_status | 작성자, 검수자, draft / approved(approved는 reviewer 필수). 결과 identity에 상태별 개수가 남는다 |
| action | open(노트에서 표기를 누름) / ask(AI에게 질문) |
| text | open이면 누른 표기, ask면 질문(최대 1,000자) |
| role | member / operator. 사전은 모두 공개(W5)라 검색 결과는 역할과 무관해야 한다 |
| origin, wiki_ref | none / note / wiki. wiki면 `wiki_ref`(`glossary:{term_id}`)가 필수이고, 아니면 null |
| topic_label | 대화 주제(문맥 낱말로만 쓴다) |
| selections | `[{"note_id": 정수, "text": 선택 문장}]`. 노트 선택 문맥이며 근거가 아니다 |
| expected_route | P1 / P3 / P4 / P5 / P6(아래) |
| expected_term_id | open + P1일 때 대표 페이지(사전 항목) term_id, 그 밖에는 null |
| gold | 정답 문단 `[{"source_id", "section", "text_sha256"}]`. 해시는 `note_chunks`로 나눈 문단 원문의 SHA-256이다 |
| required_conditions | 정답 문단에 들어 있는 필수 조건 구절(E4). 없으면 빈 목록 |
| forbidden_texts | 결과와 로그에 나오면 안 되는 문자열(카나리). 비공개 노트 선택 문장, 지운 항목 본문 등 |
| forbidden_source_ids | 결과에 나오면 안 되는 source_id(지운 항목 등) |

규칙: open은 P1·P4만, ask는 P3·P5·P6만 쓴다. P3은 origin wiki, P5는 wiki가 아닌 origin이다. selections는 origin note에서만 쓴다. gold의 source_id를 forbidden_source_ids에 넣을 수 없다. ask에서 gold가 비어 있으면 P6(근거 없음)이고 required_conditions도 비어야 한다. gold·expected_term_id·wiki_ref는 스냅숏의 지금 있는 항목과 맞아야 한다(`gold_not_in_snapshot` 등). 사전 본문이 바뀌면 해시가 달라지므로 사례를 다시 검수한다.

P2(별칭, MEG-198), P7(부분 근거, 모델 필요), P8(웹 보완, T4 밖), P9(별칭·대표 페이지 연결 오류)는 지금 모델 없이 잴 수 없어 `route_not_evaluable`로 거부한다.

## 지표

| 지표 | 분모 | 판정 |
| --- | --- | --- |
| E1 경로 | 모든 사례 | open: 표기가 사전 항목 하나와 맞으면 P1, 아니면 P4. ask: 검색 결과가 0개면 P6, 아니면 origin wiki는 P3, 그 밖은 P5 |
| E2 대표 페이지 연결 | open 사례 | 표기 → term_id가 expected_term_id와 같다(미연결은 null과 같아야 한다). 노트 강조(E05)와 같은 찾기 규칙, 별칭 없음(W4) |
| E3 Recall@k | gold가 있는 ask 사례 | 정답 문단이 하나라도 상위 k개 안에 있다. 정답 문단 단위 비율(`E3_gold_paragraphs_at_k`)도 함께 낸다 |
| E4 필수 조건 확보 | E3 사례의 필수 조건 전체 | 조건 구절(공백 정리)이 상위 k개 문단 하나 안에 잘리지 않고 들어 있다 |
| E5 근거 없음 | gold가 비어 있는 ask 사례 | 검색 결과가 0개다 |
| E6 누출 | ask 사례 | 건수. output: 위키가 아닌 문단, 스냅숏에 지금 있는 항목이 아닌 source_id(사례에 적지 않아도 센다), 금지 source_id, 금지 문자열이 결과에 나온 수. log: 검색 중 `app.agent` 로그에 질문·선택 문장·결과 문단·금지 문자열이 나온 수. 단계와 개수만 있는 줄(`stage=… key=숫자`, `source_kind=note|wiki`)은 글을 담을 수 없으므로 보지 않는다 |

ask 사례의 E1은 사례 규칙상 "근거를 찾았는가"와 origin으로 정해진다. 그래서 E3·E5와 겹치며, 맞는 문단을 찾았는지는 E3이 본다.

모든 비율은 분자·분모를 함께 낸다. 합성 셋의 값은 명령이 도는지 보는 시험값이지 품질 근거가 아니다. 작은 개발 셋의 결과로 목표 달성을 말하지 않는다(설계 6.2).

## 결과 `wrag-retrieval-eval-v1`

- `identity`: 사례 셋(개수·해시·검수 상태), 사전 스냅숏(행 수, 항목 수, 뺀 행 수, 문단 수, 스냅숏 해시, 항목 해시), `retriever_version`, `chunk_rule_version`(`note-chunks-v1`)과 문단 상한, k, 검색 매개변수(문단 상한, 항목당 문단 수, 가산점, 문맥 가중치). 하나라도 바뀌면 이전 결과를 재사용하지 않는다.
- `metrics`: E1~E6.
- `measurements`: ask 사례별 돌려준 문단 수·글자 수와 검색 지연(ms)의 평균·중앙값·최댓값. 문단 상한·항목당 문단 수·검색 시간 상한을 정할 때 본다(설계 5절). 지연은 실행 환경마다 다르다.
- `cases`: 사례별 경로, 일치 여부, 돌려준 문단(순위, source_id, 개정, 절, 원문 해시, 글자 수), 지표별 값.
