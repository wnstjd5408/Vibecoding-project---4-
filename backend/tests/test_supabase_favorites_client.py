"""즐겨찾기(MEG-89) Supabase 래퍼의 HTTP 모양. 실제 요청 주소·필터·헤더·본문과 오류 판정을 고정한다. 네트워크 없이 돈다.

같은 호출은 실제 로컬 Supabase에서도 확인한다(docs/backend-local-guide.md 8절). 여기서는 그 모양이 바뀌지 않게 지킨다.
"""

import json

import httpx
import pytest

from app.supabase import SupabaseClient, SupabaseConfigError, SupabaseUnavailable

USER_ID = "00000000-0000-0000-0000-00000000000a"
PREFER = "resolution=ignore-duplicates,return=minimal"
EVENT_TERM_FK = {
    "code": "23503",
    "message": 'insert or update on table "favorite_events" violates foreign key constraint "favorite_events_term_id_fkey"',
}
FAVORITE_TERM_FK = {
    "code": "23503",
    "message": 'insert or update on table "favorites" violates foreign key constraint "favorites_term_id_fkey"',
}
USER_FK = {
    "code": "23503",
    "message": 'insert or update on table "favorite_events" violates foreign key constraint "favorite_events_user_id_fkey"',
}


def recording_client(responses):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[len(seen) - 1]

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SupabaseClient("https://project.supabase.co/", "sb_secret_test", http), seen


def test_favorite_writes_the_event_first_then_the_favorite_ignoring_duplicates():
    client, seen = recording_client([httpx.Response(201), httpx.Response(201)])
    assert client.favorite_term(USER_ID, 7, "2026-11-03") is True
    assert [r.url.path for r in seen] == ["/rest/v1/favorite_events", "/rest/v1/favorites"]
    assert all(r.method == "POST" and r.headers["prefer"] == PREFER for r in seen)
    assert json.loads(seen[0].content) == {"user_id": USER_ID, "term_id": 7, "study_date": "2026-11-03"}
    assert json.loads(seen[1].content) == {"user_id": USER_ID, "term_id": 7}


@pytest.mark.parametrize("status", [200, 201, 204])
def test_favorite_accepts_any_success_status_for_both_writes(status):
    client, seen = recording_client([httpx.Response(status), httpx.Response(status)])
    assert client.favorite_term(USER_ID, 7, "2026-11-03") is True
    assert len(seen) == 2


@pytest.mark.parametrize("fk,calls", [(EVENT_TERM_FK, 1), (FAVORITE_TERM_FK, 2)])
def test_favorite_missing_term_foreign_key_is_false_and_stops(fk, calls):
    first = httpx.Response(409, json=fk) if calls == 1 else httpx.Response(201)
    responses = [first] if calls == 1 else [first, httpx.Response(409, json=fk)]
    client, seen = recording_client(responses)
    assert client.favorite_term(USER_ID, 99, "2026-11-03") is False
    assert len(seen) == calls  # 이력 쪽에서 막히면 favorites는 시도하지 않는다


@pytest.mark.parametrize("response", [
    httpx.Response(409, json=USER_FK),  # 사용자 쪽 외래 키는 용어 없음이 아니다
    httpx.Response(409, json={"code": "23503"}),
    httpx.Response(409, json={"code": "23505", "message": "duplicate key"}),
    httpx.Response(401, json={"message": "secret-detail"}),
    httpx.Response(403),
])
def test_favorite_other_rejections_are_configuration_errors_without_details(response):
    client, _ = recording_client([response])
    with pytest.raises(SupabaseConfigError) as error:
        client.favorite_term(USER_ID, 7, "2026-11-03")
    assert "secret-detail" not in str(error.value)


def test_favorite_failure_on_the_second_write_is_a_configuration_error():
    client, seen = recording_client([httpx.Response(201), httpx.Response(403)])
    with pytest.raises(SupabaseConfigError):
        client.favorite_term(USER_ID, 7, "2026-11-03")
    assert len(seen) == 2


def test_unfavorite_deletes_only_that_users_favorite_and_never_touches_events():
    client, seen = recording_client([httpx.Response(200, json=[{"term_id": 7}])])
    assert client.unfavorite_term(USER_ID, 7) is True
    request = seen[0]
    assert request.method == "DELETE" and request.url.path == "/rest/v1/favorites"
    assert dict(request.url.params) == {"user_id": f"eq.{USER_ID}", "term_id": "eq.7", "select": "term_id"}
    assert request.headers["prefer"] == "return=representation"
    assert len(seen) == 1  # 지운 행이 있으면 terms를 읽지 않는다
    assert all("favorite_events" not in r.url.path for r in seen)


def test_unfavorite_of_a_non_favorite_checks_that_the_term_exists():
    client, seen = recording_client([httpx.Response(200, json=[]), httpx.Response(200, json=[{"id": 7}])])
    assert client.unfavorite_term(USER_ID, 7) is True
    assert seen[1].url.path == "/rest/v1/terms"
    assert dict(seen[1].url.params) == {"id": "eq.7", "select": "id", "limit": "1"}


def test_unfavorite_of_a_missing_term_is_false():
    client, _ = recording_client([httpx.Response(200, json=[]), httpx.Response(200, json=[])])
    assert client.unfavorite_term(USER_ID, 99) is False


@pytest.mark.parametrize("responses", [
    [httpx.Response(401, json={"message": "secret-detail"})],
    [httpx.Response(200, json=[]), httpx.Response(403)],
])
def test_unfavorite_failures_are_configuration_errors_without_details(responses):
    client, _ = recording_client(responses)
    with pytest.raises(SupabaseConfigError) as error:
        client.unfavorite_term(USER_ID, 7)
    assert "secret-detail" not in str(error.value)


@pytest.mark.parametrize("responses", [[httpx.Response(500)], [httpx.Response(201), httpx.Response(503)]])
def test_server_errors_are_transient_unavailable_not_configuration_errors(responses):
    # 기존 래퍼 규칙: 5xx는 일시 장애(503)이고 401·403 같은 거절이 설정 오류(500)다.
    client, _ = recording_client(responses)
    with pytest.raises(SupabaseUnavailable):
        client.favorite_term(USER_ID, 7, "2026-11-03")


def test_network_failure_surfaces_as_unavailable():
    def handler(request):
        raise httpx.ConnectError("down")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = SupabaseClient("https://project.supabase.co/", "sb_secret_test", http)
    with pytest.raises(SupabaseUnavailable):
        client.favorite_term(USER_ID, 7, "2026-11-03")
    with pytest.raises(SupabaseUnavailable):
        client.unfavorite_term(USER_ID, 7)
