"""퀴즈 화면 로컬 e2e 보조 도구 (MEG-207).

`scripts.local_backend`로 띄운 로컬 Supabase(실제 DB·Auth)에 붙는 FastAPI를 시험용으로 실행하고,
시험이 쓸 합성 퀴즈 세트를 넣는다. 원격 대상은 받지 않는다.

- seed: member-a의 오늘(KST) 퀴즈 세트를 합성 문항 둘로 다시 만든다. 이 도구가 만든 행만 지운다.
- serve: 앱을 uvicorn으로 실행한다. 실제 Bedrock은 부르지 않는다. AI 클라이언트만 가짜로 바꾸고,
  퀴즈 시각을 오늘 12:00 KST로 고정해 08:30 이전에도 시험이 돈다. 원장·DB는 실제 로컬 DB를 쓴다.

backend 폴더에서 `uv run python -m scripts.local_quiz_e2e --help`로 쓴다.
"""

import argparse
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from itertools import count

from scripts import local_backend as lb

KST = timezone(timedelta(hours=9))
MEMBER_A = lb.USER_IDS["member-a"]
# local_fixture.sql이 만든 합성 용어. 오늘 세트의 문항이 가리킨다.
TERMS = (132001, 132002)
# 이 도구가 만드는 세트·문항 ID 범위. 고정 합성 자료(132001~)와 겹치지 않는다.
SET_ID = 132100
ITEM_IDS = (132101, 132102)


def seed_sql(today: date) -> str:
    source = today - timedelta(days=1)
    return f"""
delete from public.quiz_sets where id = {SET_ID};
delete from public.quiz_sets where user_id = '{MEMBER_A}' and quiz_date = '{today}';
delete from public.rate_limit_counters;
insert into public.quiz_sets (id, user_id, quiz_date, source_date, status)
  overriding system value values ({SET_ID}, '{MEMBER_A}', '{today}', '{source}', 'ready');
insert into public.quiz_set_terms (set_id, term_id, reason) values
  ({SET_ID}, {TERMS[0]}, 'favorited'), ({SET_ID}, {TERMS[1]}, 'viewed');
insert into public.quiz_items (id, set_id, term_id, question, answer, explanation, difficulty)
  overriding system value values
  ({ITEM_IDS[0]}, {SET_ID}, {TERMS[0]}, '합성 질문: 스택에서 가장 먼저 꺼내는 값은?', '마지막에 넣은 값', '합성 해설: 후입선출 구조입니다.', '하'),
  ({ITEM_IDS[1]}, {SET_ID}, {TERMS[1]}, '합성 질문: 큐에서 가장 먼저 꺼내는 값은?', '처음에 넣은 값', '합성 해설: 선입선출 구조입니다.', '중');
"""


def seed() -> None:
    today = datetime.now(KST).date()
    lb.docker_local()
    lb.run(["docker", "exec", "-i", f"supabase_db_{lb.project_id()}", "psql", "-U", "postgres", "-d", "postgres",
            "-v", "ON_ERROR_STOP=1", "-q"], input_text=seed_sql(today))
    print(f"Seeded quiz set {SET_ID} for member-a ({today}).")


class FakeBedrock:
    """Bedrock Converse를 흉내 낸다. 네트워크를 쓰지 않고, 호출마다 번호가 붙은 합성 꼬리 질문을 준다."""

    def __init__(self, numbers):
        self.numbers = numbers

    def converse(self, **_kwargs):
        n = next(self.numbers)
        return {
            "stopReason": "end_turn",
            "output": {"message": {"content": [{"text": f"합성 꼬리 질문 {n}: 이 개념이 실제로 쓰이는 사례를 하나 들어 보세요."}]}},
            "usage": {"inputTokens": 120, "outputTokens": 30},
        }


def build_app(origin: str):
    lb.load_environment()
    os.environ["ALLOWED_ORIGINS"] = origin
    # 실제 호출이 없어도 설정 검사는 지난다. 값은 비밀이 아닌 자리표시자다.
    os.environ.update({
        "AI_AUTH_MODE": "api_key", "AWS_BEARER_TOKEN_BEDROCK": "local-e2e-placeholder",
        "AI_DAILY_BUDGET_USD": "100", "AI_MONTHLY_BUDGET_USD": "1000",
        "AI_INPUT_USD_PER_MTOK": "1", "AI_OUTPUT_USD_PER_MTOK": "1",
    })
    from fastapi import Depends

    from app import quiz
    from app.ai_explain import AiRuntime, get_ai_runtime
    from app.ai_ledger import SupabaseLedgerStore
    from app.main import app
    from app.supabase import SupabaseClient, get_supabase

    numbers = count(1)
    fake = FakeBedrock(numbers)

    def runtime(supabase: SupabaseClient = Depends(get_supabase)) -> AiRuntime:
        return AiRuntime(store=SupabaseLedgerStore(supabase), client_factory=lambda *_a, **_k: fake, sleep=lambda _s: None)

    app.dependency_overrides[get_ai_runtime] = runtime
    quiz.kst_now = lambda: datetime.combine(datetime.now(KST).date(), time(12, 0), tzinfo=KST)
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
