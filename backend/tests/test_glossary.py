"""E06 사전 용어 읽기, E07 열람 기록 (MEG-75). 가짜 Supabase로 네트워크 없이 돈다. 데이터는 모두 합성이다."""

import json

import pytest
from fastapi.testclient import TestClient

from app import session
from app.rate_limit import PUBLIC_READ, WRITE
from support import FakeSupabase, build_glossary_app, cookie, origin

MEMBER = "00000000-0000-0000-0000-00000000000a"
OTHER = "00000000-0000-0000-0000-00000000000b"
INACTIVE = "00000000-0000-0000-0000-00000000000c"
GLOSSARY_TERM = 7
NO_IMAGE_TERM = 8
AI_TERM = 9
MISSING_TERM = 99
# 2026-10-23T05:30:00Z = 2026-10-23 14:30 KST
NOW = 1_792_733_400
# 2026-10-22T14:59:59Z = 2026-10-22 23:59:59 KST, 1초 뒤가 KST 자정이다.
BEFORE_KST_MIDNIGHT = 1_792_681_199


@pytest.fixture
def fake(monkeypatch) -> FakeSupabase:
    fake = FakeSupabase()
    fake.add_user("member-token", MEMBER)
    fake.add_user("other-token", OTHER)
    fake.add_user("inactive-token", INACTIVE, is_active=False)
    fake.add_glossary_term(
        GLOSSARY_TERM,
        "exampleterm",
        "ExampleTerm",
        body_markdown="합성 설명 문장입니다.",
        images=[
            {"id": 5, "storage_path": "terms/7/b.png", "alt": None},
            {"id": 3, "storage_path": "terms/7/a.png", "alt": "합성 구조도"},
        ],
    )
    fake.add_glossary_term(NO_IMAGE_TERM, "noimage", "NoImage", body_markdown="이미지 없는 설명")
    fake.ai_terms = {AI_TERM}
    fake.favorites = {(MEMBER, GLOSSARY_TERM), (OTHER, NO_IMAGE_TERM)}
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(session, "now", lambda: NOW + 0.9)
    return fake


@pytest.fixture
def client(fake) -> TestClient:
    return TestClient(build_glossary_app(fake))


def read(client, term_id, token: str | None = None, ip: str = "203.0.113.1"):
    headers = {"x-vercel-forwarded-for": ip, **(cookie(token) if token else {})}
    return client.get(f"/api/glossary/{term_id}", headers=headers)


def view(client, body, token: str | None = None, headers: dict | None = None):
    sent = {**origin(), **(cookie(token) if token else {}), **(headers or {})}
    return client.post("/api/term-views", json=body, headers=sent)


def assert_error(response, status: int, code: str):
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


# --- AC-1: E06이 사전 용어의 설명을 준다 ---


def test_visitor_gets_term_body_and_public_image_urls_without_favorite_key(client):
    response = read(client, GLOSSARY_TERM)

    assert response.status_code == 200
    assert response.json() == {
        "term": {"id": 7, "key": "exampleterm", "label": "ExampleTerm"},
        "body_markdown": "합성 설명 문장입니다.",
        "images": [
            {"id": 3, "url": "https://storage.example.test/public/glossary/terms/7/a.png", "alt": "합성 구조도"},
            {"id": 5, "url": "https://storage.example.test/public/glossary/terms/7/b.png", "alt": ""},
        ],
    }
    assert response.headers["cache-control"] == "private, no-store"


def test_response_has_no_storage_path_field(client):
    # 경로는 공개 주소 안에만 들어간다(1.9 예외, 2026-11-02 결정). 따로 된 필드는 없다.
    payload = read(client, GLOSSARY_TERM, "member-token").json()
    assert all(set(image) == {"id", "url", "alt"} for image in payload["images"])
    assert "storage_path" not in json.dumps(payload)


def test_member_sees_only_their_own_favorite_state(client):
    assert read(client, GLOSSARY_TERM, "member-token").json()["is_favorite"] is True
    assert read(client, NO_IMAGE_TERM, "member-token").json()["is_favorite"] is False
    # 다른 사용자의 즐겨찾기(OTHER, 8)는 MEMBER 응답에 영향을 주지 않는다.
    assert read(client, GLOSSARY_TERM, "other-token").json()["is_favorite"] is False
    assert read(client, NO_IMAGE_TERM, "other-token").json()["is_favorite"] is True


def test_inactive_account_is_read_as_a_visitor(client):
    response = read(client, GLOSSARY_TERM, "inactive-token")
    assert response.status_code == 200
    assert "is_favorite" not in response.json()


def test_term_without_images_has_an_empty_list(client):
    assert read(client, NO_IMAGE_TERM).json()["images"] == []


@pytest.mark.parametrize("term_id", [AI_TERM, MISSING_TERM])
def test_ai_only_and_missing_terms_are_the_same_404(client, term_id):
    response = read(client, term_id, "member-token")
    assert_error(response, 404, "not_found")
    assert set(response.json()["error"]) == {"code", "message", "request_id"}


@pytest.mark.parametrize("term_id", ["0", "007", "-1", "1.0", "abc", str(2**63), "9" * 20])
def test_malformed_ids_are_404_without_db_read_or_rate_count(client, fake, term_id):
    assert_error(read(client, term_id), 404, "not_found")
    assert fake.term_reads == []
    assert fake.rpc_calls == []


def test_get_does_not_record_a_view(client, fake):
    read(client, GLOSSARY_TERM, "member-token")
    assert fake.term_views == set()


def test_public_read_limit_counts_before_the_db_read(client, fake):
    key = f"{PUBLIC_READ.name}:{fake.keyed_hash('ip:203.0.113.1')}"
    for _ in range(PUBLIC_READ.limit):
        assert read(client, MISSING_TERM).status_code == 404
    assert fake.hits(key, PUBLIC_READ.window_seconds) == PUBLIC_READ.limit
    reads = len(fake.term_reads)

    response = read(client, GLOSSARY_TERM)
    assert_error(response, 429, "rate_limited")
    assert int(response.headers["retry-after"]) >= 1
    # 한도를 넘은 요청은 DB를 읽지 않는다.
    assert len(fake.term_reads) == reads


def test_missing_image_bucket_setting_is_500_only_for_terms_with_images(client, fake):
    fake.glossary_bucket_configured = False
    assert_error(read(client, GLOSSARY_TERM), 500, "internal_error")
    assert read(client, NO_IMAGE_TERM).status_code == 200


def test_database_outage_is_503(client, fake):
    fake.down = True
    assert_error(read(client, GLOSSARY_TERM), 503, "service_unavailable")


# --- AC-2: 로그인 사용자의 E07은 recorded: true, 같은 날 두 번 불러도 한 행, 방문자는 recorded: false ---


def test_member_view_is_recorded_once_per_kst_day(client, fake):
    first = view(client, {"term_id": GLOSSARY_TERM}, "member-token")
    second = view(client, {"term_id": GLOSSARY_TERM}, "member-token")

    assert first.status_code == 200 and first.json() == {"recorded": True}
    assert second.status_code == 200 and second.json() == {"recorded": True}
    assert fake.term_views == {(MEMBER, GLOSSARY_TERM, "2026-10-23")}


def test_kst_midnight_starts_a_new_study_date(client, fake, monkeypatch):
    monkeypatch.setattr(session, "now", lambda: BEFORE_KST_MIDNIGHT + 0.5)
    view(client, {"term_id": GLOSSARY_TERM}, "member-token")
    monkeypatch.setattr(session, "now", lambda: BEFORE_KST_MIDNIGHT + 1)
    view(client, {"term_id": GLOSSARY_TERM}, "member-token")

    assert fake.term_views == {(MEMBER, GLOSSARY_TERM, "2026-10-22"), (MEMBER, GLOSSARY_TERM, "2026-10-23")}


def test_ai_only_term_view_is_recorded(client, fake):
    assert view(client, {"term_id": AI_TERM}, "member-token").json() == {"recorded": True}
    assert fake.term_views == {(MEMBER, AI_TERM, "2026-10-23")}


@pytest.mark.parametrize("token", [None, "inactive-token", "unknown-token"])
def test_visitor_view_is_not_recorded_and_touches_no_table(client, fake, token):
    response = view(client, {"term_id": MISSING_TERM}, token)

    assert response.status_code == 200
    assert response.json() == {"recorded": False}
    assert fake.term_views == set()
    # 방문자는 용어 확인·속도 제한도 하지 않는다(2026-11-02 결정).
    assert fake.term_reads == []
    assert fake.rpc_calls == []


def test_missing_term_is_404_and_not_rate_counted(client, fake):
    assert_error(view(client, {"term_id": MISSING_TERM}, "member-token"), 404, "not_found")
    assert fake.term_views == set()
    assert fake.rpc_calls == []


def test_term_deleted_between_check_and_insert_is_404(client, fake):
    fake.term_deleted_before_insert = True
    assert_error(view(client, {"term_id": GLOSSARY_TERM}, "member-token"), 404, "not_found")


@pytest.mark.parametrize(
    "body, reason",
    [
        ({}, "required"),
        ({"term_id": "7"}, "invalid_format"),
        ({"term_id": True}, "invalid_format"),
        ({"term_id": 7.0}, "invalid_format"),
        ({"term_id": None}, "invalid_format"),
        ({"term_id": 0}, "out_of_range"),
        ({"term_id": 2**63}, "out_of_range"),
    ],
)
@pytest.mark.parametrize("token", [None, "member-token"])
def test_malformed_body_is_422_for_visitors_and_members(client, fake, body, reason, token):
    response = view(client, body, token)

    assert_error(response, 422, "validation_failed")
    assert response.json()["error"]["fields"] == [
        {"name": "term_id", "reason": reason, "message": response.json()["error"]["fields"][0]["message"]}
    ]
    assert fake.term_views == set()


def test_unknown_body_key_is_422_without_echoing_the_key(client):
    response = view(client, {"term_id": GLOSSARY_TERM, "user_id": OTHER}, "member-token")
    assert_error(response, 422, "validation_failed")
    assert "user_id" not in response.text


def test_post_without_allowed_origin_is_rejected(client, fake):
    response = client.post("/api/term-views", json={"term_id": GLOSSARY_TERM}, headers=cookie("member-token"))
    assert_error(response, 403, "origin_not_allowed")
    response = view(client, {"term_id": GLOSSARY_TERM}, "member-token", {"Origin": "https://evil.example"})
    assert_error(response, 403, "origin_not_allowed")
    assert fake.term_views == set()


def test_write_limit_is_per_user(client, fake):
    for _ in range(WRITE.limit):
        assert view(client, {"term_id": GLOSSARY_TERM}, "member-token").status_code == 200

    assert_error(view(client, {"term_id": GLOSSARY_TERM}, "member-token"), 429, "rate_limited")
    # 다른 사용자는 따로 센다.
    assert view(client, {"term_id": GLOSSARY_TERM}, "other-token").json() == {"recorded": True}


def test_view_database_outage_is_503(client, fake):
    fake.down = True
    # 세션 확인부터 DB·Auth가 막히면 503이다(방문자로 낮추지 않는다).
    assert_error(view(client, {"term_id": GLOSSARY_TERM}, "member-token"), 503, "service_unavailable")
