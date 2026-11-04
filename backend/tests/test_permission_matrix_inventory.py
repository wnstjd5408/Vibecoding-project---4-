"""Always-on route inventory; the real local matrix is an explicit opt-in suite."""

from app.main import app
from permission_matrix import ENDPOINTS


def test_endpoint_inventory():
    paths = app.openapi()["paths"]
    assert [e.id for e in ENDPOINTS] == [f"E{i:02}" for i in range(1, 27)]
    for endpoint in ENDPOINTS:
        present = endpoint.method.lower() in paths.get(endpoint.path, {})
        if endpoint.pending:
            assert not present, f"{endpoint.id} is now implemented: remove pending and validate its fixtures"
        else:
            assert present, f"{endpoint.id} route vanished; do not silently skip a regression"
