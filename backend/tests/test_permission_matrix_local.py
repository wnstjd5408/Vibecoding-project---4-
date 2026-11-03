"""MEG-69: real local API permission matrix. See permission_matrix_README.md.

Without MEG69_LOCAL=1 only the route inventory check runs. Missing environment
is reported as skipped, never as successful authorization verification.
"""

import os

import pytest

from app.main import app
from permission_local import (
    EXPLANATION, IMAGE, NOTE, PRIVATE, REPORT, TERM,
    LocalMatrix, install,
)
from permission_matrix import BY_ID, ENDPOINTS, ROLES, expected


def test_endpoint_inventory():
    paths = app.openapi()["paths"]
    assert [e.id for e in ENDPOINTS] == [f"E{i:02}" for i in range(1, 27)]
    for e in ENDPOINTS:
        present = e.method.lower() in paths.get(e.path, {})
        if e.pending:
            assert not present, f"{e.id} is now implemented: remove pending and validate its fixtures"
        else:
            assert present, f"{e.id} route vanished; do not silently skip a regression"


@pytest.fixture(scope="module")
def local():
    if os.environ.get("MEG69_LOCAL") != "1":
        pytest.skip("MEG69_LOCAL=1 and this worktree's disposable Supabase stack required")
    matrix = LocalMatrix()
    with pytest.MonkeyPatch.context() as patch:
        install(matrix, patch)
        try:
            matrix.setup()
            yield matrix
        finally:
            matrix.close()


@pytest.fixture
def case(request):
    endpoint = request.getfixturevalue("endpoint") if "endpoint" in request.fixturenames else None
    if endpoint and endpoint.pending:
        pytest.skip(f"{endpoint.id}: {endpoint.pending} route not implemented on main")
    matrix = request.getfixturevalue("local")
    matrix.seed()
    return matrix


def verify_response(response, status, code):
    actual = response.json().get("error", {}).get("code") if response.content else None
    assert (response.status_code, actual) == (status, code)
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e.id)
@pytest.mark.parametrize("role", ROLES)
def test_role_matrix(endpoint, role, case):
    path, kwargs = case.prepare_request(endpoint, role)
    status, code = expected(endpoint, role)
    before, offset = case.snapshot(), len(case.calls)
    with case.client(role) as client:
        response = client.request(endpoint.method, path, **kwargs)
        # Track a created account before asserting the response, so cleanup also runs on failure.
        if endpoint.id == "E24" and response.status_code == 201:
            case.created.append(response.json()["id"])
        verify_response(response, status, code)
        if code:
            case.assert_no_effect(before, offset)
            return
        body = response.json() if response.content else {}
        if endpoint.id == "E01":
            assert client.get("/api/me").json()["authenticated"] is True
        elif endpoint.id == "E02":
            assert client.get("/api/me").json() == {"authenticated": False}
            if role != "visitor":
                case.renew(role)
        elif endpoint.id == "E03":
            assert body["authenticated"] is (role != "visitor")
            if role != "visitor":
                assert body["role"] == role
        elif endpoint.id == "E04":
            ids = {n["id"] for n in body["notes"]}
            assert NOTE in ids and (PRIVATE in ids) == (role == "operator")
        elif endpoint.id == "E05":
            assert body["id"] == NOTE
        elif endpoint.id == "E06":
            assert body["term"]["id"] == TERM
        elif endpoint.id == "E07":
            assert body == {"recorded": role != "visitor"}
            if role == "visitor":
                case.assert_no_effect(before, offset)
            else:
                uid = case.users[role]["id"]
                assert case.sql(f"select count(*) from term_views where user_id='{uid}' and term_id={TERM};") == "1"
        elif endpoint.id == "E08":
            assert body == {"term_id": TERM, "is_favorite": True}
        elif endpoint.id == "E09":
            assert body["source"] == "ai" and body["explanation"]["cached"] is True
        elif endpoint.id == "E10":
            assert body["status"] == "open"
        elif endpoint.id == "E11":
            assert body["status"] == "ready"
            assert [item["id"] for item in body["items"]] == [case.users[role]["item"]]
        elif endpoint.id == "E12":
            assert body["your_answer"] == "Synthetic answer"
        elif endpoint.id == "E13":
            assert body["question"] == "Synthetic followup"
        elif endpoint.id == "E14":
            assert body["answered"] is True
        elif endpoint.id == "E19":
            assert TERM in {term["id"] for term in body["terms"]}
        elif endpoint.id == "E20":
            assert body["term"]["label"].startswith("meg69 ")
        elif endpoint.id == "E21":
            assert case.sql(f"select count(*) from glossary_entries where term_id={TERM};") == "0"
        elif endpoint.id == "E22":
            assert case.sql(f"select count(*) from glossary_images where term_id={TERM};") == "2"
        elif endpoint.id == "E23":
            assert case.sql(f"select count(*) from glossary_images where id={IMAGE};") == "0"
        elif endpoint.id == "E24":
            assert body["role"] == "member" and case.db.get_profile(body["id"]).is_active
        elif endpoint.id == "E25":
            assert REPORT in {report["id"] for report in body["reports"]}
        elif endpoint.id == "E26":
            assert body == {"id": REPORT, "status": "resolved"}
            assert case.sql(f"select invalidated_at is not null from ai_explanations where id={EXPLANATION};") == "t"


@pytest.mark.parametrize("endpoint", [e for e in ENDPOINTS if e.access != "public" or e.id in ("E03", "E07")], ids=lambda e: e.id)
@pytest.mark.parametrize("role", ("expired", "inactive"))
def test_lost_session(endpoint, role, case):
    path, kwargs = case.prepare_request(endpoint, role)
    before, offset = case.snapshot(), len(case.calls)
    with case.client(role) as client:
        response = client.request(endpoint.method, path, **kwargs)
        status, code = expected(endpoint, role)
        verify_response(response, status, code)
        if endpoint.id == "E03":
            assert response.json() == {"authenticated": False}
        elif endpoint.id == "E07":
            assert response.json() == {"recorded": False}
        case.assert_no_effect(before, offset)
        assert client.get("/api/me").json() == {"authenticated": False}


@pytest.mark.parametrize("endpoint", [BY_ID["E05"], BY_ID["E09"]], ids=lambda e: e.id)
@pytest.mark.parametrize("role", ROLES)
def test_private_note(endpoint, role, case):
    path, kwargs = case.prepare_request(endpoint, role, private=True)
    before, offset = case.snapshot(), len(case.calls)
    status = 200 if role == "operator" else 401 if endpoint.id == "E09" and role == "visitor" else 404
    code = {200: None, 401: "login_required", 404: "not_found"}[status]
    with case.client(role) as client:
        response = client.request(endpoint.method, path, **kwargs)
    verify_response(response, status, code)
    if code:
        case.assert_no_effect(before, offset)
        assert not any("/object/sign/" in path for _, path in case.calls[offset:])
    elif endpoint.id == "E05":
        assert response.json()["images"], "operator must get the private image URL"


@pytest.mark.parametrize("endpoint", [BY_ID[e] for e in ("E10", "E12", "E13", "E14")], ids=lambda e: e.id)
@pytest.mark.parametrize("role", ("member", "operator"))
def test_foreign_quiz(endpoint, role, case):
    path, kwargs = case.prepare_request(endpoint, role, foreign=True)
    before, offset = case.snapshot(), len(case.calls)
    with case.client(role) as client:
        response = client.request(endpoint.method, path, **kwargs)
    verify_response(response, 404, "not_found")
    case.assert_no_effect(before, offset)


@pytest.mark.parametrize("endpoint", [e for e in ENDPOINTS if e.method != "GET"], ids=lambda e: e.id)
@pytest.mark.parametrize("origin", (None, "https://untrusted.example"), ids=("missing", "foreign"))
def test_origin_is_distinct_from_role_denial(endpoint, origin, case):
    path, kwargs = case.prepare_request(endpoint, "operator")
    kwargs["headers"].pop("Origin")
    if origin:
        kwargs["headers"]["Origin"] = origin
    before, offset = case.snapshot(), len(case.calls)
    with case.client("operator") as client:
        response = client.request(endpoint.method, path, **kwargs)
    verify_response(response, 403, "origin_not_allowed")
    case.assert_no_effect(before, offset)
