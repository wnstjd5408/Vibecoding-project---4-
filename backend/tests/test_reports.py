"""E10 오류 신고 (MEG-88). 가짜 Supabase로 네트워크 없이 돈다. 데이터는 모두 합성이다.

신고 표의 유일 인덱스·외래 키 동작은 SupabaseClient 시험(tests/test_supabase_client.py)과 실제 PostgreSQL 시험
(tests/integration/test_ai_ledger_sql.py의 신고 절)이 따로 본다.
"""

from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import reports
from app.common import install_common_layer
from app.errors import FIELD_MESSAGES
from app.rate_limit import WRITE
from app.supabase import SupabaseUnavailable, get_supabase
from support import FakeSupabase, cookie, origin

MEMBER = "00000000-0000-4000-8000-00000000000a"
OTHER = "00000000-0000-4000-8000-00000000000b"
EXPLANATION = 31
INVALIDATED = 32
MY_ITEM = 41
OTHER_ITEM = 42


@dataclass
class ReportFake(FakeSupabase):
    """FakeSupabase에 E10이 쓰는 대상 확인과 신고 저장을 더한다."""

    # ai_explanations 행: id -> 무효화됐는지
    explanations: dict = field(default_factory=dict)
    # quiz_items 행: id -> 소유 사용자 id
    quiz_items: dict = field(default_factory=dict)
    # reports 행: {id, user_id, type, target_id, body, status}
    report_rows: list = field(default_factory=list)
    target_checks: list = field(default_factory=list)
    # create_report 직전에 대상이 지워진 것을 흉내 낸다.
    vanish_before_insert: bool = False
    next_report_id: int = 900

    def report_target_exists(self, target_type: str, target_id: int, user_id: str) -> bool:
        if self.down:
            raise SupabaseUnavailable("down")
        self.target_checks.append((target_type, target_id, user_id))
        if target_type == "ai_explanation":
            return self.explanations.get(target_id) is False
        return self.quiz_items.get(target_id) == user_id

    def create_report(self, user_id: str, target_type: str, target_id: int, body: str):
        if self.down:
            raise SupabaseUnavailable("down")
        if self.vanish_before_insert:
            return None
        for row in self.report_rows:
            same = (row["user_id"], row["type"], row["target_id"]) == (user_id, target_type, target_id)
            if same and row["status"] == "open":
                return {"id": row["id"], "status": row["status"]}, False
        row = {"id": self.next_report_id, "user_id": user_id, "type": target_type, "target_id": target_id,
               "body": body, "status": "open"}
        self.next_report_id += 1
        self.report_rows.append(row)
        return {"id": row["id"], "status": "open"}, True


@pytest.fixture
def fake() -> ReportFake:
    fake = ReportFake()
    fake.add_user("member-token", MEMBER)
    fake.add_user("other-token", OTHER)
    fake.add_user("inactive-token", "00000000-0000-4000-8000-00000000000c", is_active=False)
    fake.explanations = {EXPLANATION: False, INVALIDATED: True}
    fake.quiz_items = {MY_ITEM: MEMBER, OTHER_ITEM: OTHER}
    return fake


@pytest.fixture
def client(fake) -> TestClient:
    app = FastAPI()
    install_common_layer(app)
    app.dependency_overrides[get_supabase] = lambda: fake
    app.include_router(reports.router)
    return TestClient(app)


def report(client, target, body="합성 신고 내용", token="member-token", raw=None):
    payload = raw if raw is not None else {"target": target, "body": body}
    headers = {**origin(), **(cookie(token) if token else {})}
    return client.post("/api/reports", json=payload, headers=headers)


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


# --- AC-1: 로그인 사용자가 AI 설명과 자기 퀴즈 문항을 신고하면 저장된다 ---


def test_member_reports_a_valid_ai_explanation_and_gets_201_with_id_and_status_only(client, fake):
    response = report(client, {"type": "ai_explanation", "id": EXPLANATION})

    assert response.status_code == 201
    assert response.json() == {"id": 900, "status": "open"}
    assert response.headers["cache-control"] == "private, no-store"
    assert fake.report_rows == [
        {"id": 900, "user_id": MEMBER, "type": "ai_explanation", "target_id": EXPLANATION, "body": "합성 신고 내용",
         "status": "open"}
    ]


def test_member_reports_their_own_quiz_item(client, fake):
    response = report(client, {"type": "quiz_item", "id": MY_ITEM}, body="")

    assert response.status_code == 201
    assert [(r["user_id"], r["type"], r["target_id"], r["body"]) for r in fake.report_rows] == [
        (MEMBER, "quiz_item", MY_ITEM, "")]


def test_body_is_optional_and_defaults_to_empty(client, fake):
    response = report(client, None, raw={"target": {"type": "ai_explanation", "id": EXPLANATION}})

    assert response.status_code == 201
    assert fake.report_rows[0]["body"] == ""


def test_visitor_is_a_401_with_no_db_work(client, fake):
    response = report(client, {"type": "ai_explanation", "id": EXPLANATION}, token=None)

    assert_error(response, 401, "login_required")
    assert (fake.target_checks, fake.report_rows, fake.rpc_calls) == ([], [], [])


def test_inactive_account_is_a_visitor(client, fake):
    response = report(client, {"type": "ai_explanation", "id": EXPLANATION}, token="inactive-token")

    assert_error(response, 401, "login_required")
    assert fake.report_rows == []


def test_visitor_401_wins_over_a_broken_body(client):
    response = client.post("/api/reports", json={"target": "x"}, headers=origin())

    assert_error(response, 401, "login_required")


# --- AC-2: 남의 퀴즈 문항 id나 1회용·무효 설명으로 신고하면 거부된다 ---


@pytest.mark.parametrize(
    "target",
    [
        {"type": "quiz_item", "id": OTHER_ITEM},
        {"type": "quiz_item", "id": 9999},
        {"type": "ai_explanation", "id": INVALIDATED},
        {"type": "ai_explanation", "id": 9999},
    ],
    ids=["other-users-item", "missing-item", "invalidated-explanation", "missing-explanation"],
)
def test_unreportable_targets_are_the_same_404_without_a_saved_report(client, fake, target):
    response = report(client, target)

    assert_error(response, 404, "not_found")
    assert set(response.json()["error"]) == {"code", "message", "request_id"}
    assert fake.report_rows == []


def test_other_user_cannot_report_my_quiz_item_but_can_report_the_shared_explanation(client, fake):
    assert_error(report(client, {"type": "quiz_item", "id": MY_ITEM}, token="other-token"), 404, "not_found")
    assert report(client, {"type": "ai_explanation", "id": EXPLANATION}, token="other-token").status_code == 201
    assert fake.target_checks[0] == ("quiz_item", MY_ITEM, OTHER)


def test_a_one_off_explanation_without_an_id_cannot_be_reported(client, fake):
    # 1회용 설명은 id가 null이다. 대상 모양 검사에서 422로 끝난다(화면은 이것을 "찾을 수 없음"으로 안내한다).
    response = report(client, {"type": "ai_explanation", "id": None})

    assert_error(response, 422, "validation_failed")
    assert fake.report_rows == [] and fake.target_checks == []


def test_a_target_deleted_between_the_check_and_the_insert_is_a_404(client, fake):
    fake.vanish_before_insert = True

    assert_error(report(client, {"type": "ai_explanation", "id": EXPLANATION}), 404, "not_found")
    assert fake.report_rows == []


# --- AC-3: 같은 대상을 다시 신고하면 새 행 없이 기존 신고가 돌아온다 ---


def test_the_same_open_report_is_a_200_with_the_existing_id_and_no_new_row(client, fake):
    first = report(client, {"type": "ai_explanation", "id": EXPLANATION}, body="처음 내용")
    again = report(client, {"type": "ai_explanation", "id": EXPLANATION}, body="다른 내용")

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == first.json()
    assert len(fake.report_rows) == 1
    # 기존 신고의 본문은 고쳐지지 않는다
    assert fake.report_rows[0]["body"] == "처음 내용"


def test_a_resolved_report_allows_a_new_one_and_other_users_are_separate(client, fake):
    first = report(client, {"type": "ai_explanation", "id": EXPLANATION}).json()
    fake.report_rows[0]["status"] = "resolved"

    after_resolve = report(client, {"type": "ai_explanation", "id": EXPLANATION})
    other_user = report(client, {"type": "ai_explanation", "id": EXPLANATION}, token="other-token")

    assert after_resolve.status_code == 201 and after_resolve.json()["id"] != first["id"]
    assert other_user.status_code == 201
    assert len(fake.report_rows) == 3


# --- 2단계 구조 검증: 422 ---


@pytest.mark.parametrize(
    ("raw", "name", "reason"),
    [
        ({"body": "x"}, "target", "required"),
        ({"target": {"id": 1}, "body": "x"}, "target.type", "required"),
        ({"target": {"type": "ai_explanation"}, "body": "x"}, "target.id", "required"),
        ({"target": {"type": "note", "id": 1}, "body": "x"}, "target.type", "invalid_value"),
        ({"target": {"type": "ai_explanation", "id": "31"}, "body": "x"}, "target.id", "invalid_format"),
        ({"target": {"type": "ai_explanation", "id": 0}, "body": "x"}, "target.id", "out_of_range"),
        ({"target": {"type": "ai_explanation", "id": 2**63}, "body": "x"}, "target.id", "out_of_range"),
        ({"target": {"type": "ai_explanation", "id": True}, "body": "x"}, "target.id", "invalid_format"),
        ({"target": {"type": "ai_explanation", "id": 31}, "body": 5}, "body", "invalid_format"),
        ({"target": {"type": "ai_explanation", "id": 31}, "body": "가" * 1001}, "body", "too_long"),
    ],
)
def test_malformed_requests_are_422_with_the_field_and_reason_before_any_db_work(client, fake, raw, name, reason):
    response = report(client, None, raw=raw)

    assert_error(response, 422, "validation_failed")
    assert response.json()["error"]["fields"][0] == {"name": name, "reason": reason, "message": FIELD_MESSAGES[reason]}
    assert fake.target_checks == [] and fake.rpc_calls == []


def test_extra_fields_are_rejected(client):
    raw = {"target": {"type": "ai_explanation", "id": 31}, "body": "x", "status": "resolved"}

    assert_error(report(client, None, raw=raw), 422, "validation_failed")


def test_body_limit_counts_code_points_not_bytes_and_1000_is_accepted(client):
    thousand = "가" * 1000
    emoji = "👍" * 1000  # 코드포인트 1000개, UTF-8 4000바이트

    assert report(client, {"type": "ai_explanation", "id": EXPLANATION}, body=thousand).status_code == 201
    assert report(client, {"type": "quiz_item", "id": MY_ITEM}, body=emoji).status_code == 201


def test_a_broken_json_body_is_a_400(client):
    headers = {**origin(), **cookie("member-token"), "Content-Type": "application/json"}

    assert_error(client.post("/api/reports", content=b"{not json", headers=headers), 400, "bad_request")


# --- 속도 제한: 대상 확인보다 먼저 센다 ---


def test_write_limit_counts_before_the_target_check_and_blocks_the_next_request(client, fake):
    key = f"{WRITE.name}:{fake.keyed_hash(f'user:{MEMBER}')}"

    for _ in range(WRITE.limit):
        assert_error(report(client, {"type": "quiz_item", "id": 9999}), 404, "not_found")
    assert fake.hits(key, WRITE.window_seconds) == WRITE.limit
    checks = len(fake.target_checks)

    blocked = report(client, {"type": "ai_explanation", "id": EXPLANATION})

    assert_error(blocked, 429, "rate_limited")
    assert int(blocked.headers["retry-after"]) >= 1
    assert len(fake.target_checks) == checks and fake.report_rows == []
    # 다른 사용자는 따로 센다
    assert report(client, {"type": "ai_explanation", "id": EXPLANATION}, token="other-token").status_code == 201


def test_validation_errors_are_not_counted(client, fake):
    report(client, None, raw={"target": {"type": "x", "id": 1}})

    assert fake.rpc_calls == []


# --- DB 장애 ---


def test_db_down_is_a_503(client, fake):
    fake.down = True

    # 세션 확인이 먼저 DB를 읽는다. 어느 단계에서 나든 저장 전 장애는 503이다.
    assert_error(report(client, {"type": "ai_explanation", "id": EXPLANATION}), 503, "service_unavailable")
