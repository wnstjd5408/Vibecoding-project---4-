"""E05 노트 읽기 (MEG-73). 가짜 Supabase로 네트워크 없이 돈다. 데이터는 모두 합성이다."""

import logging

import pytest
from fastapi.testclient import TestClient

from app import glossary_spans, session
from app.notes import SIGNED_URL_SECONDS
from app.rate_limit import PUBLIC_READ, SIGNED_URL
from scripts.notion_content import rich_text
from support import FakeSupabase, build_notes_app, cookie

MEMBER = "00000000-0000-0000-0000-00000000000a"
OPERATOR = "00000000-0000-0000-0000-00000000000b"
INACTIVE_OPERATOR = "00000000-0000-0000-0000-00000000000c"
PUBLIC_NOTE = 11
PRIVATE_NOTE = 13
NO_IMAGE_NOTE = 14
BODY = "이 노트는 ExampleTerm 을 설명합니다. UnknownWord 는 사전에 없습니다. ![그림](note-image:blk-1)"
# 2026-10-23T05:30:00Z
NOW = 1_792_733_400


@pytest.fixture
def fake(monkeypatch) -> FakeSupabase:
    fake = FakeSupabase()
    fake.add_user("member-token", MEMBER)
    fake.add_user("operator-token", OPERATOR, role="operator")
    fake.add_user("inactive-operator-token", INACTIVE_OPERATOR, role="operator", is_active=False)
    fake.subjects = [{"id": 1, "name": "네트워크"}, {"id": 2, "name": "AI"}]
    fake.add_note(
        PUBLIC_NOTE,
        "Example Note",
        "2026-10-14",
        [2, 1],
        revision=3,
        body_markdown=BODY,
        sources=[
            {"id": 9, "url": "https://example.test/second", "label": None},
            {"id": 5, "url": "https://example.test/doc", "label": "예시 문서"},
        ],
        images=[{"notion_block_id": "blk-1", "storage_path": "notes/11/blk-1.png", "alt": "그림"}],
    )
    fake.add_note(
        PRIVATE_NOTE,
        "Private Note",
        "2026-10-25",
        [1],
        is_published=False,
        body_markdown="비공개 ExampleTerm ![x](note-image:blk-9)",
        images=[{"notion_block_id": "blk-9", "storage_path": "notes/13/blk-9.png", "alt": None}],
    )
    fake.add_note(NO_IMAGE_NOTE, "No image", None, [], body_markdown="이미지 없는 노트")
    fake.add_glossary_term(7, "exampleterm", "ExampleTerm")
    fake.add_glossary_term(8, "notinbody", "NotInBody")
    fake.stored_images = {"notes/11/blk-1.png", "notes/13/blk-9.png"}
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(session, "now", lambda: NOW + 0.9)
    return fake


@pytest.fixture
def client(fake) -> TestClient:
    return TestClient(build_notes_app(fake))


def read(client, note_id, token: str | None = None, ip: str = "203.0.113.1"):
    headers = {"x-vercel-forwarded-for": ip, **(cookie(token) if token else {})}
    return client.get(f"/api/notes/{note_id}", headers=headers)


def assert_not_found(response):
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert set(response.json()["error"]) == {"code", "message", "request_id"}


# --- AC-1: 공개 노트는 본문·images·glossary_spans, 비공개 노트는 운영자가 아니면 404 ---


@pytest.mark.parametrize("token", [None, "member-token"])
def test_public_note_matches_spec_example_1(client, fake, token):
    response = read(client, PUBLIC_NOTE, token)

    assert response.status_code == 200
    assert response.json() == {
        "id": PUBLIC_NOTE,
        "revision": 3,
        "title": "Example Note",
        "studied_on": "2026-10-14",
        "subjects": [{"id": 1, "name": "네트워크"}, {"id": 2, "name": "AI"}],
        "sources": [
            {"url": "https://example.test/doc", "label": "예시 문서"},
            {"url": "https://example.test/second", "label": None},
        ],
        # 본문의 이미지 토큰은 바꾸지 않는다.
        "body_markdown": BODY,
        "images": {
            "blk-1": {
                "url": "https://storage.example.test/signed/notes/11/blk-1.png?token=EXAMPLE_ONLY",
                "alt": "그림",
                "expires_at": "2026-10-23T05:35:00Z",
            }
        },
        # 본문에 없는 사전 용어(8)는 넣지 않는다.
        "glossary_terms": [{"term_id": 7, "key": "exampleterm", "label": "ExampleTerm"}],
        "glossary_spans": [{"term_id": 7, "start": 6, "end": 17}],
    }
    # 비공개 노트는 DB에서부터 거른다. 서명 URL은 5분짜리로 한 번에 받는다.
    assert fake.note_reads == [(PUBLIC_NOTE, False)]
    assert fake.sign_calls == [(["notes/11/blk-1.png"], SIGNED_URL_SECONDS)]


@pytest.mark.parametrize("token", [None, "member-token", "inactive-operator-token"])
def test_private_note_is_404_for_non_operators_and_signs_nothing(client, fake, token):
    response = read(client, PRIVATE_NOTE, token)

    assert_not_found(response)
    assert fake.note_reads == [(PRIVATE_NOTE, False)]
    assert fake.sign_calls == []


def test_private_and_missing_notes_look_the_same(client):
    private = read(client, PRIVATE_NOTE)
    missing = read(client, 999)

    assert private.status_code == missing.status_code == 404
    assert private.json()["error"]["message"] == missing.json()["error"]["message"]


def test_operator_reads_private_note_with_the_same_shape(client, fake):
    response = read(client, PRIVATE_NOTE, "operator-token")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "id",
        "revision",
        "title",
        "studied_on",
        "subjects",
        "sources",
        "body_markdown",
        "images",
        "glossary_terms",
        "glossary_spans",
    }
    assert body["images"]["blk-9"]["alt"] is None
    assert body["glossary_spans"] == [{"term_id": 7, "start": 4, "end": 15}]
    assert fake.note_reads == [(PRIVATE_NOTE, True)]


def test_note_without_images_does_not_sign_or_count(client, fake):
    response = read(client, NO_IMAGE_NOTE)

    assert response.status_code == 200
    assert response.json()["images"] == {}
    assert response.json()["glossary_terms"] == response.json()["glossary_spans"] == []
    assert response.json()["studied_on"] is None
    assert fake.sign_calls == []
    assert fake.hits(f"signed_url:{fake.keyed_hash('ip:203.0.113.1')}", SIGNED_URL.window_seconds) == 0


@pytest.mark.parametrize("note_id", ["abc", "0", "-1", "1.5", "011", str(2**63), "9" * 30])
def test_malformed_note_id_is_404_without_db_or_counting(client, fake, note_id):
    assert_not_found(read(client, note_id))
    assert fake.note_reads == []
    assert fake.rpc_calls == []


def test_largest_bigint_id_is_looked_up(client, fake):
    assert_not_found(read(client, 2**63 - 1))
    assert fake.note_reads == [(2**63 - 1, False)]


# --- 이미지 서명 ---


def test_missing_storage_object_is_left_out_and_logged(client, fake, caplog):
    fake.notes[0]["images"].append({"notion_block_id": "blk-2", "storage_path": "notes/11/gone.png", "alt": None})

    with caplog.at_level(logging.WARNING, logger="app.notes"):
        response = read(client, PUBLIC_NOTE)

    assert response.status_code == 200
    assert set(response.json()["images"]) == {"blk-1"}
    assert response.json()["body_markdown"] == BODY
    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        ("WARNING", "stage=storage note_id=11 unsigned_images=1 of 2")
    ]
    # 로그에 저장 경로를 남기지 않는다.
    assert "gone.png" not in caplog.text


def test_no_image_signed_at_all_is_logged_as_error(client, fake, caplog):
    # 버킷 이름이 틀려도 Storage는 파일 누락과 같은 응답을 준다. 노트는 주되 ERROR로 남긴다.
    fake.stored_images.clear()

    with caplog.at_level(logging.WARNING, logger="app.notes"):
        response = read(client, PUBLIC_NOTE)

    assert response.status_code == 200
    assert response.json()["images"] == {}
    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        ("ERROR", "stage=storage note_id=11 unsigned_images=1 of 1")
    ]


def test_storage_outage_is_503(client, fake):
    fake.storage_down = True

    response = read(client, PUBLIC_NOTE)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_db_outage_is_503(client, fake):
    fake.down = True

    response = read(client, PUBLIC_NOTE)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_images_sharing_one_storage_path_are_signed_once(client, fake):
    fake.notes[0]["images"].append({"notion_block_id": "blk-2", "storage_path": "notes/11/blk-1.png", "alt": None})

    response = read(client, PUBLIC_NOTE)

    assert set(response.json()["images"]) == {"blk-1", "blk-2"}
    assert fake.sign_calls == [(["notes/11/blk-1.png"], SIGNED_URL_SECONDS)]


# --- 속도 제한·공통 계층 ---


def test_public_read_limit_is_per_ip_and_counted_before_the_db(client, fake):
    for _ in range(PUBLIC_READ.limit):
        assert read(client, 999).status_code == 404

    blocked = read(client, PUBLIC_NOTE)

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1
    assert len(fake.note_reads) == PUBLIC_READ.limit
    assert read(client, PUBLIC_NOTE, ip="203.0.113.2").status_code == 200


def test_signed_url_limit_is_per_user_and_counts_one_per_note_open(client, fake):
    fake.notes[0]["images"].append({"notion_block_id": "blk-2", "storage_path": "notes/11/blk-2.png", "alt": None})
    for _ in range(SIGNED_URL.limit):
        assert read(client, PUBLIC_NOTE, "member-token").status_code == 200

    blocked = read(client, PUBLIC_NOTE, "member-token")
    visitor_same_ip = read(client, PUBLIC_NOTE)

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    # 막힌 요청은 서명을 부르지 않는다. 같은 IP라도 방문자는 IP 칸을 따로 쓴다.
    assert len(fake.sign_calls) == SIGNED_URL.limit + 1
    assert visitor_same_ip.status_code == 200
    assert fake.hits(f"signed_url:{fake.keyed_hash(f'user:{MEMBER}')}", SIGNED_URL.window_seconds) == (
        SIGNED_URL.limit + 1
    )


def test_response_is_not_cacheable(client):
    response = read(client, PUBLIC_NOTE)

    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Request-Id"]


def test_missing_bucket_setting_is_500_internal_error(client, fake):
    fake.bucket_configured = False

    response = read(client, PUBLIC_NOTE)

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    # 이미지가 없는 노트는 버킷 설정과 상관없이 읽힌다.
    assert read(client, NO_IMAGE_NOTE).status_code == 200


def test_visitor_signed_url_limit_uses_the_ip_key(client, fake):
    read(client, PUBLIC_NOTE)

    assert fake.hits(f"signed_url:{fake.keyed_hash('ip:203.0.113.1')}", SIGNED_URL.window_seconds) == 1


def test_signed_url_limit_stops_before_glossary_query_and_signing(client, fake):
    for _ in range(SIGNED_URL.limit):
        read(client, PUBLIC_NOTE)
    reads, signs = fake.glossary_reads, len(fake.sign_calls)

    assert read(client, PUBLIC_NOTE).status_code == 429
    assert (fake.glossary_reads, len(fake.sign_calls)) == (reads, signs)


def test_emoji_body_spans_cut_back_to_terms_over_http(client, fake):
    # 이모지 뒤 위치도 코드포인트 기준이다. 화면은 이 값을 UTF-16으로 바꾼다(frontend/src/notes/spans.ts).
    body = "😀👍🏽 해시테이블과 HashTable, TCP/IP 🚀 ExampleTerm"
    fake.add_note(15, "Emoji", None, [], body_markdown=body)
    fake.add_glossary_term(9, "해시테이블", "해시테이블")
    fake.add_glossary_term(10, "hashtable", "HashTable")
    fake.add_glossary_term(11, "tcp/ip", "TCP/IP")

    result = read(client, 15).json()

    assert [(s["term_id"], body[s["start"] : s["end"]]) for s in result["glossary_spans"]] == [
        (9, "해시테이블"),
        (10, "HashTable"),
        (11, "TCP/IP"),
        (7, "ExampleTerm"),
    ]
    assert [t["term_id"] for t in result["glossary_terms"]] == [7, 9, 10, 11]


def test_glossary_at_the_row_cap_is_logged(client, fake, caplog):
    fake.glossary = [{"id": i, "key": f"k{i}", "label": f"K{i}"} for i in range(1000)]

    with caplog.at_level(logging.WARNING, logger="app.notes"):
        assert read(client, NO_IMAGE_NOTE).status_code == 200

    assert "stage=db glossary_terms=1000 reached row cap" in caplog.text


@pytest.mark.parametrize("term", ["A*", "__init__", "std::vector<T>"])
def test_terms_escaped_by_the_notion_import_get_spans_over_http(client, fake, term):
    # 실제 가져오기 변환(scripts/notion_content.py)으로 만든 본문. 특수문자가 백슬래시로 이스케이프된다.
    body = rich_text([{"plain_text": f"설명: {term} 끝"}])
    assert body != f"설명: {term} 끝"
    fake.add_note(16, "Escaped", None, [], body_markdown=body)
    fake.add_glossary_term(30, term.lower(), term)

    result = read(client, 16).json()

    assert result["body_markdown"] == body
    assert [t["term_id"] for t in result["glossary_terms"]] == [30]
    [span] = result["glossary_spans"]
    # 원문 구간은 이스케이프 백슬래시를 포함하고, 이스케이프를 풀면 용어 글자다.
    assert glossary_spans._ESCAPE.sub(r"\1", body[span["start"] : span["end"]]) == term
