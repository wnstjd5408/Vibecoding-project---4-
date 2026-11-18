"""노트 용어 질문의 퀴즈 자료 (MEG-243, API spec v0.2 4절 E29 '퀴즈 자료' 항목·6절·9절, MEG-230 결정 E + C).

화면의 'AI 설명' 진입점이 'AI에게 질문'으로 바뀌어도 다음 날 퀴즈의 후보와 자료가 생기게 한다. 노트에서 고른 용어로 질문하면
E09와 같은 저장 경로로 공유 설명(`ai_explanations`, `terms`의 source='ai' 행)과 열람 기록(`term_views`)을 만든다.

규칙(사용자 결정 2026-11-18, MEG-243):
- 턴의 마지막 이벤트(result·error)를 보낸 뒤 같은 요청·같은 스레드에서 돈다. explain 예약이 agent 정산 뒤에 오므로 턴 결과가
  바뀌지 않는다. 원장의 하루 합계와 사용자 몫은 kind를 가리지 않고 더하기 때문이다(ai_check_limit).
- 대상은 origin note 대화에서 이번 턴의 선택 문맥이 정확히 하나이고, 그 선택의 노트 개정이 지금과 같고, E09 규칙
  (pick_term_and_sentence, 80자 이하)으로 용어 하나가 될 때다. 첫 턴에 한정하지 않는다.
- 사전 용어나 유효한 AI 설명이 있으면 AI를 부르지 않고 열람만 기록한다(노트가 비공개여도 같다).
- 비공개 노트의 사전 밖 용어는 AI를 부르지 않는다(저장하지 않을 결과에 비용을 쓰지 않는다, spec v0.2 5.7).
- 입력은 E09와 같이 용어와 서버가 지금 본문에서 자른 노트 문장뿐이다. 질문·답변·선택 원문(text_snapshot)은 넣지 않는다.
- 결과는 턴 행·이벤트·응답에 넣지 않는다. 이 처리의 실패와 한도 초과는 모두 여기서 삼킨다.
- 로그에는 턴 id·결과 종류·오류 이름만 남긴다. 용어·문장·질문은 남기지 않는다.
"""

import logging
import time
from typing import Any

from app.ai_explain import (
    MAX_TERM_CHARS,
    AiRuntime,
    build_prompt,
    known_term,
    pick_term_and_sentence,
    record_view,
    store_explanation,
)
from app.ai_ledger import (
    KIND_EXPLAIN,
    AiLimitReached,
    AiSettlementFailed,
    LedgerKeyExists,
    agent_explain_request_key,
    run_ai_call,
)
from app.bedrock import AiCallError, AiConfigError
from app.supabase import SupabaseClient

logger = logging.getLogger("app.agent")

# 요청을 받은 뒤 이 시간이 지났으면 AI를 부르지 않고 열람만 기록한다. explain 최악(약 86초, 기술 검토 Q15와 같은 호출 설정)을
# 더해도 함수 최대 실행 시간(300초) 안에 들게 한다. 계산값이고 실측이 아니다(MEG-243 설계안).
AI_CUTOFF_SECONDS = 180.0


def target_span(job: Any) -> tuple[int, int, int, int] | None:
    """퀴즈 자료를 볼 선택 (note_id, 저장한 개정, 시작, 끝). 본문을 읽지 않고 거를 수 있는 조건만 본다."""
    if job.access.conversation.get("origin") != "note":
        return None
    spans = job.checked.selection_spans
    if len(spans) != 1:
        # 선택이 없거나 여럿이면 어느 용어를 물었는지 알 수 없다.
        return None
    span = spans[0]
    _, _, start, end = span
    if end <= start or end - start > MAX_TERM_CHARS:
        return None
    return span


def make_quiz_material(job: Any, supabase: SupabaseClient, runtime: AiRuntime, started_at: float) -> str:
    """퀴즈 자료를 만들고 결과 종류를 돌려준다. 어떤 예외도 밖으로 내지 않는다(턴 결과를 바꾸지 않는다)."""
    try:
        outcome = _make(job, supabase, runtime, started_at)
    except Exception as error:
        outcome = "error"
        logger.warning("stage=quiz_material turn_id=%s error=%s", job.turn_id, type(error).__name__)
    logger.info("stage=quiz_material turn_id=%s outcome=%s", job.turn_id, outcome)
    return outcome


def _make(job: Any, supabase: SupabaseClient, runtime: AiRuntime, started_at: float) -> str:
    span = target_span(job)
    if span is None:
        return "not_term"
    note_id, revision, start, end = span
    user = job.user
    # 노트 읽기 권한은 E09와 같다. 그사이 볼 수 없게 됐으면 자료를 만들지 않는다.
    note = supabase.get_note_for_explain(note_id, include_unpublished=user.is_operator)
    if note is None or note["revision"] != revision:
        # 개정이 바뀌면 저장한 위치가 엉뚱한 글자를 가리킬 수 있다(E09의 stale_revision과 같은 기준).
        return "not_term"
    text = note["body_markdown"]
    if end > len(text):
        return "not_term"
    picked = pick_term_and_sentence(text, start, end)
    if picked is None:
        return "not_term"

    row = supabase.find_term_for_explain(picked.key, user.user_id)
    if known_term(row):
        record_view(supabase, user.user_id, row["id"])
        return "known"
    if not note["is_published"]:
        return "private"
    if time.monotonic() - started_at > AI_CUTOFF_SECONDS:
        return "late"

    try:
        result = run_ai_call(
            runtime.store,
            job.settings,
            job.budget,
            user_id=user.user_id,
            kind=KIND_EXPLAIN,
            request_key=agent_explain_request_key(user.user_id, job.idempotency_key),
            prompt=build_prompt(picked),
            oidc_token=job.oidc_token,
            client_factory=runtime.client_factory,
            sleep=runtime.sleep,
        )
    except AiLimitReached:
        return "limit"
    except LedgerKeyExists:
        # 턴 선점 때문에 정상 흐름에서는 생기지 않는다. 같은 턴의 키로 이미 예약했으니 다시 부르지 않는다.
        return "exists"
    except (AiCallError, AiSettlementFailed, AiConfigError) as error:
        logger.warning("stage=quiz_material turn_id=%s ai_error=%s", job.turn_id, type(error).__name__)
        return "ai_error"

    stored, row = store_explanation(
        supabase,
        user_id=user.user_id,
        note_id=note_id,
        note_revision=revision,
        picked=picked,
        text=result.text.strip(),
        model=job.settings.model_id,
    )
    if stored["outcome"] == "one_off" or not known_term(row):
        # 저장하지 못했거나(노트가 바뀜·비공개 전환) 다시 읽기 전에 무효화됐다. E09처럼 열람을 남기지 않는다.
        return "one_off"
    record_view(supabase, user.user_id, row["id"])
    return "stored"
