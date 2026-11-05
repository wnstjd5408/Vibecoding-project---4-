import pytest
from support import cookie
from test_eval_staging import rig


@pytest.mark.parametrize("path", ["console", "console.js"])
def test_console_requires_active_operator_and_staging(rig, monkeypatch, path):
    url = "/api/internal/evals/" + path
    for user, status in [("missing",401),("member",403),("inactive",401),("operator",200)]:
        result = rig.http.get(url, headers=cookie(user))
        assert result.status_code == status
        assert result.headers["cache-control"] == "private, no-store"
    monkeypatch.setenv("VERCEL_ENV", "production")
    assert rig.http.get(url, headers=cookie("operator")).status_code == 404
    assert not rig.calls and not rig.exchanges and not rig.attempts


def test_console_has_no_inline_execution_or_public_schema(rig):
    response = rig.http.get("/api/internal/evals/console", headers=cookie("operator"))
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert 'src="/api/internal/evals/console.js"' in response.text
    assert "eval" not in str(rig.http.get("/openapi.json").json()["paths"])
