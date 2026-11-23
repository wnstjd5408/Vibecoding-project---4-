"""CS Agent 'AI에게 질문' 로컬 e2e 보조 도구 (MEG-240, API spec v0.2 9절 검증 항목).

`scripts.local_backend`로 띄운 로컬 Supabase(실제 DB·Auth)에 붙는 FastAPI를 시험용으로 실행하고, 시험이 쓸 합성 노트를 넣는다.
원격 대상은 받지 않는다. 퀴즈 도구(`scripts.local_quiz_e2e`, MEG-207)와 같은 방식이다.

- seed: member-a의 CS Agent 대화·agent 원장 행·속도 제한 기록을 지우고, 합성 노트 둘을 공개로 다시 만든다.
  이 도구가 만든 노트(NOTE_OPEN, NOTE_CITED)와 member-a의 행만 건드린다.
- serve: 앱을 uvicorn으로 실행한다. 실제 Bedrock은 부르지 않는다. AI 클라이언트만 가짜(FakeModel)로 바꾼다.
  검색(공개 노트 키워드 검색)·원장·턴 저장·가림은 실제 코드와 로컬 DB를 그대로 쓴다.
  가짜 모델의 호출 기록은 `GET /__e2e/model-calls`로 읽는다(이 프로세스에만 붙는 시험용 경로, /api 밖이다).

backend 폴더에서 `uv run python -m scripts.local_agent_e2e --help`로 쓴다.
"""

import argparse
import json
import os
import sys
import threading
import time
from typing import Annotated

from scripts import local_backend as lb

MEMBER_A = lb.USER_IDS["member-a"]
# 이 도구가 만드는 노트 ID. 고정 합성 자료(132001)·퀴즈 도구(132100~132102)와 겹치지 않는다.
NOTE_OPEN = 132110  # 시험이 열고 문장을 골라 질문하는 노트. 끝까지 공개다.
NOTE_CITED = 132111  # 답변이 인용하는 노트. 시나리오 3에서 운영자가 비공개로 바꾼다.

# 질문에 이 낱말이 있으면 가짜 모델이 답하기 전에 기다린다. 그 사이에 시험이 스트림을 끊는다(시나리오 1).
SLOW_MARKER = "천천히"
SLOW_SECONDS = 3.0
# 가짜 답변의 추천 질문. 인용 노트의 낱말(합성체이닝)이 들어 있어 다시 보내도 근거를 찾는다.
SUGGESTIONS = ("합성체이닝을 예시로 보여 줘", "합성체이닝의 단점은 뭐야?")

OPEN_BODY = """# 합성 에이전트 노트

이 문장은 시험이 골라서 질문하는 합성 선택 문장이며 실제 학습 자료가 아닙니다.

## 합성 배경

합성 해시 표는 키를 버킷에 나눠 담는 자료 구조라는 합성 설명입니다.
"""

CITED_BODY = """# 합성 출처 노트

## 합성체이닝

합성체이닝은 같은 버킷에 들어온 키를 목록으로 이어 두는 합성 설명입니다. 시험 전용 문장입니다.
"""


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def seed_sql() -> str:
    return f"""
begin;
delete from public.ai_conversations where user_id = '{MEMBER_A}';
delete from public.ai_usage_ledger where user_id = '{MEMBER_A}' and kind = 'agent';
delete from public.rate_limit_counters;
delete from public.notes where id in ({NOTE_OPEN}, {NOTE_CITED});
insert into public.notes (id, title, body_markdown, is_published) overriding system value values
  ({NOTE_OPEN}, '합성 에이전트 노트', {_sql_text(OPEN_BODY)}, true),
  ({NOTE_CITED}, '합성 출처 노트', {_sql_text(CITED_BODY)}, true);
commit;
"""


def seed() -> None:
    lb.docker_local()
    lb.config()
    lb.run(["docker", "exec", "-i", f"supabase_db_{lb.project_id()}", "psql", "-U", "postgres", "-d", "postgres",
            "-v", "ON_ERROR_STOP=1", "-q"], input_text=seed_sql())
    print(f"Seeded CS Agent notes {NOTE_OPEN}, {NOTE_CITED} and cleared member-a agent rows.")


class FakeModel:
    """Bedrock Converse를 흉내 낸다. 네트워크를 쓰지 않는다.

    CS Agent 프롬프트(근거 문단 블록이 있다)에는 [1]을 인용한 answered JSON을 준다. 다른 호출(퀴즈 자료 explain 등)에는
    짧은 글을 준다. 호출은 들어오는 즉시 기록한다(답하기 전에 기다려도 호출 1회로 센다).
    """

    def __init__(self):
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def converse(self, **kwargs):
        prompt = "".join(
            block.get("text", "") for message in kwargs.get("messages", []) for block in message.get("content", [])
        )
        kind = "agent" if "근거 문단" in prompt else "other"
        with self._lock:
            number = len(self.calls) + 1
            self.calls.append({"n": number, "kind": kind, "at": time.time()})
        if kind == "agent" and SLOW_MARKER in prompt:
            time.sleep(SLOW_SECONDS)
        if kind == "agent":
            text = json.dumps({
                "state": "answered",
                "sections": [{"heading": "합성 답변", "body": f"합성 가짜 답변 {number}입니다. 근거 문단을 인용합니다 [1]."}],
                "suggestions": list(SUGGESTIONS),
            }, ensure_ascii=False)
        else:
            text = f"합성 가짜 설명 {number}입니다."
        return {
            "stopReason": "end_turn",
            "output": {"message": {"content": [{"text": text}]}},
            "usage": {"inputTokens": 200, "outputTokens": 60},
        }


def build_app(origin: str):
    lb.load_environment()
    os.environ["ALLOWED_ORIGINS"] = origin
    # 노출 중단·위키 플래그는 끈다(노트 임시 검색 경로를 시험한다). 위키 출처 시나리오는 범위 밖이다.
    for name in ("CS_AGENT_DISABLED", "CS_AGENT_WIKI_ENABLED"):
        os.environ.pop(name, None)
    # 실제 호출이 없어도 설정 검사는 지난다. 값은 비밀이 아닌 자리표시자다.
    os.environ.update({
        "AI_AUTH_MODE": "api_key", "AWS_BEARER_TOKEN_BEDROCK": "local-e2e-placeholder",
        "AI_DAILY_BUDGET_USD": "100", "AI_MONTHLY_BUDGET_USD": "1000",
        "AI_INPUT_USD_PER_MTOK": "1", "AI_OUTPUT_USD_PER_MTOK": "1",
    })
    from fastapi import Depends

    from app.ai_explain import AiRuntime, get_ai_runtime
    from app.ai_ledger import SupabaseLedgerStore
    from app.main import app
    from app.supabase import SupabaseClient, get_supabase

    fake = FakeModel()

    def runtime(supabase: Annotated[SupabaseClient, Depends(get_supabase)]) -> AiRuntime:
        return AiRuntime(store=SupabaseLedgerStore(supabase), client_factory=lambda *_a, **_k: fake, sleep=lambda _s: None)

    app.dependency_overrides[get_ai_runtime] = runtime

    def model_calls() -> dict:
        with fake._lock:
            calls = list(fake.calls)
        return {"calls": calls, "agent": sum(call["kind"] == "agent" for call in calls)}

    app.add_api_route("/__e2e/model-calls", model_calls, methods=["GET"], include_in_schema=False)
    return app


def serve(port: int, origin: str) -> None:
    import uvicorn

    uvicorn.run(build_app(origin), host="127.0.0.1", port=port, log_level="warning")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    run_parser = sub.add_parser("serve")
    run_parser.add_argument("--port", type=int, required=True)
    run_parser.add_argument("--origin", required=True, help="허용할 브라우저 출처. http://127.0.0.1:<port>만 받는다")
    args = parser.parse_args()
    try:
        if args.command == "seed":
            seed()
        else:
            lb.local_url(args.origin)
            serve(args.port, args.origin)
    except lb.SetupError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
