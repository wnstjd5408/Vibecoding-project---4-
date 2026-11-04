"""E08 즐겨찾기 추가·해제 (MEG-89). 가짜 Supabase로 네트워크 없이 돈다. 데이터는 모두 합성이다.

실제 로컬 DB(기본 키·외래 키 제약, 날짜 열)에서의 동작은 docs/backend-local-guide.md 8절 순서로 따로 확인한다.
여기서는 권한·검사 순서·응답 모양·멱등성·KST 날짜·사용자 분리·중간 실패 뒤 재시도를 본다.
가짜는 실제 래퍼와 같은 규칙(이력을 먼저, 즐겨찾기를 나중에 넣고, 충돌은 무시)을 따른다.
"""

from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import favorites, session
from app.common import install_common_layer
from app.rate_limit import WRITE
from app.supabase import SupabaseConfigError, SupabaseUnavailable, get_supabase
from support import FakeSupabase, cookie, origin

A = "00000000-0000-0000-0000-00000000000a"
B = "00000000-0000-0000-0000-00000000000b"
INACTIVE = "00000000-0000-0000-0000-00000000000c"
TERM = 7
OTHER_TERM = 8
MISSING = 99
# 2026-10-23T05:30:00Z = 2026-10-23 14:30 KST
NOW = 1_792_733_400
# 2026-10-22T14:59:59Z = 2026-10-22 23:59:59 KST, 1초 뒤가 KST 자정이다.
BEFORE_KST_MIDNIGHT = 1_792_681_199


@dataclass
class FakeFavoritesSupabase(FakeSupabase):
    """terms·favorites(상위 클래스 필드)·favorite_events 흉내. 쓰기 순서를 writes에 기록한다."""

    terms: set[int] = field(default_factory=set)
    events: set[tuple[str, int, str]] = field(default_factory=set)
    writes: list[str] = field(default_factory=list)
    # favorites 삽입만 실패하는 장애(이력은 이미 들어간 뒤)
    favorites_write_down: bool = False

    def favorite_term(self, user_id: str, term_id: int, study_date: str) -> bool:
        if self.down:
            raise SupabaseUnavailable("down")
        self.writes.append("event")
        if term_id not in self.terms:
            return False
        self.events.add((user_id, term_id, study_date))
        self.writes.append("favorite")
        if self.favorites_write_down:
            raise SupabaseUnavailable("down")
        self.favorites.add((user_id, term_id))
        return True

    def unfavorite_term(self, user_id: str, term_id: int) -> bool:
        if self.down:
            raise SupabaseUnavailable("down")
        self.writes.append("unfavorite")
        self.favorites.discard((user_id, term_id))
        return term_id in self.terms


def build_app(fake: FakeFavoritesSupabase) -> FastAPI:
    app = FastAPI()
    install_common_layer(app)
    app.dependency_overrides[get_supabase] = lambda: fake
    app.include_router(favorites.router)
    return app


@pytest.fixture
def fake(monkeypatch) -> FakeFavoritesSupabase:
    fake = FakeFavoritesSupabase()
    fake.add_user("a-token", A)
    fake.add_user("b-token", B)
    fake.add_user("inactive-token", INACTIVE, is_active=False)
    fake.terms = {TERM, OTHER_TERM}
    # B는 다른 용어를 이미 즐겨찾기했고 이력도 있다. A의 변경이 이것을 건드리면 안 된다.
    fake.favorites = {(B, OTHER_TERM)}
    fake.events = {(B, OTHER_TERM, "2026-10-22")}
    monkeypatch.setattr(session, "now", lambda: NOW + 0.9)
    return fake


@pytest.fixture
def client(fake) -> TestClient:
    return TestClient(build_app(fake))


def put(client, term_id, body, token: str | None = "a-token", headers: dict | None = None):
    sent = {**origin(), **(cookie(token) if token else {}), **(headers or {})}
    return client.put(f"/api/favorites/{term_id}", json=body, headers=sent)


def assert_error(response, status: int, code: str):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code


def assert_field(response, name: str, reason: str):
    assert_error(response, 422, "validation_failed")
    assert {"name": name, "reason": reason} in [
        {"name": f["name"], "reason": f["reason"]} for f in response.json()["error"]["fields"]
    ]


# --- AC-1: 추가·해제하면 상태가 바뀌어 돌아온다 ---


def test_adding_returns_the_new_state_and_creates_the_favorite_and_todays_event(client, fake):
    response = put(client, TERM, {"favorited": True})
    assert response.status_code == 200
    assert response.json() == {"term_id": TERM, "is_favorite": True}
    assert response.headers["cache-control"] == "private, no-store"
    assert (A, TERM) in fake.favorites
    assert (A, TERM, "2026-10-23") in fake.events


def test_event_is_written_before_the_favorite(client, fake):
    put(client, TERM, {"favorited": True})
    assert fake.writes == ["event", "favorite"]


def test_adding_again_changes_nothing_and_stays_200(client, fake):
    put(client, TERM, {"favorited": True})
    before = (set(fake.favorites), set(fake.events))
    again = put(client, TERM, {"favorited": True})
    assert again.status_code == 200
    assert again.json() == {"term_id": TERM, "is_favorite": True}
    assert (fake.favorites, fake.events) == before


def test_removing_returns_false_and_deletes_only_the_favorite(client, fake):
    put(client, TERM, {"favorited": True})
    response = put(client, TERM, {"favorited": False})
    assert response.status_code == 200
    assert response.json() == {"term_id": TERM, "is_favorite": False}
    assert (A, TERM) not in fake.favorites
    # 해제해도 같은 날의 이력은 남는다(D-043).
    assert (A, TERM, "2026-10-23") in fake.events


def test_removing_something_that_is_not_a_favorite_is_still_200(client, fake):
    response = put(client, TERM, {"favorited": False})
    assert response.status_code == 200
    assert response.json() == {"term_id": TERM, "is_favorite": False}
    assert fake.events == {(B, OTHER_TERM, "2026-10-22")}  # 이력을 새로 만들지 않는다


def test_add_remove_add_on_the_same_day_leaves_one_event(client, fake):
    for favorited in (True, False, True):
        assert put(client, TERM, {"favorited": favorited}).status_code == 200
    assert (A, TERM) in fake.favorites
    assert {e for e in fake.events if e[0] == A} == {(A, TERM, "2026-10-23")}


def test_kst_midnight_starts_a_new_event_date(client, fake, monkeypatch):
    monkeypatch.setattr(session, "now", lambda: BEFORE_KST_MIDNIGHT + 0.5)
    put(client, TERM, {"favorited": True})
    put(client, TERM, {"favorited": False})
    monkeypatch.setattr(session, "now", lambda: BEFORE_KST_MIDNIGHT + 1)
    put(client, TERM, {"favorited": True})
    assert {e for e in fake.events if e[0] == A} == {(A, TERM, "2026-10-22"), (A, TERM, "2026-10-23")}


# --- 사용자 분리: 사용자 id는 세션에서만 꺼낸다 ---


def test_one_users_changes_do_not_touch_another_users_rows(client, fake):
    put(client, OTHER_TERM, {"favorited": True}, "a-token")
    put(client, OTHER_TERM, {"favorited": False}, "a-token")
    assert (B, OTHER_TERM) in fake.favorites
    assert (B, OTHER_TERM, "2026-10-22") in fake.events


def test_body_cannot_name_another_user(client, fake):
    response = put(client, TERM, {"favorited": True, "user_id": B})
    assert_error(response, 422, "validation_failed")
    assert (B, TERM) not in fake.favorites and (A, TERM) not in fake.favorites
    assert fake.writes == []


def test_each_user_has_their_own_state_for_the_same_term(client, fake):
    put(client, TERM, {"favorited": True}, "a-token")
    put(client, TERM, {"favorited": True}, "b-token")
    put(client, TERM, {"favorited": False}, "a-token")
    assert (A, TERM) not in fake.favorites and (B, TERM) in fake.favorites


# --- AC-2: 방문자 401, Origin 403, 거부되면 DB를 바꾸지 않는다 ---


@pytest.mark.parametrize("token", [None, "inactive-token", "unknown-token"])
def test_visitors_and_inactive_accounts_are_401_without_writes(client, fake, token):
    for favorited in (True, False):
        assert_error(put(client, TERM, {"favorited": favorited}, token), 401, "login_required")
    assert fake.writes == []
    assert fake.rpc_calls == []  # 속도 제한 카운터도 건드리지 않는다
    assert fake.events == {(B, OTHER_TERM, "2026-10-22")}


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Origin": "null"}])
def test_disallowed_or_missing_origin_is_403_without_writes(client, fake, headers):
    response = client.put(f"/api/favorites/{TERM}", json={"favorited": True}, headers={**cookie("a-token"), **headers})
    assert_error(response, 403, "origin_not_allowed")
    missing = client.put(f"/api/favorites/{TERM}", json={"favorited": True}, headers=cookie("a-token"))
    assert_error(missing, 403, "origin_not_allowed")
    assert fake.writes == [] and (A, TERM) not in fake.favorites


# --- 404: 없는 용어 ---


@pytest.mark.parametrize("favorited", [True, False])
def test_missing_term_is_404_for_both_directions(client, fake, favorited):
    assert_error(put(client, MISSING, {"favorited": favorited}), 404, "not_found")
    assert (A, MISSING) not in fake.favorites


def test_missing_term_adds_no_favorite_and_no_event(client, fake):
    put(client, MISSING, {"favorited": True})
    assert {e for e in fake.events if e[0] == A} == set()
    assert fake.favorites == {(B, OTHER_TERM)}


@pytest.mark.parametrize("term_id", ["abc", "0", "-1", "1.5", "007", "9223372036854775808", "99999999999999999999"])
def test_malformed_term_ids_are_404_without_db_calls_or_rate_count(client, fake, term_id):
    assert_error(put(client, term_id, {"favorited": True}), 404, "not_found")
    assert fake.writes == []
    assert fake.rpc_calls == []


# --- 422: 본문 ---


@pytest.mark.parametrize("body,name,reason", [
    ({}, "favorited", "required"),
    ({"favorited": "true"}, "favorited", "invalid_format"),
    ({"favorited": 1}, "favorited", "invalid_format"),
    ({"favorited": 0}, "favorited", "invalid_format"),
    ({"favorited": None}, "favorited", "invalid_format"),
    ({"favorited": []}, "favorited", "invalid_format"),
])
def test_malformed_body_is_422_without_writes(client, fake, body, name, reason):
    assert_field(put(client, TERM, body), name, reason)
    assert fake.writes == []
    assert (A, TERM) not in fake.favorites


def test_non_json_body_is_a_client_error_without_writes(client, fake):
    response = client.put(
        f"/api/favorites/{TERM}", content=b"not json", headers={**origin(), **cookie("a-token"), "Content-Type": "application/json"},
    )
    assert response.status_code in (400, 422)
    assert fake.writes == []


# --- 속도 제한: 그 밖의 쓰기, 사용자당 분당 30회 ---


def test_write_limit_is_counted_before_the_term_check_and_per_user(client, fake):
    for _ in range(WRITE.limit):
        assert put(client, MISSING, {"favorited": True}).status_code == 404
    over = put(client, TERM, {"favorited": True})
    assert_error(over, 429, "rate_limited")
    assert (A, TERM) not in fake.favorites  # 한도를 넘은 요청은 쓰기를 시도하지 않는다
    # 다른 사용자는 따로 센다.
    assert put(client, TERM, {"favorited": True}, "b-token").status_code == 200


# --- 중간 실패와 재시도 ---


def test_failure_after_the_event_is_503_and_a_retry_finishes_without_duplicates(client, fake):
    fake.favorites_write_down = True
    assert_error(put(client, TERM, {"favorited": True}), 503, "service_unavailable")
    # 이력만 남고 즐겨찾기는 없다. 해제해도 후보에 남는 규칙과 어긋나지 않는 상태다.
    assert (A, TERM) not in fake.favorites
    assert (A, TERM, "2026-10-23") in fake.events
    fake.favorites_write_down = False
    retry = put(client, TERM, {"favorited": True})
    assert retry.status_code == 200 and retry.json() == {"term_id": TERM, "is_favorite": True}
    assert (A, TERM) in fake.favorites
    assert {e for e in fake.events if e[0] == A} == {(A, TERM, "2026-10-23")}


def test_database_outage_is_503_for_both_directions(client, fake):
    # 가짜의 down은 인증도 막으므로, 세션 확인은 통과하고 즐겨찾기 쓰기만 실패하는 경우를 만든다.
    def broken(*args, **kwargs):
        raise SupabaseUnavailable("down")

    fake.favorite_term = broken
    fake.unfavorite_term = broken
    for favorited in (True, False):
        assert_error(put(client, TERM, {"favorited": favorited}), 503, "service_unavailable")


def test_database_misconfiguration_is_a_500_without_details(client, fake):
    def broken(*args, **kwargs):
        raise SupabaseConfigError("favorites insert status 401 secret-detail")

    fake.favorite_term = broken
    response = put(client, TERM, {"favorited": True})
    assert_error(response, 500, "internal_error")
    assert "secret-detail" not in response.text
