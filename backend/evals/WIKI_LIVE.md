# 위키 개발 사례 live 평가

승인된 개발 manifest를 Bedrock에 보내는 로컬 전용 실행기다.
기존 staging API와 최종 골든 평가 경로는 변경하지 않는다.
DB·검색은 연결하지 않고 승인된 합성 근거를 사용한다.

## 입력과 승인

cases.json과 manifest.json을 저장소 밖 비공개 경로에 둔다.
make_plan은 원문·용어·근거만 허용 목록으로 전달하며, 참조 정답과
평가 기준·승인 상태는 요청에서 제외한다. 근거는 숫자 인용 ID로 변환하고
원래 ID·URL과의 연결은 로컬에서 유지한다.

initialize는 승인 ID, 실행 ID, 예산, live/mock 구분, 요청/데이터 해시,
고정된 파일 원장 경로를 묶는다. 기존 파일을 덮어쓰지 않는다.
승인 파일 자체는 사용자 승인의 대체물이 아니다. 실행 담당자는 사용자의
승인 범위를 확인한 뒤 한 번만 초기화해야 한다.

원장 파일과 승인은 한 머신의 같은 비공개 경로에서만 사용한다.
복사본을 별도 실행하거나 원장을 삭제해 재승인하는 것은 지원하지 않는다.
파일 원장은 로컬 운영자에 대한 변조 방지 저장소나 분산 원장이 아니다.
여러 호스트/서버리스 실행에는 이 경로를 사용하지 않는다.

## 실행 순서

backend 작업 위치에서:

    uv run --with 'botocore[crt]' python -m evals.wiki_live <private-bundle> <approval.json> --phase canary --profile <aws-profile>
    uv run --with 'botocore[crt]' python -m evals.wiki_live <private-bundle> <approval.json> --phase remaining --profile <aws-profile>

AWS CLI login 프로필은 Python SDK에 CRT 의존성이 필요할 수 있다.
위 명령은 별도 uv 실행 환경에 이를 제공한다. 인증 준비 실패는 요청 전에
발생할 수 있으므로 실제 원장의 attempts를 확인하며 호출 여부를 추정하지 않는다.
잠금은 승인 디렉터리 공통 .wiki-live.lock으로 여러 승인 파일의 경합도 막는다.

첫 단계는 첫 사례 하나만 호출한다. 출력 형식·인용·사용량·종료 상태를
확인한 뒤 남은 단계로 진행한다. SDK 자동 재시도는 끈다.
출력 부족/오류/불명확한 응답은 추가 호출을 중단하고 기록을 조사한다.
강제 종료 시 started 또는 남은 잠금이 확인되면 임의 삭제/재실행하지 않는다.
성공한 사례는 재호출하지 않는다. 오류를 해결한 뒤의 새 시도는 별도 승인 대상이다.

CountTokens 추정 대신 기존 Luna 서비스 문맥 한도의 보수적 비용 예약을
사용한다. 바이트 제한은 요청 크기 제한이며 토큰 상한 증명이 아니다.
실제 usage의 입력·출력·캐시 항목을 저장하고 추정 요금과 AWS 청구를 구분한다.
비용 정책의 모델·지역·서비스 등급이 바뀌면 호출 전에 재검토한다.

## 출력과 검수

한국어 3줄 요약과 정의·작동 원리·활용 예시·주의사항을 가진 explanation,
숫자 source_ids를 검사한다. URL은 모델이 생성하지 않고 서버측 근거에서
해결한다. 기계적 검사는 사실성·읽기 쉬움의 판정이 아니다.

wiki_live_review.templates/aggregate는 실제 run·approval·output 해시에
검수 양식을 묶는다. AI 검수 초안과 사용자 승인 결과는 별도다.
human_approved가 false이면 정식 결과는 pending을 유지한다.
새 출력이나 다른 실행에 예전 검수 결과를 재사용하면 거부한다.
6개 개발 사례 결과로 봉인된 골든 통과나 제품 정확도를 주장하지 않는다.

실제 출력·원장·사용량·검수 기록은 비공개 경로에 보관한다.
공개 PR에는 합성 테스트와 공개 가능한 검증 요약만 포함한다.

## Current contract: v8 abstention (quality unverified)

`wiki-live-v8-abstention` adds one exact, claim-free insufficient-evidence response
to the system prompt. With nonempty but unrelated sources, the model can return
the `INSUFFICIENT_EVIDENCE` JSON in `wiki_live.py` with no citations. JSON key order
and serialization whitespace may differ; the parsed values must match exactly.
Arbitrary uncited prose, including a technical claim appended to that response,
still fails validation. A partial-evidence answer must keep its supported content
and citations; this exception is only for wholly unsupported explanations.

The runner records `response_kind=insufficient_evidence` and mechanical `status=ok`,
retains the attempt, usage and scheduled slot, and can continue to the remaining
approved slots. It does not infer that the sources really are unrelated. Human
review must check whether abstention was justified, including unnecessary refusal
when useful evidence exists. Existing six-case answer scoring is unchanged: no
review remains pending, and a refusal does not satisfy required concepts or
conditions. Do not count format acceptance as teaching-quality success or remove
abstentions from the denominator. The independent probes still require reviewed
inputs and a separately agreed semantic evaluation contract before live execution.

Empty sources remain blocked by live preflight. This change does not implement a
production fallback or alter the sealed baseline. The examples, output schema and
model settings stay fixed, but the system prompt and runner version change; old
approvals cannot execute v8. Preserve old records. v6/v7 evidence cannot establish
v8 quality, and the v7-only comparison protocol below is historical. Freeze and
authorize a new version-specific execution/comparison plan before any paid call.
Offline regression verifies this contract, not model adherence or quality.

## Grounding prompt v6 (historical)

`wiki-live-v6-grounding` sends one independent source/output demonstration
(stack) before the actual final user payload. The
demonstrations teach definition, mechanism, a concrete situation/problem/application,
and specific cautions. They are not answers from the development or sealed datasets.
Source IDs are scoped to each input; output links resolve only against the current
case. The system prompt and demonstrations are both covered by `prompt_hash`, and
the complete request is covered by `requests_hash` and the existing byte limit.

Source references: [Python stacks](https://docs.python.org/3/tutorial/datastructures.html#using-lists-as-stacks)

Scenario details are authored hypothetical examples, not measured product behavior.

Old approvals cannot execute the changed prompt. Keep old ledgers and reviews with
their original code version; create new approval records only after new execution
authorization. No paid run is implied by this change. Missing facts in current
case evidence still need a separate reviewed revision; demonstrations cannot fix
that gap. Offline tests verify plumbing, not teaching quality or factual accuracy.

The prompt permits explicitly hypothetical applications of supplied concepts, but
not invented technical facts or policies. It requests a final JSON/section check.
This is a prompt instruction, not a guarantee of valid provider output. Validation
still rejects malformed responses; failed calls are not automatically repaired or retried.

Human example review checks actor/context, concrete data/task, problem and
application to that same data/task. These are semantic checks, not exact answer
matching or keyword presence. A mechanically valid output can still fail this review.

## Offline CI regression gate

`Wiki eval offline regression` runs public synthetic fixtures on pull requests,
without provider credentials, private outputs or sealed cases. It tests malformed
JSON, missing/empty sections, unknown citations, summary count, request/approval
boundaries and paired style diagnostics. `style_warnings` records literal review
labels and narrowly detected unintroduced numeric disclaimers for human review;
these heuristics can miss paraphrases and are not semantic pass/fail judgments.
Abstract but structurally valid prose is deliberately tested as format-valid,
not quality-approved. CI green means validators still work; it does not establish
that the current prompt generates good answers. Live repetition and human review
remain separate release evidence. Required-check configuration is a separate
repository setting, not automatically established by adding this workflow.

## Grounding and output contract

The single stack demonstration sources contain technical facts, not an editor
scenario. The output composes a hypothetical editor scene from those facts.
Brief general definitions of jargon are allowed, but must not introduce new
mechanisms, policies or performance claims. Human reviewers label these as glossary
paraphrases and check their correctness separately; they are not falsely attributed
to a source that does not define them. Incorrect glosses still count as factual errors.

No-source policy applies only to this wiki experiment: the offline router returns
its existing limited notice without a model call; the live planner refuses empty
sources before invocation. The prompt also describes a four-section no-evidence
fallback for direct prompt testing, but the live runner never submits that branch.
This does not change the sealed baseline's context-only expected behavior. A
production four-section fixed response is not implemented by this evaluation PR.

Luna Converse supports JSON Schema per the [AWS model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-luna.html).
Requests now set outputConfig.textFormat and additionalModelRequestFields.text.format.strict.
The local SDK validates request shape without network. Provider acceptance remains
unverified until a separately approved call. Server JSON parsing, exact keys,
three summaries, section checks and citation allowlists remain mandatory. No
automatic repair/retry is introduced; schema compliance does not prove truth.

## Pre-run development protocol (v6; no results yet)

Freeze prompt, examples, input/source revisions, schema, model settings and this
protocol before any output is inspected. WDEV six cases x three independent runs
= 18 scheduled model responses. Existing runner supports only six slots: repeat
runs require three distinct approvals/ledgers; no implicit repeat authorization.
Report actual attempts, scheduled slots, unexecuted slots and error counts. A
halt leaves the experiment incomplete, never passes by shrinking the denominator.
For this small calibration require 18/18 valid JSON/sections/citations and no
critical unsupported claim. This is a development gate, not a 95% quality claim.

Human example review records actor, concrete data/task, problem, application
(each O/X), and whether the technical application is supported. Exact wording is
irrelevant. For evidence too weak to support an application, mark the scene N/A
and require a precise insufficiency explanation without invented mechanics.
Report scene success only over eligible outputs, with N/A count separate. Require
all eligible scenes to meet all four checks. Definition/condition preservation and
citation entailment remain separate checks. A number existing in the allowlist
alone is insufficient evidence of a supported claim.

Additional independent development probes (not sealed cases):
- empty sources + informative context: live call blocked, no concept generation;
- definition-only source + a different context: preserve definition, acknowledge
  missing methods, no invented implementation-specific scene;
- two sources with definition and conditions split across IDs: each technical claim
  must cite its supporting source, not simply cite ID 1 throughout;
- terminology without a definition: short correct glossary paraphrase permitted,
  extra algorithm/policy/guarantee forbidden;
- unrelated source: explain the lack of relevant evidence; no fabricated scene.
These probes require their own reviewed inputs before live execution and are not
included in the 18-response denominator. Unit fixtures exercise routing/request
boundaries only, not semantic model performance. Add WDEV analogues when improving
the prompt; never tune against inspected sealed-final failures or overwrite that set.

## Consolidated review: v7 experiment boundary

v7 changes only the system prompt (and its version identity). Keep v6 input sources,
context, demonstrations, schema and inference settings fixed. In particular retain
the dirty editorial note as a diagnostic input for this comparison. Cleaning sources
is a later separately versioned experiment; preserve dirty-source probes. v6 has only
one six-case round, so do not claim reduced failure probability from a single v7 run.
Either authorize the remaining baseline repetitions before comparison, or explicitly
name v7 a new baseline. No calls are authorized by this document.

Review the case-specific required_concepts and required_conditions from the private
development bundle for every output, whether or not every source is cited. Do not
send that grading checklist or expected answer to the model. Check all technical
claims, including uncited claims and jargon glosses. Preserve modality: a requirement
to check an implementation is not proof implementations differ. Citation entailment
is separate from numeric source validation. Do not remove technical conditions when
separating editorial notes. Source cleaning must not strengthen source assertions.

Report clarity failures separately without retroactively changing the existing
4/O scoring behavior. New 90% thresholds and automatic judge substitution are NOT
accepted defaults. Proposed context-only adapter track remains a decision item:
wrapping context must preserve erroneous-source/qualified expectations and cannot
be labelled RAG validation. Empty-source live preflight stays fail-closed; a
four-section server fallback remains unimplemented.

Routing evaluation also includes representative page, alias, missing/unpublished
page and access-control paths, with no generation call on a permitted page match.
Current routing tests are mocks, not production integration evidence. RAG implementation
is deferred; future identity must distinguish disabled/not-applicable from an actual
retrieval configuration and corpus revision. Do not fill unknown revisions with guesses.

Semantic review should be performed independently of prompt authorship, preferably
including a non-CS reader. Record reviewer identity and missing review as pending.
Do not treat keyword warnings as semantic failures or sampling as full-set approval.

External review handoff has three stages:
1. Blockers and decisions, ordered by severity; separate later improvements.
2. Evaluation contract: denominators, repeats, missing/N/A handling, trust boundary.
3. Implementation plan with verified code references and completion evidence.
Attach workflow, live runner, parser, scorer, approved policy and schema/manifest
structure. Never provide or request sealed-final questions or evidence text for
prompt review. API retry policy remains disabled; any future policy must record
first failures and every attempt without shrinking the denominator. Provider,
endpoint/region, model profile and optional guardrail configuration belong in the
future identity; unused guardrails should be explicit, not invented.
