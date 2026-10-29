"""E04 과목·노트 목록 (MEG-71). 가짜 Supabase로 네트워크 없이 돈다."""

import pytest
from fastapi.testclient import TestClient

from app.rate_limit import PUBLIC_READ
from support import FakeSupabase, build_notes_app, cookie

MEMBER = "00000000-0000-0000-0000-00000000000a"
OPERATOR = "00000000-0000-0000-0000-00000000000b"
INACTIVE_OPERATOR = "00000000-0000-0000-0000-00000000000c"
OPERATOR_FIELDS = {"is_published", "revision", "needs_review"}
PRIVATE_NOTE = 13
PRIVATE_ONLY_SUBJECT = 3


@pytest.fixture
def fake(monkeypatch) -> FakeSupabase:
    fake = FakeSupabase()
    fake.add_user("member-token", MEMBER)
    fake.add_user("operator-token", OPERATOR, role="operator")
    fake.add_user("inactive-operator-token", INACTIVE_OPERATOR, role="operator", is_active=False)
    fake.subjects = [{"id": 1, "name": "네트워크"}, {"id": 2, "name": "AI"}, {"id": 3, "name": "보안"}, {"id": 4, "name": "프론트"}]
    # 합성 데이터: 공개 2·비공개 1. 공개 노트 12의 상위 노트는 비공개 노트 13이다.
    fake.add_note(11, "Public A", "2026-10-14", [1])
    fake.add_note(12, "Public B", "2026-10-20", [1, 2], parent_note_id=PRIVATE_NOTE, revision=2)
    fake.add_note(PRIVATE_NOTE, "Private C", "2026-10-25", [PRIVATE_ONLY_SUBJECT], is_published=False, needs_review=True)
    monkeypatch.setenv("VERCEL", "1")
    return fake


@pytest.fixture
def client(fake) -> TestClient:
    return TestClient(build_notes_app(fake))


def get_notes(client, token: str | None = None, query: str = "", ip: str = "203.0.113.1"):
    headers = {"x-vercel-forwarded-for": ip, **(cookie(token) if token else {})}
    return client.get(f"/api/notes{query}", headers=headers)


# --- AC-1: 방문자·일반 사용자에게는 공개 노트만, 과목별 수도 공개 노트만 ---


@pytest.mark.parametrize("token", [None, "member-token"])
def test_non_operator_sees_only_published_notes_and_counts(client, fake, token):
    response = get_notes(client, token)

    assert response.status_code == 200
    assert response.json() == {
        # 비공개 노트만 있는 과목(보안)과 노트가 없는 과목(프론트)은 빠진다.
        "subjects": [{"id": 1, "name": "네트워크", "note_count": 2}, {"id": 2, "name": "AI", "note_count": 1}],
        "notes": [
            {
                "id": 12,
                "title": "Public B",
                "studied_on": "2026-10-20",
                "subjects": [{"id": 1, "name": "네트워크"}, {"id": 2, "name": "AI"}],
                # 상위 노트가 비공개라 id를 숨긴다.
                "parent_note_id": None,
            },
            {
                "id": 11,
                "title": "Public A",
                "studied_on": "2026-10-14",
                "subjects": [{"id": 1, "name": "네트워크"}],
                "parent_note_id": None,
            },
        ],
    }
    # 비공개 노트는 DB에서부터 읽지 않는다.
    assert fake.note_queries == [False]


def test_inactive_operator_is_treated_as_a_visitor(client, fake):
    body = get_notes(client, "inactive-operator-token").json()

    assert [note["id"] for note in body["notes"]] == [12, 11]
    assert all(not OPERATOR_FIELDS & note.keys() for note in body["notes"])
    assert fake.note_queries == [False]


def test_private_only_subject_filter_is_empty_for_non_operator(client):
    # 과목이 있어도 공개 노트가 없으면 404가 아니라 빈 목록이다. 비공개 노트 유무가 새지 않는다.
    response = get_notes(client, "member-token", f"?subject_id={PRIVATE_ONLY_SUBJECT}")

    assert response.status_code == 200
    assert response.json()["notes"] == []


def test_public_parent_is_kept(client, fake):
    fake.add_note(14, "Public D", "2026-10-15", [2], parent_note_id=11)

    notes = {note["id"]: note for note in get_notes(client).json()["notes"]}

    assert notes[14]["parent_note_id"] == 11


# --- AC-2: 운영자에게는 비공개 노트와 운영자 열까지 ---


def test_operator_sees_all_notes_with_operator_fields(client, fake):
    response = get_notes(client, "operator-token")

    assert response.status_code == 200
    body = response.json()
    # 운영자에게는 노트가 0개인 과목도 보인다. 수는 비공개 노트까지 센다.
    assert body["subjects"] == [
        {"id": 1, "name": "네트워크", "note_count": 2},
        {"id": 2, "name": "AI", "note_count": 1},
        {"id": 3, "name": "보안", "note_count": 1},
        {"id": 4, "name": "프론트", "note_count": 0},
    ]
    assert [note["id"] for note in body["notes"]] == [PRIVATE_NOTE, 12, 11]
    by_id = {note["id"]: note for note in body["notes"]}
    assert by_id[PRIVATE_NOTE] == {
        "id": PRIVATE_NOTE,
        "title": "Private C",
        "studied_on": "2026-10-25",
        "subjects": [{"id": 3, "name": "보안"}],
        "parent_note_id": None,
        "is_published": False,
        "revision": 1,
        "needs_review": True,
    }
    assert by_id[12]["parent_note_id"] == PRIVATE_NOTE
    assert (by_id[12]["is_published"], by_id[12]["revision"], by_id[12]["needs_review"]) == (True, 2, False)
    assert fake.note_queries == [True]


# --- 거르기·정렬 ---


def test_subject_filter_narrows_notes_but_not_subjects(client):
    full = get_notes(client).json()
    filtered = get_notes(client, query="?subject_id=2").json()

    assert [note["id"] for note in filtered["notes"]] == [12]
    # 과목 목록과 수는 거르기와 상관없이 같다. 화면이 과목 탭을 그대로 그린다.
    assert filtered["subjects"] == full["subjects"]


def test_unknown_subject_is_empty_not_an_error(client):
    response = get_notes(client, query="?subject_id=999")

    assert response.status_code == 200
    assert response.json()["notes"] == []


def test_notes_are_ordered_by_studied_on_desc_then_id_desc_with_missing_dates_last(client, fake):
    fake.add_note(20, "No date", None, [1])
    fake.add_note(21, "Same day low id", "2026-10-14", [1])
    fake.add_note(30, "Same day high id", "2026-10-14", [1])

    ids = [note["id"] for note in get_notes(client).json()["notes"]]

    assert ids == [12, 30, 21, 11, 20]


# --- 형식 오류·속도 제한·공통 계층 ---


@pytest.mark.parametrize("value", ["abc", "0", "-1", "1.5", str(2**63)])
def test_invalid_subject_id_is_422_and_not_counted(client, fake, value):
    response = get_notes(client, query=f"?subject_id={value}")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert [field["name"] for field in error["fields"]] == ["subject_id"]
    # 형식 검사(4번)가 속도 제한(6번)보다 앞이다. DB도 부르지 않는다.
    assert fake.rpc_calls == []
    assert fake.note_queries == []


def test_public_read_limit_is_per_ip_regardless_of_login(client, fake):
    for i in range(PUBLIC_READ.limit):
        # 같은 IP면 방문자와 로그인 사용자가 한 칸을 같이 쓴다.
        assert get_notes(client, "member-token" if i % 2 else None).status_code == 200

    blocked = get_notes(client, "operator-token")
    other_ip = get_notes(client, ip="203.0.113.2")

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1
    assert other_ip.status_code == 200
    assert fake.hits(f"public_read:{fake.keyed_hash('ip:203.0.113.1')}", PUBLIC_READ.window_seconds) == (
        PUBLIC_READ.limit + 1
    )


def test_response_is_not_cacheable(client):
    response = get_notes(client)

    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Request-Id"]


def test_db_outage_is_503(client, fake):
    fake.down = True

    response = get_notes(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
