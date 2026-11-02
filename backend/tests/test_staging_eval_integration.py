"""Guard the actual app composition when promoting evaluation tools to staging."""
from fastapi.testclient import TestClient

from app.main import app
from app.auth import get_session_user


def test_existing_routes_and_private_evaluation_coexist(monkeypatch):
    paths = set(app.openapi()["paths"])
    assert {"/api/admin/users", "/api/auth/login", "/api/auth/logout", "/api/me",
            "/api/notes", "/api/notes/{note_id}", "/api/health"} <= paths
    monkeypatch.setenv("VERCEL_ENV", "production")
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        origin = next(iter(app.state.allowed_origins))
        assert client.post("/api/internal/evals/preflight", json={},
                           headers={"Origin": origin}).status_code == 404
        assert not any("/internal/evals" in path for path in client.get("/openapi.json").json()["paths"])
        monkeypatch.setenv("VERCEL_ENV", "preview")
        monkeypatch.setenv("VERCEL_GIT_COMMIT_REF", "staging")
        monkeypatch.setenv("EVAL_APPROVAL_ID", "fixture")
        monkeypatch.setenv("AI_AUTH_MODE", "oidc")
        monkeypatch.setitem(app.dependency_overrides, get_session_user, lambda: None)
        for path in ("preflight", "run/D01", "status"):
            assert client.post("/api/internal/evals/" + path, json={},
                               headers={"Origin": origin}).status_code == 401
