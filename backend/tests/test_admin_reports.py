"""E25·E26 운영자 신고 목록·처리 (MEG-83). 가짜 Supabase로 네트워크 없이 돈다. 데이터는 모두 합성이다.

실제 로컬 DB(SQL 함수·제약 포함)에서의 동작은 docs/backend-local-guide.md 8절 순서로 따로 확인한다.
여기서는 권한·검사 순서·응답 모양·무효화 선택값·실패 뒤 재시도를 본다. 가짜는 실제 래퍼와 같은 결과 모양을 낸다.
"""

from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import admin_reports
from app.common import install_common_layer
from app.rate_limit import WRITE
from app.supabase import SupabaseConfigError, SupabaseUnavailable, get_supabase
from support import FakeSupabase, cookie, origin

OPERATOR = "00000000-0000-0000-0000-0000000000a1"
MEMBER = "00000000-0000-0000-0000-0000000000b1"
REPORTER = "00000000-0000-0000-0000-0000000000c1"


@dataclass
class FakeReportsSupabase(FakeSupabase):
    """reports·ai_explanations·quiz_items 흉내. 신고자(user_id)는 행에 있지만 응답에 나가면 안 된다."""

    reports: dict[int, dict] = field(default_factory=dict)
    explanations: dict[int, dict] = field(default_factory=dict)
    items: dict[int, dict] = field(default_factory=dict)
    invalidate_down: bool = False
    resolve_down: bool = False
    # 신고가 읽힌 뒤 처리 전에 지워진 것처럼 만든다(사용자 삭제와 겹친 경우).
    report_vanishes_before_resolve: bool = False
    writes: list[str] = field(default_factory=list)
    list_calls: list[tuple] = field(default_factory=list)
    _clock: int = 0

    def list_admin_reports(self, status: str, limit: int, before_id: int | None) -> list[dict]:
        self.list_calls.append((status, limit, before_id))
        ids = sorted((rid for rid, row in self.reports.items() if row["status"] == status), reverse=True)
        if before_id is not None:
            ids = [rid for rid in ids if rid < before_id]
        return [self._summary(rid) for rid in ids[:limit]]

    def _summary(self, rid: int) -> dict:
        row = self.reports[rid]
        if row["ai_explanation_id"] is not None:
            e = self.explanations[row["ai_explanation_id"]]
            target = {
                "type": "ai_explanation", "id": row["ai_explanation_id"],
                "term_key_snapshot": e["term_key_snapshot"], "body": e["body"],
            }
        else:
            q = self.items[row["quiz_item_id"]]
            target = {"type": "quiz_item", "id": row["quiz_item_id"], "question": q["question"], "answer": q["answer"]}
        return {"id": rid, "status": row["status"], "body": row["body"], "target": target}

    def get_admin_report(self, report_id: int) -> dict | None:
        row = self.reports.get(report_id)
        if row is None:
            return None
        return {"id": report_id, "status": row["status"], "ai_explanation_id": row["ai_explanation_id"]}

    def invalidate_ai_explanation(self, explanation_id: int) -> int:
        self.writes.append("invalidate")
        if self.invalidate_down:
            raise SupabaseUnavailable("down")
        explanation = self.explanations[explanation_id]
        if explanation["invalidated"]:
            return 0
        explanation["invalidated"] = True
        return 1

    def mark_report_resolved(self, report_id: int, resolved_at: str) -> bool:
        self.writes.append("resolve")
        if self.resolve_down:
            raise SupabaseUnavailable("down")
        if self.report_vanishes_before_resolve:
            self.reports.pop(report_id, None)
        row = self.reports.get(report_id)
        if row is None or row["status"] != "open":
            return False
        row["status"] = "resolved"
        row["resolved_at"] = resolved_at
        return True


def build_app(fake: FakeReportsSupabase) -> FastAPI:
    app = FastAPI()
    install_common_layer(app)
    app.dependency_overrides[get_supabase] = lambda: fake
    app.include_router(admin_reports.router)
    return app


def add_report(fake, rid, *, status="open", ai=None, item=None, body="", resolved_at=None):
    fake.reports[rid] = {
        "user_id": REPORTER, "status": status, "body": body, "resolved_at": resolved_at,
        "ai_explanation_id": ai, "quiz_item_id": item,
    }


@pytest.fixture
def fake() -> FakeReportsSupabase:
    """열린 신고 5건(AI 설명 3, 퀴즈 문항 2)과 처리된 신고 1건. 번호는 가이드 8절 합성 데이터와 같은 모양이다."""
    fake = FakeReportsSupabase()
    fake.add_user("operator-token", OPERATOR, role="operator")
    fake.add_user("member-token", MEMBER)
    for eid in (1, 2, 3):
        fake.explanations[eid] = {"term_key_snapshot": f"fixture alpha {eid}", "body": f"합성 설명 {eid}", "invalidated": False}
    fake.explanations[4] = {"term_key_snapshot": "fixture alpha 4", "body": "합성 설명 4", "invalidated": True}
    for iid in (4, 5):
        fake.items[iid] = {"question": f"합성 질문 {iid}?", "answer": f"합성 답 {iid}"}
    add_report(fake, 1, ai=1, body="틀렸어요")
    add_report(fake, 2, ai=2)
    add_report(fake, 3, ai=3, body="합성 신고")
    add_report(fake, 4, item=4)
    add_report(fake, 5, item=5)
    add_report(fake, 6, status="resolved", ai=4, resolved_at="2026-10-30T00:00:00+00:00")
    return fake


@pytest.fixture
def client(fake) -> TestClient:
    return TestClient(build_app(fake))


def auth(token: str | None = "operator-token") -> dict[str, str]:
    return {**origin(), **(cookie(token) if token else {})}


def assert_error(response, status: int, code: str):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


def assert_field(response, name: str, reason: str):
    assert_error(response, 422, "validation_failed")
    assert {"name": name, "reason": reason} in [
        {"name": f["name"], "reason": f["reason"]} for f in response.json()["error"]["fields"]
    ]


def patch(client, report_id, body, token="operator-token"):
    return client.patch(f"/api/admin/reports/{report_id}", json=body, headers=auth(token))


# --- 운영자만 쓴다. 방문자 401, 일반 사용자 403, 거부되면 DB를 바꾸지 않는다 ---

CALLS = [
    ("GET", "/api/admin/reports", None),
    ("PATCH", "/api/admin/reports/1", {"status": "resolved"}),
    ("PATCH", "/api/admin/reports/1", {"status": "resolved", "invalidate_explanation": True}),
]


@pytest.mark.parametrize("method,path,body", CALLS)
@pytest.mark.parametrize("token,status,code", [(None, 401, "login_required"), ("member-token", 403, "forbidden")])
def test_non_operators_are_rejected_without_changes(client, fake, method, path, body, token, status, code):
    response = client.request(method, path, json=body, headers=auth(token))
    assert_error(response, status, code)
    assert fake.writes == []
    assert fake.rpc_calls == []  # 속도 제한 카운터도 건드리지 않는다
    assert fake.list_calls == []
    assert fake.reports[1]["status"] == "open"
    assert not fake.explanations[1]["invalidated"]


def test_patch_without_allowed_origin_is_rejected(client, fake):
    response = client.patch("/api/admin/reports/1", json={"status": "resolved"}, headers=cookie("operator-token"))
    assert_error(response, 403, "origin_not_allowed")
    assert fake.writes == []


# --- E25 목록 ---


def test_list_defaults_to_open_newest_first_with_target_summaries(client):
    response = client.get("/api/admin/reports", headers=auth())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "reports": [
            {"id": 5, "status": "open", "body": "", "target": {
                "type": "quiz_item", "id": 5, "question": "합성 질문 5?", "answer": "합성 답 5"}},
            {"id": 4, "status": "open", "body": "", "target": {
                "type": "quiz_item", "id": 4, "question": "합성 질문 4?", "answer": "합성 답 4"}},
            {"id": 3, "status": "open", "body": "합성 신고", "target": {
                "type": "ai_explanation", "id": 3, "term_key_snapshot": "fixture alpha 3", "body": "합성 설명 3"}},
            {"id": 2, "status": "open", "body": "", "target": {
                "type": "ai_explanation", "id": 2, "term_key_snapshot": "fixture alpha 2", "body": "합성 설명 2"}},
            {"id": 1, "status": "open", "body": "틀렸어요", "target": {
                "type": "ai_explanation", "id": 1, "term_key_snapshot": "fixture alpha 1", "body": "합성 설명 1"}},
        ],
        "next_cursor": None,
    }


def test_list_never_exposes_the_reporter(client):
    for status in ("open", "resolved"):
        text = client.get("/api/admin/reports", params={"status": status}, headers=auth()).text
        assert REPORTER not in text
        assert "user_id" not in text


def test_list_resolved_returns_only_resolved(client):
    response = client.get("/api/admin/reports", params={"status": "resolved"}, headers=auth())
    assert [r["id"] for r in response.json()["reports"]] == [6]
    assert response.json()["reports"][0]["status"] == "resolved"


def test_list_with_no_matching_reports_is_empty(client, fake):
    fake.reports = {6: fake.reports[6]}
    response = client.get("/api/admin/reports", headers=auth())
    assert response.status_code == 200
    assert response.json() == {"reports": [], "next_cursor": None}


def test_list_pages_without_gaps_or_repeats(client):
    seen, cursor = [], None
    for _ in range(5):
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = client.get("/api/admin/reports", params=params, headers=auth()).json()
        seen.append([r["id"] for r in body["reports"]])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == [[5, 4], [3, 2], [1]]
    assert cursor is None


def test_next_cursor_is_the_last_id_and_only_present_when_more_remain(client, fake):
    first = client.get("/api/admin/reports", params={"limit": 2}, headers=auth()).json()
    assert first["next_cursor"] == "4"
    # 마지막 쪽이 limit과 딱 맞아 떨어지면 다음 쪽은 없다.
    exact = client.get("/api/admin/reports", params={"limit": 5}, headers=auth()).json()
    assert len(exact["reports"]) == 5 and exact["next_cursor"] is None
    # 한 개 더 읽어 다음 쪽을 안다.
    assert fake.list_calls[0] == ("open", 3, None)


@pytest.mark.parametrize("params,name,reason", [
    ({"status": "all"}, "status", "invalid_value"),
    ({"status": "resolved,open"}, "status", "invalid_value"),
    ({"limit": 0}, "limit", "out_of_range"),
    ({"limit": 101}, "limit", "out_of_range"),
    ({"limit": "x"}, "limit", "invalid_format"),
    ({"cursor": "abc"}, "cursor", "invalid_format"),
    ({"cursor": "0"}, "cursor", "invalid_format"),
    ({"cursor": "-3"}, "cursor", "invalid_format"),
    ({"cursor": "9223372036854775808"}, "cursor", "invalid_format"),
    ({"cursor": "007"}, "cursor", "invalid_format"),
])
def test_list_rejects_bad_query_values(client, fake, params, name, reason):
    assert_field(client.get("/api/admin/reports", params=params, headers=auth()), name, reason)
    assert fake.list_calls == []


def test_listing_does_not_count_against_the_write_limit(client, fake):
    client.get("/api/admin/reports", headers=auth())
    assert fake.rpc_calls == []


# --- E26 처리 ---


def snapshot(fake):
    return {rid: dict(row) for rid, row in fake.reports.items()}, {eid: dict(e) for eid, e in fake.explanations.items()}


@pytest.mark.parametrize("body", [
    {"status": "resolved"},
    {"status": "resolved", "invalidate_explanation": False},
])
def test_resolve_without_or_with_false_keeps_the_explanation_valid(client, fake, body):
    response = patch(client, 1, body)
    assert response.status_code == 200
    assert response.json() == {"id": 1, "status": "resolved"}
    assert fake.reports[1]["status"] == "resolved"
    assert fake.reports[1]["resolved_at"] is not None
    assert [e["invalidated"] for e in fake.explanations.values()] == [False, False, False, True]
    assert fake.writes == ["resolve"]  # 무효화 호출 자체가 없다


def test_resolve_with_true_invalidates_only_that_explanation(client, fake):
    response = patch(client, 3, {"status": "resolved", "invalidate_explanation": True})
    assert response.status_code == 200
    assert response.json() == {"id": 3, "status": "resolved"}
    assert fake.reports[3]["status"] == "resolved"
    assert fake.explanations[3]["invalidated"] is True
    # 다른 설명과 다른 신고는 그대로다.
    assert [fake.explanations[e]["invalidated"] for e in (1, 2)] == [False, False]
    assert [fake.reports[r]["status"] for r in (1, 2, 4, 5)] == ["open"] * 4
    assert fake.writes == ["invalidate", "resolve"]  # 무효화를 먼저 한다


def test_resolve_with_true_on_a_quiz_item_report_ignores_the_flag(client, fake):
    response = patch(client, 4, {"status": "resolved", "invalidate_explanation": True})
    assert response.status_code == 200
    assert response.json() == {"id": 4, "status": "resolved"}
    assert fake.reports[4]["status"] == "resolved"
    assert fake.writes == ["resolve"]
    assert [e["invalidated"] for e in fake.explanations.values()] == [False, False, False, True]


def test_resolved_report_leaves_the_open_list_and_enters_the_resolved_list(client):
    patch(client, 2, {"status": "resolved"})
    assert [r["id"] for r in client.get("/api/admin/reports", headers=auth()).json()["reports"]] == [5, 4, 3, 1]
    resolved = client.get("/api/admin/reports", params={"status": "resolved"}, headers=auth()).json()["reports"]
    assert [r["id"] for r in resolved] == [6, 2]


def test_resolving_again_is_ok_and_keeps_the_first_resolved_time(client, fake):
    assert patch(client, 1, {"status": "resolved"}).status_code == 200
    first_time = fake.reports[1]["resolved_at"]
    again = patch(client, 1, {"status": "resolved"})
    assert again.status_code == 200
    assert again.json() == {"id": 1, "status": "resolved"}
    assert fake.reports[1]["resolved_at"] == first_time


def test_already_resolved_report_still_applies_a_later_invalidation(client, fake):
    # 신고 6은 처음부터 처리됨이다. 대상 설명 4는 이미 무효화돼 있어 바뀌는 것이 없다.
    response = patch(client, 6, {"status": "resolved", "invalidate_explanation": True})
    assert response.status_code == 200
    assert fake.reports[6]["resolved_at"] == "2026-10-30T00:00:00+00:00"
    # 처리만 하고 무효화는 안 했던 신고에 나중에 true로 다시 보내면 설명이 무효화된다.
    patch(client, 1, {"status": "resolved"})
    assert fake.explanations[1]["invalidated"] is False
    assert patch(client, 1, {"status": "resolved", "invalidate_explanation": True}).status_code == 200
    assert fake.explanations[1]["invalidated"] is True


def test_invalidation_failure_keeps_the_report_open_and_a_retry_finishes(client, fake):
    fake.invalidate_down = True
    response = patch(client, 3, {"status": "resolved", "invalidate_explanation": True})
    assert_error(response, 503, "service_unavailable")
    assert fake.reports[3]["status"] == "open"
    assert fake.explanations[3]["invalidated"] is False
    assert "resolve" not in fake.writes  # 무효화에 실패하면 신고를 처리하지 않는다
    fake.invalidate_down = False
    assert patch(client, 3, {"status": "resolved", "invalidate_explanation": True}).status_code == 200
    assert fake.reports[3]["status"] == "resolved"
    assert fake.explanations[3]["invalidated"] is True


def test_resolve_failure_after_invalidation_is_retryable(client, fake):
    fake.resolve_down = True
    assert_error(patch(client, 3, {"status": "resolved", "invalidate_explanation": True}), 503, "service_unavailable")
    # 설명은 이미 무효화됐고 신고는 열린 채다.
    assert fake.explanations[3]["invalidated"] is True
    assert fake.reports[3]["status"] == "open"
    fake.resolve_down = False
    retry = patch(client, 3, {"status": "resolved", "invalidate_explanation": True})
    assert retry.status_code == 200
    assert fake.reports[3]["status"] == "resolved"


@pytest.mark.parametrize("report_id", ["99", "0", "abc", "-1", "1.5", "007", "9223372036854775808", "99999999999999999999"])
def test_unknown_or_malformed_report_id_is_404_without_changes(client, fake, report_id):
    before = snapshot(fake)
    assert_error(patch(client, report_id, {"status": "resolved", "invalidate_explanation": True}), 404, "not_found")
    assert snapshot(fake) == before
    assert fake.writes == []


def test_report_deleted_while_resolving_is_404(client, fake):
    fake.report_vanishes_before_resolve = True
    assert_error(patch(client, 2, {"status": "resolved"}), 404, "not_found")


@pytest.mark.parametrize("body,name,reason", [
    ({}, "status", "required"),
    ({"invalidate_explanation": True}, "status", "required"),
    ({"status": "open"}, "status", "invalid_value"),
    ({"status": "closed"}, "status", "invalid_value"),
    ({"status": ""}, "status", "invalid_value"),
    ({"status": "resolved", "invalidate_explanation": "true"}, "invalidate_explanation", "invalid_format"),
    ({"status": "resolved", "invalidate_explanation": 1}, "invalidate_explanation", "invalid_format"),
    ({"status": "resolved", "invalidate_explanation": None}, "invalidate_explanation", "invalid_format"),
])
def test_resolve_rejects_bad_bodies_without_changes(client, fake, body, name, reason):
    assert_field(patch(client, 1, body), name, reason)
    assert fake.writes == []
    assert fake.reports[1]["status"] == "open"


def test_resolve_rejects_unknown_fields(client, fake):
    response = patch(client, 1, {"status": "resolved", "user_id": MEMBER, "body": "바꿈"})
    assert_error(response, 422, "validation_failed")
    assert fake.writes == []
    assert fake.reports[1]["body"] == "틀렸어요"


def test_resolve_counts_against_the_write_limit_per_operator(client, fake):
    patch(client, 1, {"status": "resolved"})
    key = f"{WRITE.name}:{fake.keyed_hash(f'user:{OPERATOR}')}"
    assert fake.hits(key, WRITE.window_seconds) == 1


def test_resolve_over_the_write_limit_is_429_without_changes(client, fake):
    for _ in range(WRITE.limit):
        assert patch(client, 99, {"status": "resolved"}).status_code == 404
    response = patch(client, 1, {"status": "resolved", "invalidate_explanation": True})
    assert_error(response, 429, "rate_limited")
    assert fake.reports[1]["status"] == "open"
    assert fake.writes == []


def test_database_misconfiguration_is_a_500_without_details(client, fake):
    def broken(*args, **kwargs):
        raise SupabaseConfigError("reports select status 401 secret-detail")

    fake.get_admin_report = broken
    response = patch(client, 1, {"status": "resolved"})
    assert_error(response, 500, "internal_error")
    assert "secret-detail" not in response.text
