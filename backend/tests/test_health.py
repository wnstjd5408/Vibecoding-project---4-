from fastapi.testclient import TestClient
import httpx
import pytest

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("cookie", [None, "cs_session=invalid-session"])
def test_api_health_is_liveness_only(monkeypatch, cookie):
    for name in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "AWS_ROLE_ARN", "AWS_BEARER_TOKEN_BEDROCK"):
        monkeypatch.delenv(name, raising=False)

    def reject_network(*args, **kwargs):
        raise AssertionError("Health must not call external services")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", reject_network)
    headers = {"Cookie": cookie} if cookie else {}
    response = client.get("/api/health", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-request-id"]
