"""가림 함수(hidden_marks)의 다시 묻기 규칙 표 시험 (MEG-236, 2026-11-18 결정). 네트워크·모델 호출 없이 돈다.

결정: 다시 묻기 턴은 가림 연쇄에서 빠진다. 첫 가림 턴 X를 대상으로 한 다시 묻기 턴과 그 뒤 턴은 각자의 출처로 판정한다.
X는 계속 가리고, X를 대상으로 한 다시 묻기가 완료되면 X의 retry_allowed는 false다(한 번만). X와 다시 묻기 턴 사이 턴은 가린다.
"""

import httpx
import pytest

from app.agent_access import Hidden, hidden_marks, source_checker
from app.supabase import SupabaseClient

VISIBLE = {"source_kind": "note", "source_id": "5"}
REVOKED = {"source_kind": "note", "source_id": "6"}
CHECKER = source_checker({5: {"is_published": True}, 6: {"is_published": False}})

FIRST = Hidden("source_revoked", retry_allowed=True)
LATER = Hidden("source_revoked", retry_allowed=False)


def turn(turn_id, seq, *, revoked=False, retry_of=None, status="completed"):
    return {"id": turn_id, "seq": seq, "status": status, "retry_of_turn_id": retry_of,
            "ai_turn_sources": [REVOKED if revoked else VISIBLE]}


CASES = {
    "no_hidden_turns": (
        [turn("a", 1), turn("b", 2), turn("c", 3)],
        {"a": None, "b": None, "c": None},
    ),
    "no_retry_hides_x_and_every_later_turn": (
        [turn("a", 1), turn("x", 2, revoked=True), turn("b", 3), turn("c", 4)],
        {"a": None, "x": FIRST, "b": LATER, "c": LATER},
    ),
    "retry_ends_the_cascade_and_uses_up_the_retry": (
        [turn("a", 1), turn("x", 2, revoked=True), turn("m1", 3), turn("m2", 4),
         turn("r", 5, retry_of="x"), turn("l1", 6), turn("l2", 7)],
        {"a": None, "x": LATER, "m1": LATER, "m2": LATER, "r": None, "l1": None, "l2": None},
    ),
    "retry_citing_a_revoked_source_starts_a_new_cascade": (
        [turn("x", 1, revoked=True), turn("r", 2, revoked=True, retry_of="x"), turn("l1", 3)],
        {"x": LATER, "r": FIRST, "l1": LATER},
    ),
    "second_revoked_turn_after_the_retry_is_hidden_again": (
        [turn("x", 1, revoked=True), turn("m", 2), turn("r", 3, retry_of="x"), turn("l1", 4),
         turn("y", 5, revoked=True), turn("l2", 6)],
        {"x": LATER, "m": LATER, "r": None, "l1": None, "y": FIRST, "l2": LATER},
    ),
    "the_second_cascade_can_also_be_retried_once": (
        [turn("x", 1, revoked=True), turn("r", 2, retry_of="x"), turn("y", 3, revoked=True),
         turn("r2", 4, retry_of="y"), turn("l", 5)],
        {"x": LATER, "r": None, "y": LATER, "r2": None, "l": None},
    ),
    "a_retry_of_a_turn_that_is_not_the_cascade_start_stays_hidden": (
        # X 앞의 w가 나중에 회수되면 연쇄는 w에서 시작한다. x를 대상으로 한 다시 묻기는 연쇄를 끝내지 않는다.
        [turn("w", 1, revoked=True), turn("x", 2), turn("r", 3, retry_of="x"), turn("l", 4)],
        {"w": FIRST, "x": LATER, "r": LATER, "l": LATER},
    ),
    "a_retry_whose_target_is_visible_again_is_an_ordinary_turn": (
        [turn("x", 1), turn("r", 2, retry_of="x"), turn("l", 3)],
        {"x": None, "r": None, "l": None},
    ),
    "a_failed_retry_ends_the_cascade_but_keeps_the_retry": (
        [turn("x", 1, revoked=True), turn("m", 2), turn("r", 3, retry_of="x", status="failed"), turn("l", 4)],
        {"x": FIRST, "m": LATER, "r": None, "l": None},
    ),
    "a_completed_retry_after_a_failed_one_uses_up_the_retry": (
        [turn("x", 1, revoked=True), turn("r1", 2, retry_of="x", status="failed"),
         turn("r2", 3, retry_of="x"), turn("l", 4)],
        {"x": LATER, "r1": None, "r2": None, "l": None},
    ),
}


@pytest.mark.parametrize("turns, expected", CASES.values(), ids=CASES.keys())
def test_hidden_marks_retry_rules(turns, expected):
    assert hidden_marks(turns, CHECKER) == expected
    # 입력 순서와 상관없이 seq 순서로 판정한다.
    assert hidden_marks(list(reversed(turns)), CHECKER) == expected


@pytest.mark.parametrize("status", ["cancelled", "running"])
def test_an_unfinished_retry_ends_the_cascade_without_using_up_the_retry(status):
    turns = [turn("x", 1, revoked=True), turn("r", 2, retry_of="x", status=status)]
    # 진행 중 다시 묻기와 겹치는 새 다시 묻기는 E29가 turn_in_progress로 막는다.
    assert hidden_marks(turns, CHECKER) == {"x": FIRST, "r": None}


def test_rows_without_retry_of_turn_id_keep_the_old_cascade():
    turns = [{"id": "x", "seq": 1, "status": "completed", "ai_turn_sources": [REVOKED]},
             {"id": "b", "seq": 2, "status": "completed", "ai_turn_sources": []}]
    assert hidden_marks(turns, CHECKER) == {"x": FIRST, "b": LATER}


def test_listing_turns_selects_retry_of_turn_id():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    client = SupabaseClient("https://project.supabase.co/", "sb_secret_test",
                            httpx.Client(transport=httpx.MockTransport(handler)))
    client.list_agent_turns("00000000-0000-4000-8000-00000000000a", "11111111-1111-4111-8111-111111111111")
    assert "retry_of_turn_id" in dict(seen[0].url.params)["select"].split(",")
