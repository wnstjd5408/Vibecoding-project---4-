"""Supabase 호출 최소 래퍼. FastAPI만 secret key로 부른다(D-007).

이 파일이 하는 일: 로그인·세션 갱신·로그아웃·세션 토큰 확인(Auth), profiles·과목·노트·사전 용어 조회(REST),
노트 이미지 서명 URL 발급(Storage), SQL 함수 호출(RPC).
"""

import hashlib
import hmac
import os
import re
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import ceil
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

_TIMEOUT = httpx.Timeout(5.0, connect=3.0)

# Supabase 액세스 토큰(JWT) 모양: base64url 세 구간을 점으로 이은 것. 이 밖의 쿠키 값은 Auth를 부르기 전에
# 무효로 본다. 비ASCII 값은 HTTP 헤더로 만들 수 없어 예외가 되고, 쓰레기 값마다 Auth 왕복이 생기는 것도 막는다.
# 길이 4096은 브라우저 쿠키 크기 한계(약 4KB)와 맞춘 값이다.
_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_MAX_TOKEN_LENGTH = 4096

# 재시도하면 풀릴 수 있는 응답. 그 밖의 4xx는 키·권한·주소 설정 오류로 본다.
_TRANSIENT_STATUSES = frozenset({408, 425, 429})

# 버킷 이름은 주소 경로에 그대로 들어간다. 영문·숫자·`.`·`_`·`-`만 받고 `.`·`..`는 막는다.
_BUCKET_SHAPE = re.compile(r"(?!\.{1,2}$)[A-Za-z0-9._-]+")


class SupabaseUnavailable(Exception):
    """연결 실패, 시간 초과, 5xx. main.py의 처리기가 503으로 바꾼다."""


class SupabaseConfigError(Exception):
    """환경변수가 없거나 키 권한이 거부됐다. main.py의 처리기가 500으로 바꾼다."""


class AuthCreationUncertain(SupabaseUnavailable):
    """Auth 생성 결과를 확인하지 못했다. 이 요청이 정한 ID만 복구 대상으로 쓴다."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__("auth creation outcome unknown")


class AuthRateLimited(Exception):
    def __init__(self, retry_after: str | None):
        # 초 형식과 HTTP-date 모두 허용한다. 누락·비정상 값은 60초 안내로 대체한다.
        seconds = 60
        if retry_after:
            try:
                seconds = int(retry_after)
            except ValueError:
                try:
                    deadline = parsedate_to_datetime(retry_after)
                    seconds = ceil((deadline - datetime.now(timezone.utc)).total_seconds())
                except (ValueError, TypeError, OverflowError):
                    pass
        self.retry_after_seconds = max(1, min(seconds, 2147483647))
        super().__init__("auth rate limited")


class EmailExists(Exception):
    """Auth가 같은 이메일의 기존 계정을 확인했다."""


class AccountInputRejected(Exception):
    """Auth의 입력 거절. 외부 오류 원문 대신 필드 이름만 보관한다."""

    def __init__(self, field: str):
        self.field = field
        super().__init__(field)


@dataclass(frozen=True)
class Profile:
    role: str
    is_active: bool
    display_name: str | None = None


@dataclass(frozen=True)
class AuthSession:
    """Auth가 발급한 세션. 토큰은 쿠키에만 담고 응답 본문·로그에는 남기지 않는다."""

    access_token: str
    refresh_token: str
    user_id: str
    # 액세스 토큰이 유효한 초
    expires_in: int


# 사용자 쪽 거절(비밀번호 틀림·무효 토큰·끊긴 세션)이 올 수 있는 상태. 404는 넣지 않는다(주소 설정 오류).
_AUTH_REJECTED = frozenset({400, 401, 403, 422})
# 거절 상태로 오지만 사용자 잘못이 아니라 프로젝트 설정 문제인 Auth 오류 코드.
# 예: 이메일 로그인이 꺼져 있으면 422 email_provider_disabled가 온다(supabase/config.toml [auth.email]).
_AUTH_CONFIG_ERRORS = frozenset({"email_provider_disabled", "provider_disabled"})


def _auth_error_code(response: httpx.Response) -> str | None:
    """Auth 오류 본문의 error_code. 본문이 JSON이 아니면 None이다. 메시지 원문은 쓰지 않는다."""
    try:
        code = response.json().get("error_code")
    except (ValueError, AttributeError):
        return None
    return code if isinstance(code, str) else None


def _is_user_rejection(response: httpx.Response, operation: str, extra: frozenset[int] = frozenset()) -> bool:
    """Auth가 이 사용자·토큰을 거절했으면 True, 거절이 아니면 False다. 설정 오류면 예외를 낸다.

    Auth 서버의 거절에는 늘 error_code가 있다(invalid_credentials, bad_jwt, session_not_found,
    refresh_token_not_found 등, 2026-10-29 로컬 Auth로 확인). 게이트웨이가 API 키를 거절하면
    error_code 없이 401 {"message": "Invalid API key"}가 온다(staging으로 확인). 이것을 사용자 거절로
    보면 키가 틀렸을 때 모든 로그인이 "비밀번호 틀림"이 되고 모든 세션 쿠키가 지워지므로 설정 오류로 낸다.
    """
    if response.status_code not in _AUTH_REJECTED and response.status_code not in extra:
        return False
    code = _auth_error_code(response)
    if code is None or code in _AUTH_CONFIG_ERRORS:
        raise SupabaseConfigError(f"auth {operation} status {response.status_code} error_code {code or '-'}")
    return True


class SupabaseClient:
    def __init__(
        self, url: str, secret_key: str, http: httpx.Client | None = None, note_image_bucket: str | None = None
    ):
        self._url = url.rstrip("/")
        self._secret_key = secret_key
        self._http = http or httpx.Client(timeout=_TIMEOUT)
        self._note_image_bucket = note_image_bucket

    @classmethod
    def from_env(cls) -> "SupabaseClient":
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SECRET_KEY")
        if not url or not key:
            raise SupabaseConfigError("SUPABASE_URL or SUPABASE_SECRET_KEY is not set")
        # 이미지가 있는 노트를 읽을 때만 필요하다. 비어 있어도 앱은 뜨고 그때 500이 된다(2026-10-30 결정).
        return cls(url, key, note_image_bucket=os.environ.get("NOTE_IMAGE_BUCKET", "").strip() or None)

    def _headers(self, bearer: str | None = None) -> dict[str, str]:
        return {"apikey": self._secret_key, "Authorization": f"Bearer {bearer or self._secret_key}"}

    def _request(self, method: str, path: str, *, preserve_rate_limit: bool = False, **kwargs: Any) -> httpx.Response:
        try:
            response = self._http.request(method, f"{self._url}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise SupabaseUnavailable(type(exc).__name__) from None
        if preserve_rate_limit and response.status_code == 429:
            raise AuthRateLimited(response.headers.get("Retry-After"))
        if response.status_code >= 500 or response.status_code in _TRANSIENT_STATUSES:
            raise SupabaseUnavailable(f"status {response.status_code}")
        return response

    def get_auth_user_id(self, access_token: str) -> str | None:
        """토큰이 살아 있는 세션이면 사용자 id를, 아니면 None을 돌려준다.

        Auth 서버가 세션 유무까지 확인하므로 로그아웃·회수로 끊은 세션이 바로 거부된다.
        """
        if len(access_token) > _MAX_TOKEN_LENGTH or not _TOKEN_SHAPE.fullmatch(access_token):
            return None
        response = self._request("GET", "/auth/v1/user", headers=self._headers(access_token))
        if _is_user_rejection(response, "user"):
            return None
        if response.status_code != 200:
            raise SupabaseUnavailable(f"status {response.status_code}")
        try:
            return str(uuid.UUID(str(response.json().get("id"))))
        except (ValueError, AttributeError):
            return None

    def _token_grant(self, grant_type: str, body: dict[str, str], forwarded_for: str | None) -> AuthSession | None:
        headers = self._headers()
        if forwarded_for:
            # Auth의 IP별 제한이 서버 IP 하나에 몰리지 않게 사용자 IP를 넘긴다. secret key로 부를 때만 쓰이고,
            # 프로젝트 설정(Authentication > Rate Limits > IP Address Forwarding)을 켜야 반영된다.
            headers["Sb-Forwarded-For"] = forwarded_for
        response = self._request("POST", "/auth/v1/token", params={"grant_type": grant_type}, json=body, headers=headers)
        if _is_user_rejection(response, f"token {grant_type}"):
            return None
        if response.status_code != 200:
            # 5xx·일시 상태는 _request가 이미 SupabaseUnavailable로 바꿨다. 남은 4xx는 키·주소 설정 오류다.
            raise SupabaseConfigError(f"auth token {grant_type} status {response.status_code}")
        try:
            data = response.json()
            return AuthSession(
                access_token=str(data["access_token"]),
                refresh_token=str(data["refresh_token"]),
                user_id=str(uuid.UUID(str(data["user"]["id"]))),
                expires_in=int(data["expires_in"]),
            )
        except (ValueError, KeyError, TypeError):
            # 200인데 세션 모양이 아니면 Auth 쪽 이상이다. 본문 원문은 남기지 않는다.
            raise SupabaseUnavailable("malformed auth response") from None

    def sign_in_with_password(
        self, email: str, password: str, forwarded_for: str | None = None
    ) -> AuthSession | None:
        """맞으면 새 세션, 계정 없음·비밀번호 틀림이면 None이다. 둘을 구분하지 않는다."""
        return self._token_grant("password", {"email": email, "password": password}, forwarded_for)

    def refresh_session(self, refresh_token: str, forwarded_for: str | None = None) -> AuthSession | None:
        """리프레시 토큰으로 새 세션을 받는다. 만료·폐기된 토큰이면 None이다.

        Auth는 리프레시 토큰을 한 번 쓰면 새 토큰으로 바꾼다. 새 토큰을 쿠키에 저장하지 못하고 옛 토큰을
        다시 쓰면 Auth가 재사용으로 보고 세션 전체를 끊을 수 있다.
        """
        return self._token_grant("refresh_token", {"refresh_token": refresh_token}, forwarded_for)

    def sign_out(self, access_token: str) -> bool:
        """이 세션 하나(scope=local)를 끊는다. 이미 끊겼거나 토큰이 무효면 False다."""
        if len(access_token) > _MAX_TOKEN_LENGTH or not _TOKEN_SHAPE.fullmatch(access_token):
            return False
        response = self._request(
            "POST", "/auth/v1/logout", params={"scope": "local"}, headers=self._headers(access_token)
        )
        if response.status_code in (200, 204):
            return True
        # 404: 사용자가 이미 없다(user_not_found)
        if _is_user_rejection(response, "logout", extra=frozenset({404})):
            return False
        raise SupabaseConfigError(f"auth logout status {response.status_code}")

    def _select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        response = self._request("GET", f"/rest/v1/{table}", params=params, headers=self._headers())
        if response.status_code != 200:
            # 키·권한 설정 오류(RLS·GRANT)는 응답에 원인을 담지 않고 500으로 낸다.
            raise SupabaseConfigError(f"{table} select status {response.status_code}")
        return response.json()

    def create_auth_user(self, email: str, password: str) -> str:
        """운영자 발급 계정을 만든다. 이메일 확인 메일·초대 메일은 보내지 않는다."""
        user_id = str(uuid.uuid4())
        try:
            response = self._request(
                "POST", "/auth/v1/admin/users", headers=self._headers(), preserve_rate_limit=True,
                json={"id": user_id, "email": email, "password": password, "email_confirm": True},
            )
        except SupabaseUnavailable:
            # 5xx·응답 유실은 서버에서 커밋됐을 수 있다. 새 POST를 자동 재시도하지 않는다.
            raise AuthCreationUncertain(user_id) from None
        if response.status_code in (400, 422):
            code = _auth_error_code(response)
            if code == "email_exists":
                raise EmailExists()
            if code in ("email_address_invalid", "email_address_not_authorized"):
                raise AccountInputRejected("email")
            if code == "weak_password":
                raise AccountInputRejected("initial_password")
        if response.status_code in (401, 403):
            raise SupabaseConfigError("auth create permission denied")
        if response.status_code not in (200, 201):
            raise SupabaseUnavailable(f"auth create status {response.status_code}")
        try:
            returned_id = str(uuid.UUID(str(response.json()["id"])))
            if returned_id != user_id:
                raise ValueError("unexpected user id")
            return user_id
        except (ValueError, KeyError, TypeError):
            raise AuthCreationUncertain(user_id) from None

    def create_member_profile(self, user_id: str, display_name: str) -> None:
        response = self._request(
            "POST", "/rest/v1/profiles",
            headers={**self._headers(), "Prefer": "return=minimal"},
            json={"user_id": str(uuid.UUID(user_id)), "role": "member",
                  "is_active": True, "display_name": display_name},
        )
        if response.status_code != 201:
            raise SupabaseConfigError(f"profiles insert status {response.status_code}")

    def delete_auth_user(self, user_id: str) -> None:
        """발급 중 부분 실패를 보상한다. 일반 계정 회수 API로 노출하지 않는다."""
        response = self._request(
            "DELETE", f"/auth/v1/admin/users/{uuid.UUID(user_id)}",
            headers=self._headers(), json={"should_soft_delete": False},
        )
        if response.status_code not in (200, 204):
            raise SupabaseUnavailable(f"auth delete status {response.status_code}")

    def get_profile(self, user_id: str) -> Profile | None:
        """profiles 행이 없으면 None이다. user_id는 UUID 형식으로 검증한 값만 받는다."""
        user_id = str(uuid.UUID(user_id))
        rows = self._select(
            "profiles", {"user_id": f"eq.{user_id}", "select": "role,is_active,display_name", "limit": "1"}
        )
        if not rows:
            return None
        row = rows[0]
        return Profile(role=row["role"], is_active=bool(row["is_active"]), display_name=row.get("display_name"))

    def list_subjects(self) -> list[dict[str, Any]]:
        """과목 전체(id, name)를 id 오름차순으로 준다."""
        return self._select("subjects", {"select": "id,name", "order": "id.asc"})

    def list_notes(self, include_unpublished: bool) -> list[dict[str, Any]]:
        """노트 목록 열과 연결된 과목 id(note_subjects)를 E04 정렬로 준다.

        include_unpublished가 False면 공개 노트만 DB에서 거르고 운영자 열(is_published·revision·needs_review)도
        읽지 않는다. 쪽 나누기가 없어 API 최대 행(config.toml max_rows = 1000)을 넘으면 조용히 잘린다(1.5).
        """
        columns = "id,title,studied_on,parent_note_id,note_subjects(subject_id)"
        params = {"order": "studied_on.desc.nullslast,id.desc"}
        if include_unpublished:
            columns += ",is_published,revision,needs_review"
        else:
            params["is_published"] = "eq.true"
        return self._select("notes", {"select": columns, **params})

    def get_note(self, note_id: int, include_unpublished: bool) -> dict[str, Any] | None:
        """E05 노트 한 개와 연결된 과목·출처·이미지 행. 없거나 볼 수 없으면 None이다.

        include_unpublished가 False면 공개 노트만 DB에서 거른다. 비공개 열(memo 등)은 읽지 않는다.
        """
        params = {
            "id": f"eq.{int(note_id)}",
            "select": (
                "id,revision,title,studied_on,body_markdown,"
                "note_subjects(subjects(id,name)),note_sources(id,url,label),"
                "note_images(notion_block_id,storage_path,alt)"
            ),
            "limit": "1",
        }
        if not include_unpublished:
            params["is_published"] = "eq.true"
        rows = self._select("notes", params)
        return rows[0] if rows else None

    def list_glossary_terms(self) -> list[dict[str, Any]]:
        """사전 용어(glossary_entries 행이 있는 terms, S8)의 id·key·label. API 최대 행(1000)을 넘으면 잘린다."""
        return self._select("terms", {"select": "id,key,label,glossary_entries!inner(term_id)", "order": "id.asc"})

    def sign_note_images(self, paths: list[str], expires_in: int) -> dict[str, str]:
        """노트 이미지 비공개 버킷의 서명 URL을 한 번에 받는다. 파일이 없어 발급되지 않은 경로는 결과에서 빠진다.

        버킷 이름은 NOTE_IMAGE_BUCKET이다. 없거나 모양이 틀리면 설정 오류(500)다.
        """
        bucket = self._note_image_bucket
        if not bucket or not _BUCKET_SHAPE.fullmatch(bucket):
            raise SupabaseConfigError("NOTE_IMAGE_BUCKET is not set or invalid")
        response = self._request(
            "POST",
            f"/storage/v1/object/sign/{bucket}",
            json={"expiresIn": expires_in, "paths": paths},
            headers=self._headers(),
        )
        if response.status_code != 200:
            # 버킷 없음·키 권한 거부. 5xx·일시 상태는 _request가 이미 SupabaseUnavailable로 바꿨다.
            raise SupabaseConfigError(f"storage sign status {response.status_code}")
        try:
            items = [(item["path"], item.get("signedURL"), item.get("error")) for item in response.json()]
        except (ValueError, KeyError, TypeError, AttributeError):
            raise SupabaseUnavailable("malformed storage response") from None
        signed = {}
        for path, signed_path, error in items:
            url = self._signed_url(signed_path) if not error and isinstance(signed_path, str) else None
            # 발급되지 않았거나 모양이 이상한 항목은 그 이미지만 뺀다. 호출 쪽이 빠진 수를 로그에 남긴다.
            if url is not None:
                signed[path] = url
        return signed

    def _signed_url(self, signed_path: str) -> str | None:
        """Storage의 서명 경로(/object/sign/{버킷}/{경로}?token=...)를 브라우저가 열 수 있는 주소로 만든다.

        Storage는 경로를 인코딩하지 않고 준다(공백·`?`·`&`가 그대로 온다, 2026-10-30 로컬 확인). 토큰 앞의
        마지막 `?`에서 나눠 경로만 인코딩한다. 토큰은 base64url이라 그대로 둔다.
        """
        path, separator, query = signed_path.rpartition("?")
        if not separator or not query.startswith("token="):
            return None
        return f"{self._url}/storage/v1{quote(path, safe='/')}?{query}"

    def keyed_hash(self, value: str) -> str:
        """이메일·IP 같은 원문 대신 저장할 키. secret key로 서명한 해시라 값을 되돌려 추측하기 어렵다."""
        return hmac.new(self._secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]

    def rpc(self, name: str, payload: dict[str, Any]) -> Any:
        response = self._request("POST", f"/rest/v1/rpc/{name}", json=payload, headers=self._headers())
        # 반환값이 없는(void) 함수는 PostgREST가 204(본문 없음)나 빈 200으로 응답한다.
        if response.status_code not in (200, 204):
            raise SupabaseConfigError(f"rpc {name} status {response.status_code}")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()


_client: SupabaseClient | None = None


def get_supabase() -> SupabaseClient:
    """FastAPI 의존성. 시험은 dependency_overrides로 바꾼다."""
    global _client
    if _client is None:
        _client = SupabaseClient.from_env()
    return _client
