"""E12 퀴즈 답 제출·E14 꼬리 질문 답 저장 (MEG-92). 가짜 Supabase로 네트워크 없이 돈다. 데이터는 모두 합성이다.

실제 래퍼의 HTTP 모양은 test_supabase_quiz_answers_client.py가 고정한다. 여기서는 권한·검사 순서·응답 모양·멱등성(같은 답
200, 다른 답 409)·동시 요청·사용자 분리·장애 응답을 보고, AC-3은 E12 뒤에 E11을 다시 불러 같은 세트가 복원되는지로 본다.
가짜는 실제 래퍼와 같은 규칙(먼저 저장된 답을 덮어쓰지 않고, 저장된 답을 돌려준다)을 따른다.
"""

from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import quiz, quiz_answers, session
from app.ai_explain import AiRuntime, get_ai_runtime
from app.common import install_common_layer
from app.quiz_answers import ANSWER_LIMIT
from app.rate_limit import WRITE
from app.supabase import SupabaseConfigError, SupabaseUnavailable, get_supabase
from support import cookie, origin
from test_quiz import MEMBER, OPEN, OTHER, TODAY, YESTERDAY, QuizFake

# 문항: 1은 답 없음, 2는 답했고 꼬리 질문 둘(1번 답함·2번 답 없음), 3은 답했고 꼬리 질문 슬롯만 있음(만드는 중),
# 4는 답했고 꼬리 질문 1번이 질문만 있음, 5는 다른 사용자(OTHER)의 문항이다.
NO_ANSWER, TWO_FOLLOWUPS, IN_PROGRESS, ONE_FOLLOWUP, OTHERS = 1, 2, 3, 4, 5


@dataclass
class AnswerFake(QuizFake):
    """QuizFake에 E12·E14의 읽기·쓰기를 더한다. 쓰기 시도를 writes에 남긴다."""

    writes: list = field(default_factory=list)
    # 쓰기 직전에 부른다. 같은 문항에 동시에 들어온 다른 요청이 먼저 저장하는 경합을 흉내 낸다.
    before_write: object = None
    # 쓰기 직전에 문항이 지워지는 경합
    vanish_on_write: bool = False
    config_error: bool = False

    def _item(self, item_id):
        return next((i for i in self.quiz_items if i["id"] == item_id), None)

    def get_quiz_item_for_answer(self, user_id, item_id):
        self._read()
        item = self._item(item_id)
        if item is None:
            return None
        if next(s for s in self.quiz_sets if s["id"] == item["set_id"])["user_id"] != user_id:
            return None
        answer = self.quiz_answers.get(item_id)
        return {
            **{k: item[k] for k in ("id", "difficulty", "answer", "explanation")},
            "quiz_answers": None if answer is None else {"user_answer": answer},
            "quiz_followups": [
                dict(f) for f in sorted((f for f in self.quiz_followups if f["item_id"] == item_id), key=lambda f: f["seq"])
            ],
        }

    def _before_write(self, kind, *args):
        if self.down:
            raise SupabaseUnavailable("down")
        if self.config_error:
            raise SupabaseConfigError("status 401")
        self.writes.append((kind, *args))
        if self.before_write is not None:
            self.before_write()

    def save_quiz_answer(self, item_id, answer):
        self._before_write("answer", item_id, answer)
        if self.vanish_on_write or self._item(item_id) is None:
            return None
        return self.quiz_answers.setdefault(item_id, answer)

    def save_followup_answer(self, item_id, seq, answer):
        self._before_write("followup", item_id, seq, answer)
        slot = next((f for f in self.quiz_followups if f["item_id"] == item_id and f["seq"] == seq), None)
        if self.vanish_on_write or slot is None or not slot["question"]:
            return None
        if slot["user_answer"] is None:
            slot["user_answer"] = answer
        return slot["user_answer"]


@pytest.fixture
def fake(monkeypatch) -> AnswerFake:
    fake = AnswerFake()
    fake.add_user("member-token", MEMBER)
    fake.add_user("other-token", OTHER)
    fake.add_user("inactive-token", "00000000-0000-4000-8000-00000000000c", is_active=False)
    monkeypatch.setattr(session, "now", lambda: OPEN)
    fake.quiz_sets = [
        {"id": 1, "user_id": MEMBER, "quiz_date": TODAY, "source_date": YESTERDAY, "status": "ready", "attempt": 1, "lease": None},
        {"id": 2, "user_id": OTHER, "quiz_date": TODAY, "source_date": YESTERDAY, "status": "ready", "attempt": 1, "lease": None},
    ]
    for item_id, set_id in ((1, 1), (2, 1), (3, 1), (4, 1), (5, 2)):
        fake.quiz_items.append(
            {
                "id": item_id, "set_id": set_id, "term_id": item_id, "question": f"합성 문제 {item_id}",
                "answer": f"합성 정답 {item_id}", "explanation": f"합성 해설 {item_id}", "difficulty": "중",
            }
        )
    fake.quiz_answers = {2: "먼저 낸 답", 3: "먼저 낸 답", 4: "먼저 낸 답", 5: "OTHER의 답"}
    fake.quiz_followups = [
        {"item_id": 2, "seq": 1, "question": "합성 꼬리 질문 1", "user_answer": "꼬리 답 1"},
        {"item_id": 2, "seq": 2, "question": "합성 꼬리 질문 2", "user_answer": None},
        {"item_id": 3, "seq": 1, "question": None, "user_answer": None},
        {"item_id": 4, "seq": 1, "question": "합성 꼬리 질문", "user_answer": None},
        {"item_id": 5, "seq": 1, "question": "OTHER의 꼬리 질문", "user_answer": None},
    ]
    return fake


def build_app(fake: AnswerFake) -> FastAPI:
    app = FastAPI()
    install_common_layer(app)
    app.dependency_overrides[get_supabase] = lambda: fake

    def no_ai():
        raise AssertionError("E11 ready path and E12·E14 must not touch the AI runtime")

    app.dependency_overrides[get_ai_runtime] = lambda: AiRuntime(
        store=None, load_budget=no_ai, load_settings=no_ai, client_factory=no_ai, sleep=lambda _: None
    )
    app.include_router(quiz.router)
    app.include_router(quiz_answers.router)
    return app


@pytest.fixture
def client(fake) -> TestClient:
    return TestClient(build_app(fake))


def headers(token, extra=None):
    return {**origin(), **(cookie(token) if token else {}), **(extra or {})}


def post_answer(client, item_id, body, token="member-token", extra=None):
    return client.post(f"/api/quiz/items/{item_id}/answer", json=body, headers=headers(token, extra))


def put_followup(client, item_id, seq, body, token="member-token", extra=None):
    return client.put(f"/api/quiz/items/{item_id}/followups/{seq}/answer", json=body, headers=headers(token, extra))


def assert_error(response, status, code, detail=None):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    if detail is not None:
        assert error["detail"] == detail


def assert_field(response, name, reason):
    assert_error(response, 422, "validation_failed")
    assert {"name": name, "reason": reason} in [
        {"name": f["name"], "reason": f["reason"]} for f in response.json()["error"]["fields"]
    ]


# --- E12 AC-1: 답하면 정답과 해설이 나온다 ---


def test_answering_saves_the_answer_and_returns_the_correct_answer_and_explanation(client, fake):
    response = post_answer(client, NO_ANSWER, {"answer": "합성 답변"})
    assert response.status_code == 200
    # 3절 예시 6 그대로다. 정오 판정 필드가 없다.
    assert response.json() == {
        "item_id": NO_ANSWER,
        "your_answer": "합성 답변",
        "correct_answer": "합성 정답 1",
        "explanation": "합성 해설 1",
        "difficulty": "중",
        "can_request_followup": True,
        "followups_remaining": 2,
    }
    assert response.headers["cache-control"] == "private, no-store"
    assert fake.quiz_answers[NO_ANSWER] == "합성 답변"
    assert fake.writes == [("answer", NO_ANSWER, "합성 답변")]


def test_the_answer_is_stored_as_written_without_trimming(client, fake):
    response = post_answer(client, NO_ANSWER, {"answer": "  앞뒤 공백이 있는 답  "})
    assert response.status_code == 200
    assert response.json()["your_answer"] == "  앞뒤 공백이 있는 답  "
    assert fake.quiz_answers[NO_ANSWER] == "  앞뒤 공백이 있는 답  "


@pytest.mark.parametrize("length", [1, ANSWER_LIMIT])
def test_answer_lengths_within_the_limit_are_accepted(client, fake, length):
    assert post_answer(client, NO_ANSWER, {"answer": "가" * length}).status_code == 200
    assert fake.quiz_answers[NO_ANSWER] == "가" * length


def test_answering_never_uses_the_ai_or_the_ledger(client, fake):
    # build_app의 AI 런타임은 부르면 실패한다. 응답이 200이면 AI·원장을 건드리지 않았다.
    assert post_answer(client, NO_ANSWER, {"answer": "답"}).status_code == 200
    assert put_followup(client, ONE_FOLLOWUP, 1, {"answer": "꼬리 답"}).status_code == 200
    # 속도 제한 집계(rate_limit_hit) 말고는 SQL 함수를 부르지 않는다. ai_reserve 같은 원장 함수가 없다.
    assert {name for name, _ in fake.rpc_calls} == {"rate_limit_hit"}


def test_followup_state_in_the_e12_response_follows_the_slots(client, fake):
    # 문항 4는 답했고 꼬리 질문 슬롯이 하나다. 질문에 답하지 않아서 새로 받을 수 없고 남은 수는 1이다.
    response = post_answer(client, ONE_FOLLOWUP, {"answer": "먼저 낸 답"})
    assert response.status_code == 200
    assert response.json()["can_request_followup"] is False
    assert response.json()["followups_remaining"] == 1
    # 문항 2는 꼬리 질문 둘을 이미 받았다.
    response = post_answer(client, TWO_FOLLOWUPS, {"answer": "먼저 낸 답"})
    assert response.json()["can_request_followup"] is False
    assert response.json()["followups_remaining"] == 0
    # 슬롯만 있는(만드는 중) 문항은 이미 쓴 번호로 센다.
    response = post_answer(client, IN_PROGRESS, {"answer": "먼저 낸 답"})
    assert response.json()["can_request_followup"] is False
    assert response.json()["followups_remaining"] == 1


# --- E12 AC-2: 다른 답은 409, 남의 문항은 404 ---


def test_the_same_answer_again_is_200_with_the_same_response_and_no_extra_row(client, fake):
    first = post_answer(client, NO_ANSWER, {"answer": "합성 답변"})
    again = post_answer(client, NO_ANSWER, {"answer": "합성 답변"})
    assert again.status_code == 200
    assert again.json() == first.json()
    assert fake.writes == [("answer", NO_ANSWER, "합성 답변")]  # 두 번째는 쓰기를 시도하지 않는다


def test_a_different_answer_is_409_already_answered_and_keeps_the_first_answer(client, fake):
    post_answer(client, NO_ANSWER, {"answer": "합성 답변"})
    response = post_answer(client, NO_ANSWER, {"answer": "다른 답변"})
    assert_error(response, 409, "conflict", "already_answered")
    assert fake.quiz_answers[NO_ANSWER] == "합성 답변"
    assert "다른 답변" not in response.text and "합성 정답" not in response.text


def test_a_different_answer_for_a_question_answered_earlier_is_409(client, fake):
    response = post_answer(client, TWO_FOLLOWUPS, {"answer": "다른 답변"})
    assert_error(response, 409, "conflict", "already_answered")
    assert fake.writes == []
    assert fake.quiz_answers[TWO_FOLLOWUPS] == "먼저 낸 답"


def test_a_concurrent_request_that_saved_a_different_answer_first_makes_this_one_409(client, fake):
    def other_request_wins():
        fake.quiz_answers[NO_ANSWER] = "먼저 도착한 다른 답"

    fake.before_write = other_request_wins
    assert_error(post_answer(client, NO_ANSWER, {"answer": "내 답"}), 409, "conflict", "already_answered")
    assert fake.quiz_answers[NO_ANSWER] == "먼저 도착한 다른 답"


def test_a_concurrent_request_that_saved_the_same_answer_first_is_still_200(client, fake):
    def other_request_wins():
        fake.quiz_answers[NO_ANSWER] = "같은 답"

    fake.before_write = other_request_wins
    response = post_answer(client, NO_ANSWER, {"answer": "같은 답"})
    assert response.status_code == 200
    assert response.json()["your_answer"] == "같은 답"


def test_another_users_item_is_404_and_writes_nothing(client, fake):
    response = post_answer(client, OTHERS, {"answer": "답"})
    assert_error(response, 404, "not_found")
    assert fake.writes == []
    assert fake.quiz_answers[OTHERS] == "OTHER의 답"
    # 없는 문항과 같은 응답이라 존재 여부가 새지 않는다.
    missing = post_answer(client, 999, {"answer": "답"})
    strip = lambda r: {k: v for k, v in r.json()["error"].items() if k != "request_id"}  # noqa: E731
    assert strip(missing) == strip(response)


def test_the_owner_still_reaches_their_own_item_and_the_other_user_theirs(client, fake):
    assert post_answer(client, NO_ANSWER, {"answer": "답"}).status_code == 200
    assert post_answer(client, OTHERS, {"answer": "OTHER의 답"}, token="other-token").status_code == 200
    assert_error(post_answer(client, NO_ANSWER, {"answer": "답"}, token="other-token"), 404, "not_found")


def test_an_item_deleted_between_the_check_and_the_write_is_404(client, fake):
    fake.vanish_on_write = True
    assert_error(post_answer(client, NO_ANSWER, {"answer": "답"}), 404, "not_found")


@pytest.mark.parametrize("item_id", ["abc", "0", "01", "-1", "1.5", "9223372036854775808", "1" * 30, "%20"])
def test_malformed_item_ids_are_404_without_db_calls_or_rate_count(client, fake, item_id):
    response = post_answer(client, item_id, {"answer": "답"})
    assert_error(response, 404, "not_found")
    assert fake.db_reads == 0
    assert fake.writes == []


# --- 검사 순서와 형식 (422) ---


def test_visitors_are_401_before_anything_else_and_touch_nothing(client, fake):
    assert_error(post_answer(client, NO_ANSWER, {"answer": "답"}, token=None), 401, "login_required")
    assert_error(put_followup(client, TWO_FOLLOWUPS, 2, {"answer": "답"}, token=None), 401, "login_required")
    assert fake.writes == []
    assert fake.db_reads == 0


def test_an_inactive_account_is_401(client, fake):
    assert_error(post_answer(client, NO_ANSWER, {"answer": "답"}, token="inactive-token"), 401, "login_required")
    assert fake.writes == []


def test_a_missing_or_wrong_origin_is_rejected_for_both_endpoints(client, fake):
    for send in (
        lambda h: client.post(f"/api/quiz/items/{NO_ANSWER}/answer", json={"answer": "답"}, headers=h),
        lambda h: client.put(f"/api/quiz/items/{TWO_FOLLOWUPS}/followups/2/answer", json={"answer": "답"}, headers=h),
    ):
        assert_error(send(cookie("member-token")), 403, "origin_not_allowed")
        assert_error(send({**cookie("member-token"), **origin("https://evil.example")}), 403, "origin_not_allowed")
    assert fake.writes == []


@pytest.mark.parametrize(
    "body,reason",
    [
        ({}, "required"),
        ({"answer": ""}, "required"),
        ({"answer": "   \n\t"}, "required"),
        ({"answer": "가" * (ANSWER_LIMIT + 1)}, "too_long"),
        ({"answer": "답\x00답"}, "invalid_format"),
    ],
)
def test_invalid_bodies_are_422_with_the_field_name_and_write_nothing(client, fake, body, reason):
    for response in (post_answer(client, NO_ANSWER, body), put_followup(client, TWO_FOLLOWUPS, 2, body)):
        assert_field(response, "answer", reason)
    assert fake.writes == []


@pytest.mark.parametrize("body", [{"answer": 5}, {"answer": None}, {"answer": ["a"]}, {"answer": "답", "extra": 1}])
def test_wrong_types_and_extra_fields_are_422(client, fake, body):
    assert_error(post_answer(client, NO_ANSWER, body), 422, "validation_failed")
    assert fake.writes == []


def test_the_body_is_checked_before_the_item_so_a_bad_body_never_reveals_ownership(client, fake):
    # 남의 문항이어도 본문이 틀리면 422다. 대상 확인(404)은 형식 검사(422) 뒤다(1.2).
    assert_error(post_answer(client, OTHERS, {"answer": ""}), 422, "validation_failed")


def test_the_target_check_comes_before_the_conflict_check(client, fake):
    # 남의 문항에 다른 답을 보내면 409가 아니라 404다. 남이 답했는지 새지 않는다.
    assert_error(post_answer(client, OTHERS, {"answer": "다른 답"}), 404, "not_found")


def test_write_rate_limit_counts_every_valid_request_even_for_missing_items(client, fake):
    for _ in range(WRITE.limit):
        assert_error(post_answer(client, 999, {"answer": "답"}), 404, "not_found")
    assert_error(post_answer(client, NO_ANSWER, {"answer": "답"}), 429, "rate_limited")
    assert_error(put_followup(client, TWO_FOLLOWUPS, 2, {"answer": "답"}), 429, "rate_limited")
    assert fake.writes == []
    # 다른 사용자는 영향이 없다.
    assert post_answer(client, OTHERS, {"answer": "OTHER의 답"}, token="other-token").status_code == 200


# --- 장애 ---


def test_a_database_outage_is_503_for_both_endpoints(client, fake):
    fake.down = True
    assert_error(post_answer(client, NO_ANSWER, {"answer": "답"}), 503, "service_unavailable")
    assert_error(put_followup(client, TWO_FOLLOWUPS, 2, {"answer": "답"}), 503, "service_unavailable")


def test_a_write_permission_error_is_500_not_a_retryable_503(client, fake):
    fake.config_error = True
    assert_error(post_answer(client, NO_ANSWER, {"answer": "답"}), 500, "internal_error")
    assert_error(put_followup(client, TWO_FOLLOWUPS, 2, {"answer": "답"}), 500, "internal_error")


# --- E14 ---


def test_answering_a_followup_saves_it_and_reports_whether_a_new_one_can_be_requested(client, fake):
    # 문항 4: 꼬리 질문 1번에 답하면 슬롯이 둘 미만이고 모두 답했으니 새 질문을 받을 수 있다.
    response = put_followup(client, ONE_FOLLOWUP, 1, {"answer": "꼬리 답"})
    assert response.status_code == 200
    assert response.json() == {"seq": 1, "answered": True, "can_request_followup": True}
    assert response.headers["cache-control"] == "private, no-store"
    assert next(f for f in fake.quiz_followups if f["item_id"] == ONE_FOLLOWUP)["user_answer"] == "꼬리 답"
    assert fake.writes == [("followup", ONE_FOLLOWUP, 1, "꼬리 답")]


def test_answering_the_second_followup_ends_the_chain(client, fake):
    response = put_followup(client, TWO_FOLLOWUPS, 2, {"answer": "꼬리 답 2"})
    assert response.status_code == 200
    assert response.json() == {"seq": 2, "answered": True, "can_request_followup": False}


def test_the_same_followup_answer_again_is_200_and_a_different_one_is_409(client, fake):
    assert put_followup(client, TWO_FOLLOWUPS, 1, {"answer": "꼬리 답 1"}).status_code == 200  # 이미 같은 답이 있다
    assert fake.writes == []
    assert_error(put_followup(client, TWO_FOLLOWUPS, 1, {"answer": "다른 꼬리 답"}), 409, "conflict", "already_answered")
    assert next(f for f in fake.quiz_followups if f["item_id"] == 2 and f["seq"] == 1)["user_answer"] == "꼬리 답 1"


def test_a_concurrent_followup_answer_that_won_the_race_is_judged_by_content(client, fake):
    def other_request_wins():
        next(f for f in fake.quiz_followups if f["item_id"] == TWO_FOLLOWUPS and f["seq"] == 2)["user_answer"] = "먼저 도착"

    fake.before_write = other_request_wins
    assert_error(put_followup(client, TWO_FOLLOWUPS, 2, {"answer": "내 답"}), 409, "conflict", "already_answered")
    assert put_followup(client, TWO_FOLLOWUPS, 2, {"answer": "먼저 도착"}).status_code == 200


@pytest.mark.parametrize("seq", [3, 0, -1, "x", "01", "1.0", 10])
def test_seq_outside_one_and_two_is_404_without_db_calls(client, fake, seq):
    assert_error(put_followup(client, TWO_FOLLOWUPS, seq, {"answer": "답"}), 404, "not_found")
    assert fake.db_reads == 0
    assert fake.writes == []


def test_a_followup_that_was_not_created_yet_is_404(client, fake):
    # 슬롯이 없다.
    assert_error(put_followup(client, NO_ANSWER, 1, {"answer": "답"}), 404, "not_found")
    assert_error(put_followup(client, ONE_FOLLOWUP, 2, {"answer": "답"}), 404, "not_found")
    # 슬롯은 있지만 질문이 아직 비어 있다(만드는 중).
    assert_error(put_followup(client, IN_PROGRESS, 1, {"answer": "답"}), 404, "not_found")
    assert fake.writes == []


def test_another_users_followup_is_404_and_untouched(client, fake):
    assert_error(put_followup(client, OTHERS, 1, {"answer": "답"}), 404, "not_found")
    assert fake.writes == []
    assert next(f for f in fake.quiz_followups if f["item_id"] == OTHERS)["user_answer"] is None


def test_a_followup_deleted_between_the_check_and_the_write_is_404(client, fake):
    fake.vanish_on_write = True
    assert_error(put_followup(client, ONE_FOLLOWUP, 1, {"answer": "답"}), 404, "not_found")


def test_followup_responses_have_no_grading_fields(client, fake):
    body = put_followup(client, ONE_FOLLOWUP, 1, {"answer": "꼬리 답"}).json()
    assert set(body) == {"seq", "answered", "can_request_followup"}
    answer = post_answer(client, NO_ANSWER, {"answer": "답"}).json()
    assert not {"correct", "is_correct", "score", "result"} & set(answer)


# --- AC-3: 이탈 뒤 다시 접속하면 E11이 답한 문항과 해설을 그대로 돌려준다 ---


def today(client, token="member-token"):
    return client.post("/api/quiz/today", headers=headers(token))


def test_reconnecting_restores_answers_explanations_and_followup_progress_through_e11(client, fake):
    before = today(client).json()
    unanswered = next(i for i in before["items"] if i["id"] == NO_ANSWER)
    assert unanswered["answered"] is False
    # 답하기 전에는 정답·해설·내 답이 없다.
    assert not {"your_answer", "correct_answer", "explanation"} & set(unanswered)

    assert post_answer(client, NO_ANSWER, {"answer": "합성 답변"}).status_code == 200
    assert put_followup(client, ONE_FOLLOWUP, 1, {"answer": "꼬리 답"}).status_code == 200

    # 사용자가 나갔다가 같은 날 다시 접속한다. 새 요청이고 서버가 기억하는 것은 DB뿐이다.
    after = today(client)
    assert after.status_code == 200
    assert after.json()["status"] == "ready"
    items = {i["id"]: i for i in after.json()["items"]}
    assert items[NO_ANSWER] == {
        "id": NO_ANSWER, "difficulty": "중", "question": "합성 문제 1", "answered": True,
        "your_answer": "합성 답변", "correct_answer": "합성 정답 1", "explanation": "합성 해설 1",
        "followups": [], "can_request_followup": True,
    }
    assert items[ONE_FOLLOWUP]["followups"] == [{"seq": 1, "question": "합성 꼬리 질문", "answered": True}]
    assert items[ONE_FOLLOWUP]["can_request_followup"] is True
    # 답하지 않은 꼬리 질문은 그대로 이어서 답할 수 있게 남아 있다.
    assert items[TWO_FOLLOWUPS]["followups"] == [
        {"seq": 1, "question": "합성 꼬리 질문 1", "answered": True},
        {"seq": 2, "question": "합성 꼬리 질문 2", "answered": False},
    ]
    assert items[TWO_FOLLOWUPS]["can_request_followup"] is False
    # E11 응답에는 이 사용자의 답만 있고 다른 사용자의 문항·답은 없다.
    assert OTHERS not in items
    assert "OTHER" not in after.text


def test_the_e12_response_matches_what_e11_later_shows_for_the_same_item(client, fake):
    sent = post_answer(client, NO_ANSWER, {"answer": "합성 답변"}).json()
    shown = next(i for i in today(client).json()["items"] if i["id"] == NO_ANSWER)
    assert (shown["your_answer"], shown["correct_answer"], shown["explanation"], shown["difficulty"]) == (
        sent["your_answer"], sent["correct_answer"], sent["explanation"], sent["difficulty"],
    )
    assert shown["can_request_followup"] is sent["can_request_followup"]


def test_followup_progress_rule_is_shared_by_e11_e12_and_e14():
    assert quiz.followup_progress(False, []) == (False, 2)
    assert quiz.followup_progress(True, []) == (True, 2)
    assert quiz.followup_progress(True, [{"question": "q", "user_answer": None}]) == (False, 1)
    assert quiz.followup_progress(True, [{"question": "q", "user_answer": "a"}]) == (True, 1)
    assert quiz.followup_progress(True, [{"question": None, "user_answer": None}]) == (False, 1)
    two = [{"question": "q", "user_answer": "a"}, {"question": "q", "user_answer": "a"}]
    assert quiz.followup_progress(True, two) == (False, 0)
