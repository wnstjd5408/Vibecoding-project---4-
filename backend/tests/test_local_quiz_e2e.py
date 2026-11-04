"""로컬 퀴즈 e2e 보조 도구(MEG-207)의 단위 시험. DB·네트워크를 쓰지 않는다."""

from datetime import date
from itertools import count

import pytest

from app.bedrock import BedrockSettings, converse_text
from app.quiz_followups import parse_question
from scripts import local_quiz_e2e as e2e


def test_seed_sql_touches_only_member_a_and_tool_ids():
    sql = e2e.seed_sql(date(2026, 11, 4))
    assert e2e.MEMBER_A in sql
    assert "'2026-11-04'" in sql and "'2026-11-03'" in sql
    # 고정 합성 자료의 세트·문항 ID(132001, 132002)를 지우거나 덮어쓰지 않는다.
    assert f"id = {e2e.SET_ID}" in sql
    assert all(item not in (132001, 132002) for item in e2e.ITEM_IDS)
    assert e2e.SET_ID not in (132001, 132002)
    # 다른 사용자의 퀴즈를 지우는 조건이 없다.
    assert "delete from public.quiz_sets where user_id = '" + e2e.MEMBER_A + "'" in sql
    assert sql.count("delete from public.quiz_sets") == 2


def test_fake_bedrock_numbers_questions_and_passes_the_real_parser():
    fake = e2e.FakeBedrock(count(1))
    settings = BedrockSettings()
    first = converse_text(fake, settings, "p", max_tokens=100)
    second = converse_text(fake, settings, "p", max_tokens=100)
    assert parse_question(first.text).startswith("합성 꼬리 질문 1")
    assert parse_question(second.text).startswith("합성 꼬리 질문 2")
    assert (first.input_tokens, first.output_tokens) == (120, 30)


def test_serve_rejects_non_loopback_origin():
    with pytest.raises(e2e.lb.SetupError):
        e2e.lb.local_url("https://example.com")
