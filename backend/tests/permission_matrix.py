"""API spec v0.2 sections 2/4: explicit contract, not inferred from implementation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoint:
    id: str
    method: str
    path: str
    success: int
    access: str = "public"
    pending: str | None = None


ENDPOINTS = (
    Endpoint("E01", "POST", "/api/auth/login", 200),
    Endpoint("E02", "POST", "/api/auth/logout", 204),
    Endpoint("E03", "GET", "/api/me", 200),
    Endpoint("E04", "GET", "/api/notes", 200),
    Endpoint("E05", "GET", "/api/notes/{note_id}", 200),
    Endpoint("E06", "GET", "/api/glossary/{term_id}", 200),
    Endpoint("E07", "POST", "/api/term-views", 200),
    Endpoint("E08", "PUT", "/api/favorites/{term_id}", 200, "login"),
    Endpoint("E09", "POST", "/api/ai/explanations", 200, "login"),
    Endpoint("E10", "POST", "/api/reports", 201, "login"),
    Endpoint("E11", "POST", "/api/quiz/today", 200, "login"),
    Endpoint("E12", "POST", "/api/quiz/items/{item_id}/answer", 200, "login"),
    Endpoint("E13", "POST", "/api/quiz/items/{item_id}/followups", 200, "login"),
    Endpoint("E14", "PUT", "/api/quiz/items/{item_id}/followups/{seq}/answer", 200, "login"),
    Endpoint("E15", "GET", "/api/admin/notes/{note_id}", 200, "operator", "MEG-79"),
    Endpoint("E16", "POST", "/api/admin/notes", 201, "operator", "MEG-79"),
    Endpoint("E17", "PATCH", "/api/admin/notes/{note_id}", 200, "operator", "MEG-79"),
    Endpoint("E18", "DELETE", "/api/admin/notes/{note_id}", 204, "operator", "MEG-79"),
    Endpoint("E19", "GET", "/api/admin/glossary", 200, "operator"),
    Endpoint("E20", "POST", "/api/admin/glossary", 201, "operator"),
    Endpoint("E21", "DELETE", "/api/admin/glossary/{term_id}", 204, "operator"),
    Endpoint("E22", "POST", "/api/admin/glossary/{term_id}/images", 201, "operator"),
    Endpoint("E23", "DELETE", "/api/admin/glossary/{term_id}/images/{image_id}", 204, "operator"),
    Endpoint("E24", "POST", "/api/admin/users", 201, "operator"),
    Endpoint("E25", "GET", "/api/admin/reports", 200, "operator"),
    Endpoint("E26", "PATCH", "/api/admin/reports/{report_id}", 200, "operator"),
)
BY_ID = {endpoint.id: endpoint for endpoint in ENDPOINTS}
ROLES = ("visitor", "member", "operator")


def expected(endpoint, role):
    if endpoint.access != "public" and role in ("visitor", "expired", "inactive"):
        return 401, "login_required"
    if endpoint.access == "operator" and role == "member":
        return 403, "forbidden"
    return endpoint.success, None
