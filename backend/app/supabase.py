"""Supabase 호출 최소 래퍼. FastAPI만 secret key로 부른다(D-007).

이 파일이 하는 일은 세 가지다: 세션 토큰 확인(Auth), profiles 조회(REST), SQL 함수 호출(RPC).
"""

import os
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

_TIMEOUT = httpx.Timeout(5.0, connect=3.0)


class SupabaseUnavailable(Exception):
    """연결 실패, 시간 초과, 5xx. main.py의 처리기가 503으로 바꾼다."""


class SupabaseConfigError(Exception):
    """환경변수가 없거나 키 권한이 거부됐다. main.py의 처리기가 500으로 바꾼다."""


@dataclass(frozen=True)
class Profile:
    role: str
    is_active: bool


class SupabaseClient:
    def __init__(self, url: str, secret_key: str, http: httpx.Client | None = None):
        self._url = url.rstrip("/")
        self._secret_key = secret_key
        self._http = http or httpx.Client(timeout=_TIMEOUT)

    @classmethod
    def from_env(cls) -> "SupabaseClient":
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SECRET_KEY")
        if not url or not key:
            raise SupabaseConfigError("SUPABASE_URL or SUPABASE_SECRET_KEY is not set")
        return cls(url, key)

    def _headers(self, bearer: str | None = None) -> dict[str, str]:
        return {"apikey": self._secret_key, "Authorization": f"Bearer {bearer or self._secret_key}"}

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._http.request(method, f"{self._url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise SupabaseUnavailable(type(exc).__name__) from None
        if response.status_code >= 500:
            raise SupabaseUnavailable(f"status {response.status_code}")
        return response

    def get_auth_user_id(self, access_token: str) -> str | None:
        """토큰이 살아 있는 세션이면 사용자 id를, 아니면 None을 돌려준다.

        Auth 서버가 세션 유무까지 확인하므로 로그아웃·회수로 끊은 세션이 바로 거부된다.
        """
        response = self._request("GET", "/auth/v1/user", headers=self._headers(access_token))
        if response.status_code in (400, 401, 403):
            return None
        if response.status_code != 200:
            raise SupabaseUnavailable(f"status {response.status_code}")
        try:
            return str(uuid.UUID(str(response.json().get("id"))))
        except (ValueError, AttributeError):
            return None

    def get_profile(self, user_id: str) -> Profile | None:
        """profiles 행이 없으면 None이다. user_id는 UUID 형식으로 검증한 값만 받는다."""
        user_id = str(uuid.UUID(user_id))
        response = self._request(
            "GET",
            "/rest/v1/profiles",
            params={"user_id": f"eq.{user_id}", "select": "role,is_active", "limit": "1"},
            headers=self._headers(),
        )
        if response.status_code != 200:
            # 키·권한 설정 오류(RLS·GRANT)는 응답에 원인을 담지 않고 500으로 낸다.
            raise SupabaseConfigError(f"profiles select status {response.status_code}")
        rows = response.json()
        if not rows:
            return None
        return Profile(role=rows[0]["role"], is_active=bool(rows[0]["is_active"]))

    def rpc(self, name: str, payload: dict[str, Any]) -> Any:
        response = self._request("POST", f"/rest/v1/rpc/{name}", json=payload, headers=self._headers())
        if response.status_code != 200:
            raise SupabaseConfigError(f"rpc {name} status {response.status_code}")
        return response.json()


_client: SupabaseClient | None = None


def get_supabase() -> SupabaseClient:
    """FastAPI 의존성. 시험은 dependency_overrides로 바꾼다."""
    global _client
    if _client is None:
        _client = SupabaseClient.from_env()
    return _client
