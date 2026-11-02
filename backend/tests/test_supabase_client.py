import httpx
import pytest

from app.supabase import Profile, SupabaseClient, SupabaseConfigError, SupabaseUnavailable

USER_ID = "00000000-0000-0000-0000-00000000000a"
# 구조만 맞춘 가짜 값(base64url 세 구간). 실제 JWT처럼 보이는 값은 비밀 검사기가 오탐하므로 쓰지 않는다.
JWT = "header-part.payload-part.signature_part"


def client_with(handler) -> SupabaseClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SupabaseClient("https://project.supabase.co/", "sb_secret_test", http)


def test_auth_user_check_uses_the_session_token_not_the_secret_key_as_bearer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["authorization"]
        seen["apikey"] = request.headers["apikey"]
        return httpx.Response(200, json={"id": USER_ID})

    assert client_with(handler).get_auth_user_id(JWT) == USER_ID
    assert seen == {
        "url": "https://project.supabase.co/auth/v1/user",
        "authorization": f"Bearer {JWT}",
        "apikey": "sb_secret_test",
    }


# Auth 서버의 거절에는 error_code가 있다(2026-10-29 로컬 Auth로 확인한 값).
@pytest.mark.parametrize("status, code", [(403, "bad_jwt"), (403, "session_not_found"), (401, "no_authorization")])
def test_rejected_token_is_no_user(status, code):
    body = {"code": status, "error_code": code, "msg": "rejected"}
    assert client_with(lambda r: httpx.Response(status, json=body)).get_auth_user_id(JWT) is None


# 게이트웨이가 API 키를 거절하면 error_code 없이 401이 온다(staging으로 확인한 모양).
INVALID_KEY = {"message": "Invalid API key", "hint": "Double check your API key."}


def test_invalid_api_key_on_user_check_is_a_config_error_not_a_logged_out_user():
    # 사용자 거절로 보면 키가 틀렸을 때 모든 사용자의 세션 쿠키가 지워진다.
    with pytest.raises(SupabaseConfigError):
        client_with(lambda r: httpx.Response(401, json=INVALID_KEY)).get_auth_user_id(JWT)


def test_malformed_auth_body_is_no_user():
    assert client_with(lambda r: httpx.Response(200, json={"id": "not-a-uuid"})).get_auth_user_id(JWT) is None


def test_auth_server_error_is_unavailable():
    with pytest.raises(SupabaseUnavailable):
        client_with(lambda r: httpx.Response(503)).get_auth_user_id(JWT)


def test_network_failure_is_unavailable_without_cause_text():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect to secret-host timed out")

    with pytest.raises(SupabaseUnavailable) as info:
        client_with(handler).get_auth_user_id(JWT)

    assert "secret-host" not in str(info.value)


def test_profile_lookup_filters_by_user_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=[{"role": "operator", "is_active": True, "display_name": "Ops"}])

    assert client_with(handler).get_profile(USER_ID) == Profile(role="operator", is_active=True, display_name="Ops")
    assert seen["params"] == {"user_id": f"eq.{USER_ID}", "select": "role,is_active,display_name", "limit": "1"}


def test_profile_without_display_name_is_none_name():
    profile = client_with(lambda r: httpx.Response(200, json=[{"role": "member", "is_active": True, "display_name": None}]))
    assert profile.get_profile(USER_ID).display_name is None


def test_missing_profile_row_is_none():
    assert client_with(lambda r: httpx.Response(200, json=[])).get_profile(USER_ID) is None


def test_profile_lookup_rejects_non_uuid_ids():
    with pytest.raises(ValueError):
        client_with(lambda r: httpx.Response(200, json=[])).get_profile("1&select=*")


def test_denied_key_is_a_config_error():
    with pytest.raises(SupabaseConfigError):
        client_with(lambda r: httpx.Response(401, json={})).get_profile(USER_ID)


def test_from_env_requires_both_variables(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")

    with pytest.raises(SupabaseConfigError):
        SupabaseClient.from_env()


# 토큰 모양: 요청을 보내기 전에 걸러 낸다(비ASCII는 헤더를 만들 수 없어 예외가 된다)
@pytest.mark.parametrize(
    "token",
    ["abc", "a.b", "a.b.c.d", "..", "a..c", "éabc.b.c", "abc def", "abc\r\nX-Injected: 1", "", "a" * 4097, "토큰", "abc\x00", "abc;def", 'abc"'],
)
def test_malformed_token_is_no_user_and_sends_no_request(token):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": USER_ID})

    assert client_with(handler).get_auth_user_id(token) is None
    assert calls == []


def test_jwt_shaped_token_is_sent():
    token = JWT

    assert client_with(lambda r: httpx.Response(200, json={"id": USER_ID})).get_auth_user_id(token) == USER_ID


def test_non_ascii_cookie_through_the_real_client_is_anonymous_not_a_500():
    from starlette.requests import Request

    from app.auth import get_session_user

    calls = []
    real = client_with(lambda r: calls.append(r) or httpx.Response(401))
    request = Request(
        {"type": "http", "method": "GET", "path": "/api/ping", "query_string": b"",
         "headers": [(b"cookie", b"cs_session=\xe9abc")]}
    )

    assert get_session_user(request, real) is None
    assert calls == []


# 재시도하면 풀릴 수 있는 응답은 503, 설정 오류는 500
@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_transient_statuses_are_unavailable_for_every_call(status):
    handler = lambda r: httpx.Response(status, json={})  # noqa: E731

    with pytest.raises(SupabaseUnavailable):
        client_with(handler).get_profile(USER_ID)
    with pytest.raises(SupabaseUnavailable):
        client_with(handler).rpc("rate_limit_hit", {})
    with pytest.raises(SupabaseUnavailable):
        client_with(handler).get_auth_user_id(JWT)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_other_client_errors_on_data_calls_are_config_errors(status):
    handler = lambda r: httpx.Response(status, json={})  # noqa: E731

    with pytest.raises(SupabaseConfigError):
        client_with(handler).get_profile(USER_ID)
    with pytest.raises(SupabaseConfigError):
        client_with(handler).rpc("rate_limit_hit", {})


# 저장 키 해시: secret key로 서명한 HMAC
def test_keyed_hash_is_stable_and_hides_the_input():
    client = client_with(lambda r: httpx.Response(200, json=[]))

    one = client.keyed_hash("203.0.113.1")

    assert one == client.keyed_hash("203.0.113.1")
    assert one != client.keyed_hash("203.0.113.2")
    assert "203.0.113.1" not in one and len(one) == 32


def test_keyed_hash_depends_on_the_secret_key():
    other = SupabaseClient("https://project.supabase.co", "another-secret", httpx.Client())

    assert client_with(lambda r: httpx.Response(200)).keyed_hash("x") != other.keyed_hash("x")


def test_valid_shape_but_oversized_token_is_rejected_without_a_request():
    calls = []
    token = "a" * 2000 + "." + "b" * 2000 + "." + "c" * 200  # 각 구간은 상한 안이지만 전체가 4096자를 넘는다
    client = client_with(lambda r: calls.append(r) or httpx.Response(200, json={"id": USER_ID}))

    assert client.get_auth_user_id(token) is None
    assert calls == []


def test_realistic_large_payload_segment_is_accepted():
    # user_metadata가 큰 계정의 토큰: 가운데 구간이 2800자여도 전체가 4096자 이하면 받는다.
    token = "a" * 40 + "." + "b" * 2800 + "." + "c" * 86

    assert client_with(lambda r: httpx.Response(200, json={"id": USER_ID})).get_auth_user_id(token) == USER_ID


# --- MEG-63: 로그인·갱신·로그아웃 Auth 호출 ---

SESSION_BODY = {
    "access_token": JWT,
    "refresh_token": "refresh-one",
    "expires_in": 3600,
    "token_type": "bearer",
    "user": {"id": USER_ID, "email": "member@example.test"},
}


def test_password_sign_in_posts_to_the_token_endpoint_with_the_secret_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        seen["apikey"] = request.headers["apikey"]
        return httpx.Response(200, json=SESSION_BODY)

    session = client_with(handler).sign_in_with_password("member@example.test", "pw")

    assert session.user_id == USER_ID
    assert session.access_token == JWT
    assert session.refresh_token == "refresh-one"
    assert session.expires_in == 3600
    assert seen["url"] == "https://project.supabase.co/auth/v1/token?grant_type=password"
    assert '"email":"member@example.test"' in seen["body"].replace(" ", "")
    assert seen["apikey"] == "sb_secret_test"


@pytest.mark.parametrize("status, code", [(400, "invalid_credentials"), (400, "email_not_confirmed"), (422, "validation_failed")])
def test_rejected_sign_in_is_none(status, code):
    response = {"code": status, "error_code": code, "msg": "Invalid login credentials"}
    assert client_with(lambda r: httpx.Response(status, json=response)).sign_in_with_password("a@b.c", "x") is None


@pytest.mark.parametrize("call", ["sign_in", "refresh"])
def test_invalid_api_key_on_token_grant_is_a_config_error_not_a_wrong_password(call):
    # 키가 틀렸을 때 모든 로그인이 "비밀번호 틀림"이 되고 계정 실패 횟수를 쓰는 것을 막는다.
    client = client_with(lambda r: httpx.Response(401, json=INVALID_KEY))
    with pytest.raises(SupabaseConfigError):
        client.sign_in_with_password("a@b.c", "x") if call == "sign_in" else client.refresh_session("r")


def test_forwarded_ip_is_sent_only_when_given():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("sb-forwarded-for"))
        return httpx.Response(200, json=SESSION_BODY)

    client = client_with(handler)
    client.sign_in_with_password("a@b.c", "x", "203.0.113.7")
    client.refresh_session("r", "2001:db8::1")
    client.sign_in_with_password("a@b.c", "x")

    assert seen == ["203.0.113.7", "2001:db8::1", None]


def test_sign_in_server_error_is_unavailable():
    with pytest.raises(SupabaseUnavailable):
        client_with(lambda r: httpx.Response(502)).sign_in_with_password("a@b.c", "x")


def test_sign_in_unexpected_client_error_is_a_config_error_not_a_wrong_password():
    # 주소 설정 오류(404)가 "비밀번호 틀림"으로 묻히지 않는다.
    with pytest.raises(SupabaseConfigError):
        client_with(lambda r: httpx.Response(404, json={})).sign_in_with_password("a@b.c", "x")


def test_malformed_session_body_is_unavailable():
    body = {**SESSION_BODY, "user": {"id": "not-a-uuid"}}
    with pytest.raises(SupabaseUnavailable):
        client_with(lambda r: httpx.Response(200, json=body)).sign_in_with_password("a@b.c", "x")


def test_refresh_posts_the_refresh_token_grant():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={**SESSION_BODY, "refresh_token": "refresh-two"})

    session = client_with(handler).refresh_session("refresh-one")

    assert session.refresh_token == "refresh-two"
    assert seen["url"] == "https://project.supabase.co/auth/v1/token?grant_type=refresh_token"
    assert '"refresh_token":"refresh-one"' in seen["body"].replace(" ", "")


def test_revoked_refresh_token_is_none():
    body = {"code": 400, "error_code": "refresh_token_not_found", "msg": "Invalid Refresh Token"}
    assert client_with(lambda r: httpx.Response(400, json=body)).refresh_session("old") is None


def test_sign_out_uses_the_user_token_and_local_scope():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["authorization"]
        return httpx.Response(204)

    assert client_with(handler).sign_out(JWT) is True
    assert seen == {
        "url": "https://project.supabase.co/auth/v1/logout?scope=local",
        "authorization": f"Bearer {JWT}",
    }


@pytest.mark.parametrize("status, code", [(403, "session_not_found"), (403, "bad_jwt"), (404, "user_not_found")])
def test_sign_out_of_a_dead_session_is_false(status, code):
    body = {"code": status, "error_code": code, "msg": "gone"}
    assert client_with(lambda r: httpx.Response(status, json=body)).sign_out(JWT) is False


def test_sign_out_with_an_invalid_api_key_is_a_config_error():
    with pytest.raises(SupabaseConfigError):
        client_with(lambda r: httpx.Response(401, json=INVALID_KEY)).sign_out(JWT)


def test_sign_out_with_a_malformed_token_sends_nothing():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call Auth")

    assert client_with(handler).sign_out("not a token") is False


def test_disabled_email_provider_is_a_config_error_not_a_wrong_password():
    # 422로 오지만 사용자 잘못이 아니다. invalid_credentials로 묻히면 설정 오류를 찾지 못한다.
    body = {"code": 422, "error_code": "email_provider_disabled", "msg": "Email logins are disabled"}
    with pytest.raises(SupabaseConfigError):
        client_with(lambda r: httpx.Response(422, json=body)).sign_in_with_password("a@b.c", "x")


# --- E04 과목·노트 조회 (MEG-71) ---


def capture(rows):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["authorization"] = request.headers["authorization"]
        return httpx.Response(200, json=rows)

    return seen, handler


def test_list_notes_for_non_operator_filters_published_in_db_and_skips_operator_columns():
    rows = [{"id": 1, "title": "t", "studied_on": None, "parent_note_id": None, "note_subjects": []}]
    seen, handler = capture(rows)

    assert client_with(handler).list_notes(include_unpublished=False) == rows
    assert seen == {
        "path": "/rest/v1/notes",
        "params": {
            "select": "id,title,studied_on,parent_note_id,note_subjects(subject_id)",
            "order": "studied_on.desc.nullslast,id.desc",
            "is_published": "eq.true",
        },
        "authorization": "Bearer sb_secret_test",
    }


def test_list_notes_for_operator_reads_all_notes_and_operator_columns():
    seen, handler = capture([])

    client_with(handler).list_notes(include_unpublished=True)

    assert "is_published" not in seen["params"]
    assert seen["params"]["select"].endswith(",is_published,revision,needs_review")


def test_list_subjects_reads_id_and_name_in_id_order():
    seen, handler = capture([{"id": 1, "name": "네트워크"}])

    assert client_with(handler).list_subjects() == [{"id": 1, "name": "네트워크"}]
    assert seen["path"] == "/rest/v1/subjects"
    assert seen["params"] == {"select": "id,name", "order": "id.asc"}


def test_notes_select_rejected_is_a_config_error():
    with pytest.raises(SupabaseConfigError):
        client_with(lambda r: httpx.Response(401, json=INVALID_KEY)).list_notes(include_unpublished=False)


def test_notes_select_server_error_is_unavailable():
    with pytest.raises(SupabaseUnavailable):
        client_with(lambda r: httpx.Response(503)).list_subjects()


# --- E05 노트 읽기·사전 용어·서명 URL (MEG-73) ---

NOTE_SELECT = (
    "id,revision,title,studied_on,body_markdown,"
    "note_subjects(subjects(id,name)),note_sources(id,url,label),"
    "note_images(notion_block_id,storage_path,alt)"
)


def test_get_note_for_non_operator_filters_published_in_db_and_skips_private_columns():
    row = {"id": 11, "title": "t"}
    seen, handler = capture([row])

    assert client_with(handler).get_note(11, include_unpublished=False) == row
    assert seen["path"] == "/rest/v1/notes"
    assert seen["params"] == {"id": "eq.11", "select": NOTE_SELECT, "limit": "1", "is_published": "eq.true"}
    # memo·needs_review·is_published 같은 비공개 열은 읽지 않는다.
    assert not {"memo", "needs_review", "importance", "is_published"} & set(seen["params"]["select"].split(","))


def test_get_note_for_operator_reads_unpublished_and_missing_is_none():
    seen, handler = capture([])

    assert client_with(handler).get_note(13, include_unpublished=True) is None
    assert "is_published" not in seen["params"]


def test_list_glossary_terms_reads_only_terms_with_a_glossary_entry():
    seen, handler = capture([])

    client_with(handler).list_glossary_terms()

    assert seen["path"] == "/rest/v1/terms"
    assert seen["params"] == {"select": "id,key,label,glossary_entries!inner(term_id)", "order": "id.asc"}


def signing_client(handler, bucket: str | None = "note-images") -> SupabaseClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SupabaseClient("https://project.supabase.co/", "sb_secret_test", http, note_image_bucket=bucket)


def test_sign_note_images_signs_all_paths_in_one_call_and_drops_failed_items():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content.decode()
        seen["authorization"] = request.headers["authorization"]
        # 로컬 Storage(2026-10-30)에서 본 모양. 서명 경로는 공백을 그대로 담아 온다. 토큰은 가짜다.
        return httpx.Response(
            200,
            json=[
                {"error": None, "path": "notes/11/a b+(1).png", "signedURL": "/object/sign/note-images/notes/11/a b+(1).png?token=fake-token"},
                {"error": "Either the object does not exist or you do not have access to it", "path": "notes/11/gone.png", "signedURL": None},
            ],
        )

    signed = signing_client(handler).sign_note_images(["notes/11/a b+(1).png", "notes/11/gone.png"], 300)

    assert signed == {
        "notes/11/a b+(1).png": "https://project.supabase.co/storage/v1/object/sign/note-images/notes/11/a%20b%2B%281%29.png?token=fake-token"
    }
    assert seen["path"] == "/storage/v1/object/sign/note-images"
    assert '"expiresIn":300' in seen["body"].replace(" ", "")
    assert seen["authorization"] == "Bearer sb_secret_test"


def test_question_mark_in_a_storage_path_is_encoded_not_taken_as_the_query():
    # Storage 키에는 ?가 들어갈 수 있다(2026-10-30 로컬 업로드 200). 마지막 ? 앞까지만 경로다.
    body = [{"error": None, "path": "n/q?mark.png", "signedURL": "/object/sign/b.1/n/q?mark.png?token=fake-token"}]
    client = signing_client(lambda r: httpx.Response(200, json=body), "b.1")

    assert client.sign_note_images(["n/q?mark.png"], 300) == {
        "n/q?mark.png": "https://project.supabase.co/storage/v1/object/sign/b.1/n/q%3Fmark.png?token=fake-token"
    }


@pytest.mark.parametrize("bad", ["/object/sign/b/a.png", 7, None])
def test_an_odd_signed_item_drops_only_that_image(bad):
    body = [
        {"error": None, "path": "a.png", "signedURL": bad},
        {"error": None, "path": "b.png", "signedURL": "/object/sign/b/b.png?token=fake-token"},
    ]

    signed = signing_client(lambda r: httpx.Response(200, json=body)).sign_note_images(["a.png", "b.png"], 300)

    assert list(signed) == ["b.png"]


@pytest.mark.parametrize("bucket", [None, "", "../other", "note images", ".", ".."])
def test_sign_without_a_valid_bucket_is_a_config_error_and_sends_nothing(bucket):
    def handler(request):
        raise AssertionError("must not call Storage")

    with pytest.raises(SupabaseConfigError):
        signing_client(handler, bucket).sign_note_images(["notes/11/a.png"], 300)


def test_sign_rejected_is_a_config_error():
    with pytest.raises(SupabaseConfigError):
        signing_client(lambda r: httpx.Response(400, json={"error": "Bucket not found"})).sign_note_images(["a.png"], 300)


@pytest.mark.parametrize(
    "response",
    [httpx.Response(503), httpx.Response(200, json={"not": "a list"}), httpx.Response(200, text="oops"), httpx.Response(200, json=[{}])],
)
def test_sign_outage_or_malformed_body_is_unavailable(response):
    with pytest.raises(SupabaseUnavailable):
        signing_client(lambda r: response).sign_note_images(["a.png"], 300)


def test_from_env_reads_the_note_image_bucket(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    monkeypatch.setenv("NOTE_IMAGE_BUCKET", " note-images ")

    assert SupabaseClient.from_env()._note_image_bucket == "note-images"

    monkeypatch.delenv("NOTE_IMAGE_BUCKET")
    assert SupabaseClient.from_env()._note_image_bucket is None


# --- E06 사전 용어·E07 열람 기록 (MEG-75) ---


GLOSSARY_SELECT = "id,key,label,glossary_entries!inner(body_markdown),glossary_images(id,storage_path,alt)"


def test_get_glossary_entry_reads_one_glossary_term_with_ordered_images():
    row = {"id": 7, "key": "k", "label": "K", "glossary_entries": {"body_markdown": "b"}, "glossary_images": []}
    seen, handler = capture([row])

    assert client_with(handler).get_glossary_entry(7) == row
    assert seen["path"] == "/rest/v1/terms"
    # 방문자는 즐겨찾기를 읽지 않는다.
    assert seen["params"] == {
        "id": "eq.7",
        "select": GLOSSARY_SELECT,
        "glossary_images.order": "id.asc",
        "limit": "1",
    }


def test_get_glossary_entry_for_a_user_embeds_only_that_users_favorite():
    seen, handler = capture([])

    client_with(handler).get_glossary_entry(7, USER_ID)

    assert seen["params"] == {
        "id": "eq.7",
        "select": GLOSSARY_SELECT + ",favorites(term_id)",
        "favorites.user_id": f"eq.{USER_ID}",
        "glossary_images.order": "id.asc",
        "limit": "1",
    }


def test_get_glossary_entry_rejects_non_uuid_user_ids():
    with pytest.raises(ValueError):
        client_with(capture([])[1]).get_glossary_entry(7, "not-a-uuid")


def test_get_glossary_entry_without_a_glossary_row_is_none():
    _, handler = capture([])
    assert client_with(handler).get_glossary_entry(9) is None


def test_record_term_view_inserts_and_ignores_duplicates():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["prefer"] = request.headers["prefer"]
        seen["body"] = request.content.decode()
        return httpx.Response(201)

    assert client_with(handler).record_term_view(USER_ID, 7, "2026-10-23") is True
    assert seen["method"] == "POST"
    assert seen["path"] == "/rest/v1/term_views"
    assert seen["prefer"] == "resolution=ignore-duplicates,return=minimal"
    assert seen["body"].replace(" ", "") == f'{{"user_id":"{USER_ID}","term_id":7,"study_date":"2026-10-23"}}'


# 2026-11-02 로컬 PostgREST가 준 외래 키 위반 본문(값만 합성).
TERM_FK = {"code": "23503", "message": 'insert or update on table "term_views" violates foreign key constraint "term_views_term_id_fkey"'}
USER_FK = {"code": "23503", "message": 'insert or update on table "term_views" violates foreign key constraint "term_views_user_id_fkey"'}


def test_record_term_view_for_a_missing_term_is_false():
    assert client_with(lambda r: httpx.Response(409, json=TERM_FK)).record_term_view(USER_ID, 7, "2026-10-23") is False


@pytest.mark.parametrize(
    "response",
    [httpx.Response(409, json=USER_FK), httpx.Response(409, json={"code": "23503"}),
     httpx.Response(409, json={"code": "23505"}), httpx.Response(401, json={"message": "Invalid API key"}),
     httpx.Response(403, json={"code": "42501"}), httpx.Response(409, text="not json"),
     httpx.Response(409, json=["not", "an", "object"])],
)
def test_record_term_view_other_rejections_are_config_errors(response):
    with pytest.raises(SupabaseConfigError):
        client_with(lambda r: response).record_term_view(USER_ID, 7, "2026-10-23")


def test_record_term_view_outage_is_unavailable():
    with pytest.raises(SupabaseUnavailable):
        client_with(lambda r: httpx.Response(503)).record_term_view(USER_ID, 7, "2026-10-23")


def glossary_client(bucket: str | None = "glossary-images") -> SupabaseClient:
    def handler(request):
        raise AssertionError("public URLs need no Storage call")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SupabaseClient("https://project.supabase.co/", "sb_secret_test", http, glossary_image_bucket=bucket)


def test_glossary_image_url_is_the_public_object_url_with_an_encoded_path():
    assert glossary_client().glossary_image_url("terms/7/a b+(1)?.png") == (
        "https://project.supabase.co/storage/v1/object/public/glossary-images/terms/7/a%20b%2B%281%29%3F.png"
    )


@pytest.mark.parametrize("path", ["../note-images/x.png", "terms/../../x.png", "/abs.png", "terms//x.png", "./x.png", "terms/"])
def test_glossary_image_url_rejects_empty_or_dot_segments(path):
    # 브라우저가 ../를 정규화하면 다른 버킷의 공개 주소가 된다.
    with pytest.raises(SupabaseConfigError):
        glossary_client().glossary_image_url(path)


@pytest.mark.parametrize("bucket", [None, "", "../other", "glossary images", ".", ".."])
def test_glossary_image_url_without_a_valid_bucket_is_a_config_error(bucket):
    with pytest.raises(SupabaseConfigError):
        glossary_client(bucket).glossary_image_url("terms/7/a.png")


def test_from_env_reads_the_glossary_image_bucket(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    monkeypatch.setenv("GLOSSARY_IMAGE_BUCKET", " glossary-images ")

    assert SupabaseClient.from_env()._glossary_image_bucket == "glossary-images"

    monkeypatch.delenv("GLOSSARY_IMAGE_BUCKET")
    assert SupabaseClient.from_env()._glossary_image_bucket is None


# --- E09(MEG-87)가 쓰는 조회·저장 ---


def test_note_for_explain_reads_only_the_four_columns_and_filters_private_notes_in_the_db():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[{"id": 11, "revision": 3, "is_published": True, "body_markdown": "본문"}])

    client = client_with(handler)
    assert client.get_note_for_explain(11, include_unpublished=False)["revision"] == 3
    client.get_note_for_explain(11, include_unpublished=True)

    columns = "id,revision,is_published,body_markdown"
    assert seen[0] == ("/rest/v1/notes", {"id": "eq.11", "select": columns, "limit": "1", "is_published": "eq.true"})
    assert seen[1] == ("/rest/v1/notes", {"id": "eq.11", "select": columns, "limit": "1"})
    assert client_with(lambda r: httpx.Response(200, json=[])).get_note_for_explain(99, True) is None


def test_term_for_explain_filters_embedded_explanations_and_favorites_to_active_and_mine():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=[{"id": 9, "key": "k"}])

    assert client_with(handler).find_term_for_explain("k", USER_ID) == {"id": 9, "key": "k"}
    params = seen["params"]
    assert params["key"] == "eq.k" and params["limit"] == "1"
    assert params["ai_explanations.invalidated_at"] == "is.null"
    assert params["favorites.user_id"] == f"eq.{USER_ID}"
    assert params["glossary_images.order"] == "id.asc"
    for embedded in ("glossary_entries(body_markdown)", "ai_explanations(id,body,review_status)", "favorites(term_id)"):
        assert embedded in params["select"]
    assert client_with(lambda r: httpx.Response(200, json=[])).find_term_for_explain("k", USER_ID) is None


def test_ledger_rows_are_looked_up_by_request_key_prefix_for_the_session_user_only():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["params"] = request.url.path, dict(request.url.params)
        return httpx.Response(200, json=[{"status": "settled", "attempt_no": 1, "created_at": "2026-11-02T05:00:00+00:00"}])

    key = f"{USER_ID}:3f2b8c1e-0000-4000-8000-000000000001"
    rows = client_with(handler).list_ledger_rows(USER_ID, key)

    assert rows[0]["status"] == "settled"
    assert seen["path"] == "/rest/v1/ai_usage_ledger"
    assert seen["params"]["idempotency_key"] == f"like.{key}:*"
    assert seen["params"]["user_id"] == f"eq.{USER_ID}"


def test_store_ai_explanation_sends_p_arguments_and_strips_the_out_prefix():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["json"] = request.url.path, request.read()
        return httpx.Response(200, json=[{"out_outcome": "stored", "out_term_id": 5, "out_explanation_id": 8,
                                          "out_body": "설명", "out_review_status": "pending"}])

    result = client_with(handler).store_ai_explanation(note_id=1, note_revision=2, term_key="k", body="설명")

    assert result == {"outcome": "stored", "term_id": 5, "explanation_id": 8, "body": "설명", "review_status": "pending"}
    assert seen["path"] == "/rest/v1/rpc/ai_store_explanation"
    assert b'"p_note_id":1' in seen["json"] and b'"p_term_key":"k"' in seen["json"]


# --- E10(MEG-88)이 쓰는 대상 확인과 신고 저장 ---

DUP = {"code": "23505", "message": 'duplicate key value violates unique constraint "reports_open_ai_explanation_idx"'}
FK = {"code": "23503", "message": 'insert or update on table "reports" violates foreign key constraint "reports_ai_explanation_id_fkey"'}


def test_report_target_check_for_an_explanation_requires_it_to_be_valid_and_for_a_quiz_item_to_be_mine():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[{"id": 1}])

    client = client_with(handler)
    assert client.report_target_exists("ai_explanation", 31, USER_ID) is True
    assert client.report_target_exists("quiz_item", 41, USER_ID) is True

    assert seen[0] == ("/rest/v1/ai_explanations", {"id": "eq.31", "invalidated_at": "is.null", "select": "id", "limit": "1"})
    assert seen[1][0] == "/rest/v1/quiz_items"
    assert seen[1][1]["id"] == "eq.41" and seen[1][1]["quiz_sets.user_id"] == f"eq.{USER_ID}"
    assert "quiz_sets!inner(user_id)" in seen[1][1]["select"]
    assert client_with(lambda r: httpx.Response(200, json=[])).report_target_exists("quiz_item", 41, USER_ID) is False
    with pytest.raises(ValueError):
        client.report_target_exists("note", 1, USER_ID)


def test_create_report_returns_the_new_row_as_created():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["path"], seen["params"] = request.method, request.url.path, dict(request.url.params)
        seen["body"], seen["prefer"] = request.read(), request.headers["prefer"]
        return httpx.Response(201, json=[{"id": 5, "status": "open"}])

    row, created = client_with(handler).create_report(USER_ID, "quiz_item", 41, "합성")

    assert (row, created) == ({"id": 5, "status": "open"}, True)
    assert (seen["method"], seen["path"], seen["prefer"]) == ("POST", "/rest/v1/reports", "return=representation")
    assert seen["params"] == {"select": "id,status"}
    assert b'"quiz_item_id":41' in seen["body"] and b"ai_explanation_id" not in seen["body"]


def test_create_report_reads_the_existing_open_report_when_the_open_unique_index_rejects_the_insert():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, dict(request.url.params)))
        if request.method == "POST":
            return httpx.Response(409, json=DUP)
        return httpx.Response(200, json=[{"id": 5, "status": "open"}])

    row, created = client_with(handler).create_report(USER_ID, "ai_explanation", 31, "x")

    assert (row, created) == ({"id": 5, "status": "open"}, False)
    assert calls[1][1] == {"user_id": f"eq.{USER_ID}", "ai_explanation_id": "eq.31", "status": "eq.open",
                           "select": "id,status", "limit": "1"}


def test_create_report_retries_once_when_the_conflicting_report_was_resolved_in_between():
    posts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(1)
            return httpx.Response(409, json=DUP) if len(posts) == 1 else httpx.Response(201, json=[{"id": 6, "status": "open"}])
        return httpx.Response(200, json=[])

    row, created = client_with(handler).create_report(USER_ID, "ai_explanation", 31, "x")

    assert (row["id"], created, len(posts)) == (6, True, 2)


def test_create_report_without_a_live_target_is_none_and_other_rejections_are_config_errors():
    assert client_with(lambda r: httpx.Response(409, json=FK)).create_report(USER_ID, "ai_explanation", 31, "x") is None
    # 사용자 쪽 외래 키나 알 수 없는 제약은 대상 없음이 아니라 설정 오류(500)다
    user_fk = {"code": "23503", "message": 'violates foreign key constraint "reports_user_id_fkey"'}
    with pytest.raises(SupabaseConfigError):
        client_with(lambda r: httpx.Response(409, json=user_fk)).create_report(USER_ID, "ai_explanation", 31, "x")
    with pytest.raises(SupabaseConfigError):
        client_with(lambda r: httpx.Response(400, json={"code": "23514", "message": "check"})).create_report(
            USER_ID, "ai_explanation", 31, "x")
    with pytest.raises(SupabaseUnavailable):
        client_with(lambda r: httpx.Response(503)).create_report(USER_ID, "ai_explanation", 31, "x")


QUIZ_DUP = {"code": "23505", "message": 'duplicate key value violates unique constraint "reports_open_quiz_item_idx"'}
QUIZ_FK = {"code": "23503", "message": 'violates foreign key constraint "reports_quiz_item_id_fkey"'}


def test_create_report_for_a_quiz_item_uses_the_quiz_item_column_everywhere():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, dict(request.url.params)))
        if request.method == "POST":
            return httpx.Response(409, json=QUIZ_DUP)
        return httpx.Response(200, json=[{"id": 8, "status": "open"}])

    row, created = client_with(handler).create_report(USER_ID, "quiz_item", 41, "x")

    assert (row["id"], created) == (8, False)
    assert calls[1][1]["quiz_item_id"] == "eq.41" and "ai_explanation_id" not in calls[1][1]
    assert client_with(lambda r: httpx.Response(409, json=QUIZ_FK)).create_report(USER_ID, "quiz_item", 41, "x") is None


@pytest.mark.parametrize(
    ("target_type", "error"),
    [
        # 열이 엇갈린 제약, 열린 신고가 아닌 유일 제약은 대상 없음·중복이 아니라 설정 오류다
        ("quiz_item", FK),
        ("ai_explanation", QUIZ_FK),
        ("ai_explanation", {"code": "23505", "message": 'duplicate key value violates unique constraint "reports_pkey"'}),
    ],
    ids=["fk-of-another-column", "fk-of-the-other-target", "other-unique-constraint"],
)
def test_create_report_does_not_misread_other_constraint_violations(target_type, error):
    with pytest.raises(SupabaseConfigError):
        client_with(lambda r: httpx.Response(409, json=error)).create_report(USER_ID, target_type, 31, "x")


def test_create_report_that_conflicts_twice_without_an_open_report_is_a_503_not_a_config_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json=DUP) if request.method == "POST" else httpx.Response(200, json=[])

    with pytest.raises(SupabaseUnavailable):
        client_with(handler).create_report(USER_ID, "ai_explanation", 31, "x")
