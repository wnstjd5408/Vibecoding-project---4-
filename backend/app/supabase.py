"""Supabase 호출 최소 래퍼. FastAPI만 secret key로 부른다(D-007).

이 파일이 하는 일: 로그인·세션 갱신·로그아웃·세션 토큰 확인(Auth), profiles·과목·노트·사전 용어 조회와 열람 기록(REST),
노트 이미지 서명 URL 발급과 사전 이미지 공개 주소(Storage), SQL 함수 호출(RPC).
"""

import hashlib
import hmac
import logging
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
logger = logging.getLogger("app.supabase")

# E05가 사전 용어를 읽는 한 번의 크기. PostgREST 최대 행(supabase/config.toml max_rows = 1000)과 같아야 한다.
# 서버 최대 행이 이보다 작으면 한 쪽이 덜 차서 읽기가 일찍 끝나 용어가 빠진다(MEG-141).
GLOSSARY_PAGE_SIZE = 1000
# 끝나지 않는 반복을 막는 안전장치. 50쪽 = 5만 용어는 이 학습 도구의 사전 규모(수백~수천)보다 10배 이상 큰 값이며,
# 노트를 열 때마다 이만큼 읽으면 응답이 이미 느려지는 규모라 "그 전에 설계를 다시 보라"는 경보 겸 한도다(근거: MEG-141 측정, 5,000개에서 쪽당 약 35ms).
# 넘으면 일부만 돌려주지 않고 오류로 낸다(링크가 조용히 빠지지 않게).
GLOSSARY_MAX_PAGES = 50

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


def _error_field(response: httpx.Response, key: str) -> str | None:
    """오류 본문(JSON 객체)의 문자열 필드 하나. 본문이 JSON 객체가 아니거나 값이 문자열이 아니면 None이다."""
    try:
        value = response.json().get(key)
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def _auth_error_code(response: httpx.Response) -> str | None:
    """Auth 오류 본문의 error_code. 메시지 원문은 쓰지 않는다."""
    return _error_field(response, "error_code")


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
        self,
        url: str,
        secret_key: str,
        http: httpx.Client | None = None,
        note_image_bucket: str | None = None,
        glossary_image_bucket: str | None = None,
    ):
        self._url = url.rstrip("/")
        self._secret_key = secret_key
        self._http = http or httpx.Client(timeout=_TIMEOUT)
        self._note_image_bucket = note_image_bucket
        self._glossary_image_bucket = glossary_image_bucket

    @classmethod
    def from_env(cls) -> "SupabaseClient":
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SECRET_KEY")
        if not url or not key:
            raise SupabaseConfigError("SUPABASE_URL or SUPABASE_SECRET_KEY is not set")
        # 이미지 버킷은 이미지가 있는 노트·용어를 읽을 때만 필요하다. 비어 있어도 앱은 뜨고 그때 500이 된다
        # (노트 2026-10-30 결정, 사전은 같은 방식).
        return cls(
            url,
            key,
            note_image_bucket=os.environ.get("NOTE_IMAGE_BUCKET", "").strip() or None,
            glossary_image_bucket=os.environ.get("GLOSSARY_IMAGE_BUCKET", "").strip() or None,
        )

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

    def get_admin_note(self, note_id: int) -> dict[str, Any] | None:
        """E15 전용 허용 열. 가져오기 식별자·시각은 읽지 않는다."""
        rows = self._select("notes", {
            "id": f"eq.{int(note_id)}", "limit": "1",
            "select": "id,revision,title,body_markdown,studied_on,study_minutes,importance,understanding,"
                      "needs_review,memo,is_published,parent_note_id,created_at,updated_at,"
                      "note_subjects(subjects(id,name)),note_sources(id,url,label),"
                      "note_images(notion_block_id,storage_path,alt)",
        })
        return rows[0] if rows else None

    def create_note(self, fields: dict[str, Any]) -> dict[str, Any]:
        response = self._request(
            "POST", "/rest/v1/notes", params={"select": "id,revision"}, json=fields,
            headers={**self._headers(), "Prefer": "return=representation"},
        )
        if response.status_code != 201:
            raise SupabaseConfigError(f"notes insert status {response.status_code}")
        return response.json()[0]

    def update_note(self, note_id: int, fields: dict[str, Any], expected_revision: int | None) -> dict[str, Any]:
        result = self.rpc("note_update", {
            "p_note_id": int(note_id), "p_fields": fields, "p_expected_revision": expected_revision,
        })
        if not isinstance(result, dict) or result.get("status") not in ("ok", "not_found", "stale_revision"):
            raise SupabaseConfigError("unexpected note_update result")
        return result

    def _note_bucket(self) -> str:
        bucket = self._note_image_bucket
        if not bucket or not _BUCKET_SHAPE.fullmatch(bucket):
            raise SupabaseConfigError("NOTE_IMAGE_BUCKET is not set or invalid")
        return bucket

    def delete_note(self, note_id: int) -> dict[str, Any]:
        # 커밋 전에 설정을 확인한다. 삭제 작업이 잘못된 버킷으로 기록돼서는 안 된다.
        result = self.rpc("note_delete", {"p_note_id": int(note_id), "p_bucket": self._note_bucket()})
        if not isinstance(result, dict) or result.get("status") not in ("ok", "not_found"):
            raise SupabaseConfigError("unexpected note_delete result")
        return result

    def retry_note_image_deletions(self) -> None:
        """커밋 뒤 오래된 pending부터 최대 100개. 실패하면 남겨 다음 삭제 요청에서 재시도한다.

        노트 버킷만 처리한다. 사전 업로드 보상 작업을 건드리면 진행 중인 업로드를 지울 수 있다.
        """
        bucket = self._note_bucket()
        jobs = self._select("storage_delete_jobs", {
            "bucket": f"eq.{bucket}", "status": "eq.pending", "select": "id,object_path",
            "order": "id.asc", "limit": "100",
        })
        if not jobs:
            return
        response = self._request("DELETE", f"/storage/v1/object/{bucket}",
                                 json={"prefixes": sorted({job["object_path"] for job in jobs})},
                                 headers=self._headers())
        if response.status_code != 200:
            raise SupabaseConfigError(f"storage delete status {response.status_code}")
        ids = ",".join(str(int(job["id"])) for job in jobs)
        done = self._request("PATCH", "/rest/v1/storage_delete_jobs",
                             params={"id": f"in.({ids})", "bucket": f"eq.{bucket}", "status": "eq.pending"},
                             json={"status": "done", "done_at": datetime.now(timezone.utc).isoformat()},
                             headers={**self._headers(), "Prefer": "return=minimal"})
        if done.status_code not in (200, 204):
            raise SupabaseConfigError(f"storage_delete_jobs update status {done.status_code}")

    def list_glossary_terms(self) -> list[dict[str, Any]]:
        """사전 용어(glossary_entries 행이 있는 terms, S8)의 id·key·label을 id 오름차순으로 전부 준다.

        id 기준 키셋 페이지네이션이다: 쪽마다 `id=gt.<앞 쪽의 마지막 id>`와 `limit`을 주고, 한 쪽이 덜 차면 끝이다.
        (offset 방식은 쪽 사이에 행이 바뀌면 건너뛰거나 겹친다. 정렬 키가 고유한 id라 키셋은 누락·중복이 없다.)
        쪽은 GLOSSARY_MAX_PAGES까지 읽는다. 상한만큼 꽉 찬 쪽을 읽은 뒤에는 한 건만 더 읽어 남은 용어가 있는지 확인한다.
        남은 용어가 없으면(정확히 상한에서 끝남) 정상이고, 남아 있으면 **일부만 돌려주지 않고** 오류 로그를 남기며
        SupabaseConfigError로 낸다(500). 일부 용어가 조용히 빠진 채 노트가 열리는 것보다 눈에 띄는 오류가 낫다.
        """
        select = "id,key,label,glossary_entries!inner(term_id)"
        rows: list[dict[str, Any]] = []
        for _ in range(GLOSSARY_MAX_PAGES):
            params = {"select": select, "order": "id.asc", "limit": str(GLOSSARY_PAGE_SIZE)}
            if rows:
                params["id"] = f"gt.{rows[-1]['id']}"
            page = self._select("terms", params)
            rows.extend(page)
            if len(page) < GLOSSARY_PAGE_SIZE:
                return rows
        # 상한만큼 꽉 찬 쪽을 읽었다. 뒤에 용어가 더 있는지 한 건만 확인한다.
        probe = self._select("terms", {"select": select, "order": "id.asc", "limit": "1", "id": f"gt.{rows[-1]['id']}"})
        if not probe:
            return rows
        logger.error("stage=db glossary_terms=%d read %d pages and more terms remain; refusing a partial list", len(rows), GLOSSARY_MAX_PAGES)
        raise SupabaseConfigError(f"glossary terms exceed {GLOSSARY_MAX_PAGES * GLOSSARY_PAGE_SIZE}")

    def get_glossary_entry(self, term_id: int, user_id: str | None = None) -> dict[str, Any] | None:
        """E06 사전 용어 하나: terms 열, 사전 설명, 이미지 행(id 오름차순). 사전 용어가 아니면 None이다.

        glossary_entries가 없는 용어(AI로만 설명된 용어 포함)는 !inner 내장이 행을 거른다(S8).
        glossary_entries는 term_id가 기본 키라 내장 결과가 배열이 아니라 객체 하나다(2026-11-02 로컬 확인).
        user_id를 주면 그 사용자의 즐겨찾기 행만 favorites 배열로 함께 읽는다(빈 배열이면 즐겨찾기 아님).
        한 번의 요청으로 끝내 로그인 사용자의 바텀시트 열기가 DB 왕복을 두 번 하지 않게 한다.
        """
        select = "id,key,label,glossary_entries!inner(body_markdown),glossary_images(id,storage_path,alt)"
        params = {"id": f"eq.{int(term_id)}", "glossary_images.order": "id.asc", "limit": "1"}
        if user_id is not None:
            select += ",favorites(term_id)"
            params["favorites.user_id"] = f"eq.{uuid.UUID(user_id)}"
        rows = self._select("terms", {**params, "select": select})
        return rows[0] if rows else None

    def record_term_view(self, user_id: str, term_id: int, study_date: str) -> bool:
        """term_views에 (사용자, 용어, KST 날짜) 한 건을 넣는다. 이미 있으면 그대로 둔다(기본 키 충돌 무시).

        넣었거나 이미 있었으면 True, 용어가 없어 외래 키(term_views_term_id_fkey)에 걸렸으면 False다.
        사용자 쪽 외래 키(profiles 행이 그 사이 지워짐) 같은 다른 거절은 설정 오류(500)로 낸다.
        """
        user_id = str(uuid.UUID(user_id))
        response = self._request(
            "POST",
            "/rest/v1/term_views",
            json={"user_id": user_id, "term_id": int(term_id), "study_date": study_date},
            headers={**self._headers(), "Prefer": "resolution=ignore-duplicates,return=minimal"},
        )
        if response.status_code in (200, 201, 204):
            return True
        # 제약 이름은 v05 마이그레이션이 만든 기본 이름이다. 마이그레이션에서 이 외래 키 이름을 바꾸면
        # 없는 용어가 404가 아니라 500이 되므로 여기와 시험(TERM_FK)을 함께 고친다.
        if (
            response.status_code == 409
            and _error_field(response, "code") == "23503"
            and "term_views_term_id_fkey" in (_error_field(response, "message") or "")
        ):
            return False
        raise SupabaseConfigError(f"term_views insert status {response.status_code}")

    def favorite_term(self, user_id: str, term_id: int, study_date: str) -> bool:
        """E08 favorited: true. favorite_events(그날 한 건)와 favorites 한 건을 넣는다. 둘 다 기본 키 충돌은 무시한다.

        favorite_events를 먼저 넣는다. 중간에 실패해도 남는 것은 "즐겨찾기가 아닌데 그날 퀴즈 후보에 남는 용어"뿐이라
        해제해도 후보에 남는 규칙(D-043)과 어긋나지 않는다. 반대 순서면 "즐겨찾기인데 후보에 없는 용어"가 생긴다.
        둘 다 충돌을 무시하므로 같은 요청을 다시 보내면 이어서 끝난다.

        넣었거나 이미 있었으면 True, 용어가 없어 외래 키에 걸렸으면 False다. 사용자 쪽 외래 키(profiles 행이 그 사이
        지워짐) 같은 다른 거절은 설정 오류(500)로 낸다. 제약 이름은 v05 마이그레이션의 기본 이름이다. 바꾸면 없는 용어가
        404가 아니라 500이 되므로 여기와 시험을 함께 고친다.
        """
        user_id = str(uuid.UUID(user_id))
        steps = (
            ("favorite_events", {"user_id": user_id, "term_id": int(term_id), "study_date": study_date},
             "favorite_events_term_id_fkey"),
            ("favorites", {"user_id": user_id, "term_id": int(term_id)}, "favorites_term_id_fkey"),
        )
        for table, payload, term_fk in steps:
            response = self._request(
                "POST",
                f"/rest/v1/{table}",
                json=payload,
                headers={**self._headers(), "Prefer": "resolution=ignore-duplicates,return=minimal"},
            )
            if response.status_code in (200, 201, 204):
                continue
            if (
                response.status_code == 409
                and _error_field(response, "code") == "23503"
                and term_fk in (_error_field(response, "message") or "")
            ):
                return False
            raise SupabaseConfigError(f"{table} insert status {response.status_code}")
        return True

    def unfavorite_term(self, user_id: str, term_id: int) -> bool:
        """E08 favorited: false. favorites에서 그 사용자의 그 용어 행만 지운다. favorite_events는 지우지 않는다.

        용어가 있으면 True다(즐겨찾기가 아니었어도 같다). 없으면 False다. 지운 행이 없을 때만 terms를 읽어 "즐겨찾기가
        아니었던 용어"와 "없는 용어"를 가른다.
        """
        user_id = str(uuid.UUID(user_id))
        response = self._request(
            "DELETE",
            "/rest/v1/favorites",
            params={"user_id": f"eq.{user_id}", "term_id": f"eq.{int(term_id)}", "select": "term_id"},
            headers={**self._headers(), "Prefer": "return=representation"},
        )
        if response.status_code != 200:
            raise SupabaseConfigError(f"favorites delete status {response.status_code}")
        if response.json():
            return True
        return bool(self._select("terms", {"id": f"eq.{int(term_id)}", "select": "id", "limit": "1"}))

    def report_target_exists(self, target_type: str, target_id: int, user_id: str) -> bool:
        """E10: 신고할 수 있는 대상인지. 그 사용자가 신고할 수 있는 것만 True다(없는 것과 볼 수 없는 것을 구분하지 않는다).

        ai_explanation은 지금 유효한(invalidated_at이 null) 공유 설명이다. term_id가 없는 설명은 이미 무효화된 것이다.
        quiz_item은 그 사용자 자신의 퀴즈 세트의 문항이다. 남의 문항은 없는 문항과 같다.
        """
        user_id = str(uuid.UUID(user_id))
        if target_type == "ai_explanation":
            rows = self._select(
                "ai_explanations",
                {"id": f"eq.{int(target_id)}", "invalidated_at": "is.null", "select": "id", "limit": "1"},
            )
        elif target_type == "quiz_item":
            rows = self._select(
                "quiz_items",
                {
                    "id": f"eq.{int(target_id)}",
                    "quiz_sets.user_id": f"eq.{user_id}",
                    "select": "id,quiz_sets!inner(user_id)",
                    "limit": "1",
                },
            )
        else:
            raise ValueError(f"unknown report target type: {target_type}")
        return bool(rows)

    def create_report(
        self, user_id: str, target_type: str, target_id: int, body: str
    ) -> tuple[dict[str, Any], bool] | None:
        """E10: 신고를 한 건 넣는다. (행, 새로 만들었는지)를 돌려준다. 대상이 그 사이 지워졌으면 None이다.

        같은 사용자·같은 대상의 열린 신고가 이미 있으면 부분 유일 인덱스(reports_open_*_idx)가 막는다. 이때 새 행 없이
        기존 열린 신고를 읽어 (행, False)로 돌려준다. 막 처리돼 열린 신고가 사라진 경합이면 한 번 더 넣어 본다.
        제약 이름은 v05·v06 마이그레이션의 이름이다. 바꾸면 이 판정이 틀어지므로 여기와 시험을 함께 고친다.
        """
        user_id = str(uuid.UUID(user_id))
        column = "ai_explanation_id" if target_type == "ai_explanation" else "quiz_item_id"
        payload = {"user_id": user_id, column: int(target_id), "body": body}
        for _ in range(2):
            response = self._request(
                "POST",
                "/rest/v1/reports",
                params={"select": "id,status"},
                json=payload,
                headers={**self._headers(), "Prefer": "return=representation"},
            )
            if response.status_code == 201:
                return response.json()[0], True
            code, message = _error_field(response, "code"), _error_field(response, "message") or ""
            if response.status_code == 409 and code == "23503" and f"reports_{column}_fkey" in message:
                return None
            if response.status_code == 409 and code == "23505" and "reports_open_" in message:
                rows = self._select(
                    "reports",
                    {"user_id": f"eq.{user_id}", column: f"eq.{int(target_id)}", "status": "eq.open",
                     "select": "id,status", "limit": "1"},
                )
                if rows:
                    return rows[0], False
                continue
            raise SupabaseConfigError(f"reports insert status {response.status_code}")
        # 두 번 연달아 같은 경합이면 사용자 입력이나 설정 문제가 아니다. 다시 보내 볼 수 있게 503으로 낸다.
        raise SupabaseUnavailable("reports insert kept conflicting without an open report")

    def list_admin_reports(self, status: str, limit: int, before_id: int | None) -> list[dict[str, Any]]:
        """E25: status가 같은 신고를 id 내림차순으로 limit개까지 준다. 신고자(user_id)는 읽지도 내지도 않는다(1.9).

        before_id를 주면 그보다 작은 id만 준다(cursor = 앞 쪽의 마지막 id, API spec 1.5). 대상(AI 설명·퀴즈 문항)은
        한 번의 요청으로 함께 읽어 target 요약(종류별 열)으로 바꾼다. 대상 행이 없으면(외래 키가 막는 일이라 생기지 않아야
        한다) 목록을 조용히 줄이지 않고 설정·무결성 오류로 낸다.
        """
        if status not in ("open", "resolved"):
            raise ValueError(f"unknown report status: {status}")
        params = {
            "status": f"eq.{status}",
            "select": "id,status,body,ai_explanation_id,quiz_item_id,"
            "ai_explanations(term_key_snapshot,body),quiz_items(question,answer)",
            "order": "id.desc",
            "limit": str(int(limit)),
        }
        if before_id is not None:
            params["id"] = f"lt.{int(before_id)}"
        reports = []
        for row in self._select("reports", params):
            if row["ai_explanation_id"] is not None:
                explanation = row.get("ai_explanations")
                if not explanation:
                    raise SupabaseConfigError("report without its ai explanation")
                target = {
                    "type": "ai_explanation",
                    "id": row["ai_explanation_id"],
                    "term_key_snapshot": explanation["term_key_snapshot"],
                    "body": explanation["body"],
                }
            else:
                item = row.get("quiz_items")
                if not item:
                    raise SupabaseConfigError("report without its quiz item")
                target = {"type": "quiz_item", "id": row["quiz_item_id"], "question": item["question"], "answer": item["answer"]}
            reports.append({"id": row["id"], "status": row["status"], "body": row["body"], "target": target})
        return reports

    def get_admin_report(self, report_id: int) -> dict[str, Any] | None:
        """E26: 신고의 status와 AI 설명 대상 id만 읽는다. 없으면 None이다(AI 설명이 대상이 아니면 ai_explanation_id는 None)."""
        rows = self._select(
            "reports", {"id": f"eq.{int(report_id)}", "select": "id,status,ai_explanation_id", "limit": "1"}
        )
        return rows[0] if rows else None

    def invalidate_ai_explanation(self, explanation_id: int) -> int:
        """E26: AI 설명 하나를 무효화한다(invalidated_at 채움). 이미 무효화됐으면 0을 돌려준다. 행은 지우지 않는다.

        기존 SQL 함수(ai_invalidate_explanations, 마이그레이션 20261102120000)를 설명 id 하나로 부른다.
        """
        result = self.rpc(
            "ai_invalidate_explanations",
            {"p_note_id": None, "p_term_id": None, "p_explanation_id": int(explanation_id)},
        )
        return int(result or 0)

    def mark_report_resolved(self, report_id: int, resolved_at: str) -> bool:
        """E26: 열린 신고를 처리됨으로 바꾸고 처리 시각을 채운다. 바꾼 행이 있으면 True다.

        status가 open인 행만 조건에 건다. 이미 처리된 신고의 처리 시각을 덮어쓰지 않고, 그때는 False를 돌려준다.
        """
        response = self._request(
            "PATCH",
            "/rest/v1/reports",
            params={"id": f"eq.{int(report_id)}", "status": "eq.open", "select": "id"},
            json={"status": "resolved", "resolved_at": resolved_at},
            headers={**self._headers(), "Prefer": "return=representation"},
        )
        if response.status_code != 200:
            raise SupabaseConfigError(f"reports update status {response.status_code}")
        return bool(response.json())

    def get_note_for_explain(self, note_id: int, include_unpublished: bool) -> dict[str, Any] | None:
        """E09가 읽는 노트의 열(id, revision, is_published, body_markdown). 없거나 볼 수 없으면 None이다.

        include_unpublished가 False면 공개 노트만 DB에서 거른다(비공개 노트는 없는 노트와 같다). 이미지·과목 행은
        읽지 않는다.
        """
        params = {
            "id": f"eq.{int(note_id)}",
            "select": "id,revision,is_published,body_markdown",
            "limit": "1",
        }
        if not include_unpublished:
            params["is_published"] = "eq.true"
        rows = self._select("notes", params)
        return rows[0] if rows else None

    def find_term_for_explain(self, key: str, user_id: str) -> dict[str, Any] | None:
        """E09 5.5절 7·8단계를 한 번에 읽는다: key가 같은 용어와 그 사전 설명·이미지, 유효한 AI 설명, 내 즐겨찾기.

        glossary_entries는 사전 용어일 때만 객체이고 아니면 null이다. ai_explanations는 무효화되지 않은 행만
        배열로 온다(용어당 하나). favorites는 세션 사용자의 행만 온다. 용어가 없으면 None이다.
        """
        select = (
            "id,key,label,source,glossary_entries(body_markdown),glossary_images(id,storage_path,alt),"
            "ai_explanations(id,body,review_status),favorites(term_id)"
        )
        params = {
            "key": f"eq.{key}",
            "select": select,
            "glossary_images.order": "id.asc",
            "ai_explanations.invalidated_at": "is.null",
            "favorites.user_id": f"eq.{uuid.UUID(user_id)}",
            "limit": "1",
        }
        rows = self._select("terms", params)
        return rows[0] if rows else None

    def list_ledger_rows(self, user_id: str, request_key: str) -> list[dict[str, Any]]:
        """한 요청({request_key}:{attempt_no})의 원장 행(status, attempt_no, created_at). E09의 멱등 키 확인에 쓴다.

        request_key는 서버가 UUID 두 개로 만든 값이라 like 패턴의 특수 문자가 들어 있지 않다. user_id로도 거른다
        (남의 행을 보지 않는다).
        """
        return self._select(
            "ai_usage_ledger",
            {
                "user_id": f"eq.{uuid.UUID(user_id)}",
                "idempotency_key": f"like.{request_key}:*",
                "select": "status,attempt_no,created_at",
                "order": "attempt_no.asc",
            },
        )

    def store_ai_explanation(self, **arguments: Any) -> dict[str, Any]:
        """ai_store_explanation 함수를 부른다(5.5절 11~12단계). 결과 한 행을 out_ 접두사 없이 돌려준다."""
        rows = self.rpc("ai_store_explanation", {f"p_{name}": value for name, value in arguments.items()})
        row = rows[0] if isinstance(rows, list) else rows
        return {name.removeprefix("out_"): value for name, value in row.items()}

    def get_quiz_set(self, user_id: str, quiz_date: str) -> dict[str, Any] | None:
        """E11: 그 사용자의 그날 세트 행(id, status, attempt, lease_expires_at). 없으면 None이다. 날짜는 KST ISO 문자열이다."""
        rows = self._select(
            "quiz_sets",
            {
                "user_id": f"eq.{uuid.UUID(user_id)}",
                "quiz_date": f"eq.{quiz_date}",
                "select": "id,status,attempt,lease_expires_at",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def list_quiz_source_terms(self, user_id: str, source_date: str, previous_quiz_date: str) -> dict[str, list[int]]:
        """E11 6.2절 후보의 재료. 어제 연 용어(viewed), 어제 즐겨찾기한 용어(favorited), 전날 세트에 나온 용어(excluded)의 id.

        즐겨찾기는 favorite_events라서 나중에 해제해도 남는다. 전날 세트는 quiz_date = 어제인 그 사용자의 세트다.
        용어가 지워져 term_id가 null인 문항은 건너뛴다. 모두 id 오름차순이다. 쪽 나누기가 없어 API 최대 행(max_rows = 1000)을
        넘으면 조용히 잘린다. 한 사용자가 하루에 그만큼 용어를 여는 일은 예상하지 않는다(1.5와 같은 한계).
        """
        user = f"eq.{uuid.UUID(user_id)}"
        day = {"user_id": user, "study_date": f"eq.{source_date}", "select": "term_id", "order": "term_id.asc"}
        excluded: list[int] = []
        previous_set = self.get_quiz_set(user_id, previous_quiz_date)
        if previous_set is not None:
            excluded = [
                int(row["term_id"])
                for row in self._select(
                    "quiz_items",
                    {
                        "set_id": f"eq.{int(previous_set['id'])}",
                        "term_id": "not.is.null",
                        "select": "term_id",
                        "order": "term_id.asc",
                    },
                )
            ]
        return {
            "viewed": [int(row["term_id"]) for row in self._select("term_views", day)],
            "favorited": [int(row["term_id"]) for row in self._select("favorite_events", day)],
            "excluded": excluded,
        }

    def list_quiz_terms(self, term_ids: list[int]) -> list[dict[str, Any]]:
        """후보 용어와 문항의 자료. 사전 설명(glossary_entries, 사전 용어일 때만 객체)과 유효한 AI 설명(배열)을 함께 준다."""
        if not term_ids:
            return []
        ids = ",".join(str(int(term_id)) for term_id in term_ids)
        return self._select(
            "terms",
            {
                "id": f"in.({ids})",
                "select": "id,key,label,glossary_entries(body_markdown),ai_explanations(body)",
                "ai_explanations.invalidated_at": "is.null",
                "order": "id.asc",
            },
        )

    def list_quiz_items(self, set_id: int) -> list[dict[str, Any]]:
        """한 세트의 문항을 id 순으로 준다. 정답·해설과 이 사용자의 답·꼬리 질문 행을 함께 읽는다(응답에서 가려낸다)."""
        return self._select(
            "quiz_items",
            {
                "set_id": f"eq.{int(set_id)}",
                "select": "id,difficulty,question,answer,explanation,"
                "quiz_answers(user_answer),quiz_followups(seq,question,user_answer)",
                "order": "id.asc",
                "quiz_followups.order": "seq.asc",
            },
        )

    def store_quiz_items(self, set_id: int, attempt: int, items: list[dict[str, Any]]) -> str:
        """quiz_store_items 함수를 부른다(6.4절 7번). 'stored' 또는 'stale'(선점이 바뀌어 저장하지 않음)이다."""
        result = self.rpc("quiz_store_items", {"p_set_id": set_id, "p_attempt": attempt, "p_items": items})
        if result not in ("stored", "stale"):
            raise SupabaseConfigError("rpc quiz_store_items returned an unexpected value")
        return result

    def get_quiz_item_for_answer(self, user_id: str, item_id: int) -> dict[str, Any] | None:
        """E12·E14: 그 사용자 자신의 퀴즈 세트의 문항. 남의 문항은 없는 문항과 같게 None이다.

        정답·해설·난이도와 이 사용자의 답(quiz_answers, 없으면 null), 꼬리 질문 슬롯 전부(seq 순)를 함께 읽는다.
        """
        rows = self._select(
            "quiz_items",
            {
                "id": f"eq.{int(item_id)}",
                "quiz_sets.user_id": f"eq.{uuid.UUID(user_id)}",
                "select": "id,difficulty,answer,explanation,quiz_sets!inner(user_id),"
                "quiz_answers(user_answer),quiz_followups(seq,question,user_answer)",
                "quiz_followups.order": "seq.asc",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def save_quiz_answer(self, item_id: int, answer: str) -> str | None:
        """E12: 답을 한 건 넣는다. 저장돼 있는 답을 돌려준다(내가 넣었으면 내 답, 먼저 있었으면 그 답).

        기본 키(item_id) 충돌은 무시하고 저장된 행을 읽는다. 호출한 쪽이 내 답과 같은지 비교해 같으면 200, 다르면 409로
        낸다(API spec 1.4.4). 문항이 그 사이 지워졌으면 None이다. 외래 키 이름은 v05 마이그레이션의 기본 이름이다.
        """
        response = self._request(
            "POST",
            "/rest/v1/quiz_answers",
            params={"select": "user_answer"},
            json={"item_id": int(item_id), "user_answer": answer},
            headers={**self._headers(), "Prefer": "resolution=ignore-duplicates,return=representation"},
        )
        if response.status_code == 409:
            if _error_field(response, "code") == "23503" and "quiz_answers_item_id_fkey" in (
                _error_field(response, "message") or ""
            ):
                return None
            raise SupabaseConfigError("quiz_answers insert status 409")
        if response.status_code not in (200, 201):
            raise SupabaseConfigError(f"quiz_answers insert status {response.status_code}")
        inserted = response.json()
        if inserted:
            return inserted[0]["user_answer"]
        # 충돌로 무시됐다. 먼저 저장된 답을 읽는다.
        rows = self._select("quiz_answers", {"item_id": f"eq.{int(item_id)}", "select": "user_answer", "limit": "1"})
        return rows[0]["user_answer"] if rows else None

    def save_followup_answer(self, item_id: int, seq: int, answer: str) -> str | None:
        """E14: 질문이 만들어져 있고 아직 답이 없는 슬롯에만 답을 넣는다. 저장돼 있는 답을 돌려준다.

        조건부 갱신이라 먼저 저장된 답을 덮어쓰지 않는다. 갱신된 행이 없으면 슬롯을 읽어, 이미 답이 있으면 그 답을 돌려주고
        (호출한 쪽이 비교한다), 슬롯이 없거나 질문이 아직 없으면 None이다.
        """
        key = {"item_id": f"eq.{int(item_id)}", "seq": f"eq.{int(seq)}"}
        response = self._request(
            "PATCH",
            "/rest/v1/quiz_followups",
            params={**key, "question": "not.is.null", "user_answer": "is.null", "select": "user_answer"},
            json={"user_answer": answer},
            headers={**self._headers(), "Prefer": "return=representation"},
        )
        if response.status_code != 200:
            raise SupabaseConfigError(f"quiz_followups update status {response.status_code}")
        updated = response.json()
        if updated:
            return updated[0]["user_answer"]
        rows = self._select("quiz_followups", {**key, "select": "question,user_answer", "limit": "1"})
        if not rows or not rows[0]["question"]:
            return None
        if rows[0]["user_answer"] is None:
            # 갱신 조건을 만족하는데 갱신되지 않았다. 다시 보내 볼 수 있게 503으로 낸다.
            raise SupabaseUnavailable("quiz_followups update matched no row for an unanswered slot")
        return rows[0]["user_answer"]

    def get_quiz_item_for_followup(self, user_id: str, item_id: int) -> dict[str, Any] | None:
        """E13: 그 사용자 자신의 퀴즈 문항. 남의 문항은 없는 문항과 같게 None이다.

        꼬리 질문을 만들 재료(문제·정답·해설·내 답)와 꼬리 질문 슬롯 전부(seq 순)를 함께 읽는다. 슬롯에는 예약 시각(created_at)이
        있어 질문이 비어 있는 오래된 슬롯을 가려낼 수 있다(API spec S4).
        """
        rows = self._select(
            "quiz_items",
            {
                "id": f"eq.{int(item_id)}",
                "quiz_sets.user_id": f"eq.{uuid.UUID(user_id)}",
                "select": "id,question,answer,explanation,quiz_sets!inner(user_id),"
                "quiz_answers(user_answer),quiz_followups(seq,question,user_answer,created_at)",
                "quiz_followups.order": "seq.asc",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def reserve_followup_slot(self, item_id: int, seq: int) -> bool | None:
        """E13: (item_id, seq) 슬롯을 비워 둔 채로 넣어 번호를 예약한다. 예약했으면 True다.

        같은 슬롯이 이미 있으면(다른 요청이 먼저 예약) 기본 키 충돌이라 False다. 문항이 그 사이 지워졌으면 None이다.
        제약 이름은 v05 마이그레이션의 기본 이름이다. 바꾸면 이 판정이 틀어지므로 여기와 시험을 함께 고친다.
        """
        response = self._request(
            "POST",
            "/rest/v1/quiz_followups",
            json={"item_id": int(item_id), "seq": int(seq)},
            headers={**self._headers(), "Prefer": "return=minimal"},
        )
        if response.status_code in (200, 201, 204):
            return True
        code, message = _error_field(response, "code"), _error_field(response, "message") or ""
        if response.status_code == 409 and code == "23505" and "quiz_followups_pkey" in message:
            return False
        if response.status_code == 409 and code == "23503" and "quiz_followups_item_id_fkey" in message:
            return None
        raise SupabaseConfigError(f"quiz_followups insert status {response.status_code}")

    def fill_followup_slot(self, item_id: int, seq: int, question: str) -> bool:
        """E13: 예약한 슬롯에 질문을 채운다. 질문이 비어 있는 슬롯에만 하므로 채웠으면 True, 슬롯이 없어졌으면 False다."""
        response = self._request(
            "PATCH",
            "/rest/v1/quiz_followups",
            params={"item_id": f"eq.{int(item_id)}", "seq": f"eq.{int(seq)}", "question": "is.null", "select": "seq"},
            json={"question": question},
            headers={**self._headers(), "Prefer": "return=representation"},
        )
        if response.status_code != 200:
            raise SupabaseConfigError(f"quiz_followups update status {response.status_code}")
        return bool(response.json())

    def release_followup_slot(self, item_id: int, seq: int) -> None:
        """E13: 실패한 예약을 지워 번호를 돌려준다. 질문도 답도 없는 슬롯만 지운다(이미 채워진 슬롯은 건드리지 않는다)."""
        response = self._request(
            "DELETE",
            "/rest/v1/quiz_followups",
            params={
                "item_id": f"eq.{int(item_id)}",
                "seq": f"eq.{int(seq)}",
                "question": "is.null",
                "user_answer": "is.null",
            },
            headers={**self._headers(), "Prefer": "return=minimal"},
        )
        if response.status_code not in (200, 204):
            raise SupabaseConfigError(f"quiz_followups delete status {response.status_code}")

    def delete_stale_followup_slot(self, item_id: int, seq: int, created_before: str) -> bool:
        """E13(S4): 함수가 죽어 질문 없이 남은 오래된 슬롯을 지운다. created_before(UTC ISO) 이전에 예약한 빈 슬롯만 지운다.

        지웠으면 True다. 그 사이 질문이 채워졌거나 다시 예약됐다면 조건에 맞지 않아 False다.
        """
        response = self._request(
            "DELETE",
            "/rest/v1/quiz_followups",
            params={
                "item_id": f"eq.{int(item_id)}",
                "seq": f"eq.{int(seq)}",
                "question": "is.null",
                "user_answer": "is.null",
                "created_at": f"lt.{created_before}",
                "select": "seq",
            },
            headers={**self._headers(), "Prefer": "return=representation"},
        )
        if response.status_code != 200:
            raise SupabaseConfigError(f"quiz_followups delete status {response.status_code}")
        return bool(response.json())

    def release_quiz_claim(self, set_id: int, attempt: int) -> None:
        """생성에 실패한 선점을 풀어 다음 호출이 바로 다시 선점하게 한다(failed, 선점 만료 시각 없음).

        내 attempt이고 아직 generating인 행만 바꾼다. 그 사이 다른 요청이 다시 선점했거나 ready가 됐다면 건드리지 않는다.
        시도 횟수(attempt)는 그대로라서 2회를 다 쓰면 다음 선점 함수가 failed로 끝낸다.
        """
        response = self._request(
            "PATCH",
            "/rest/v1/quiz_sets",
            params={"id": f"eq.{int(set_id)}", "attempt": f"eq.{int(attempt)}", "status": "eq.generating"},
            json={"status": "failed", "lease_expires_at": None},
            headers={**self._headers(), "Prefer": "return=minimal"},
        )
        if response.status_code not in (200, 204):
            raise SupabaseConfigError(f"quiz_sets update status {response.status_code}")

    def _glossary_bucket(self) -> str:
        bucket = self._glossary_image_bucket
        if not bucket or not _BUCKET_SHAPE.fullmatch(bucket):
            raise SupabaseConfigError("GLOSSARY_IMAGE_BUCKET is not set or invalid")
        return bucket

    def glossary_image_url(self, storage_path: str) -> str:
        """사전 이미지 공개 버킷의 주소(기술 검토 Q7 결정 (a), 2026-11-02). 발급 요청 없이 만든다.

        버킷 이름은 GLOSSARY_IMAGE_BUCKET이다. 없거나 모양이 틀리면 설정 오류(500)다. 주소 안에 버킷 이름과
        경로가 들어가는 것은 E06의 예외로 받아들였다(2026-11-02 김준성, API spec 1.9·10.5).
        경로에 빈 구간·`.`·`..`가 있으면 브라우저가 주소를 정규화해 다른 버킷을 가리킬 수 있어 설정 오류로 막는다.
        """
        bucket = self._glossary_bucket()
        if any(segment in ("", ".", "..") for segment in storage_path.split("/")):
            raise SupabaseConfigError("glossary image storage_path has an empty or dot segment")
        return f"{self._url}/storage/v1/object/public/{bucket}/{quote(storage_path, safe='/')}"

    # --- E19~E23 운영자 사전 (MEG-81). 여러 문장을 묶는 쓰기는 SQL 함수(마이그레이션 20261102160000)로 한다. ---

    def list_admin_glossary_terms(self, limit: int, before_id: int | None) -> list[dict[str, Any]]:
        """사전 용어(glossary_entries 행이 있는 terms)의 id·key·label을 id 내림차순으로 limit개까지 준다.

        before_id를 주면 그보다 작은 id만 준다(cursor = 앞 쪽의 마지막 id, API spec 1.5).
        """
        params = {
            "select": "id,key,label,glossary_entries!inner(term_id)",
            "order": "id.desc",
            "limit": str(int(limit)),
        }
        if before_id is not None:
            params["id"] = f"lt.{int(before_id)}"
        return [{"id": row["id"], "key": row["key"], "label": row["label"]} for row in self._select("terms", params)]

    def glossary_entry_exists(self, term_id: int) -> bool:
        rows = self._select("glossary_entries", {"select": "term_id", "term_id": f"eq.{int(term_id)}", "limit": "1"})
        return bool(rows)

    def upsert_glossary_entry(self, key: str, label: str, body_markdown: str, updated_by: str) -> dict[str, Any]:
        """E20. {"id", "key", "label", "created"}를 준다. 같은 용어의 AI 설명 무효화까지 한 트랜잭션이다."""
        result = self.rpc(
            "glossary_upsert_entry",
            {"p_key": key, "p_label": label, "p_body_markdown": body_markdown,
             "p_updated_by": str(uuid.UUID(updated_by))},
        )
        if not isinstance(result, dict):
            raise SupabaseConfigError("rpc glossary_upsert_entry returned an unexpected shape")
        return result

    def delete_glossary_entry(self, term_id: int) -> list[dict[str, Any]] | None:
        """E21. 사전 용어가 아니면 None, 맞으면 객체를 지울 삭제 작업 목록 [{"job_id", "object_path"}]이다."""
        result = self.rpc("glossary_delete_entry", {"p_term_id": int(term_id), "p_bucket": self._glossary_bucket()})
        if result is None:
            return None
        return list(result["jobs"])

    def delete_glossary_image(self, term_id: int, image_id: int) -> dict[str, Any] | None:
        """E23. 그 용어의 이미지가 아니면 None, 맞으면 삭제 작업 {"job_id", "object_path"}이다."""
        return self.rpc(
            "glossary_delete_image",
            {"p_term_id": int(term_id), "p_image_id": int(image_id), "p_bucket": self._glossary_bucket()},
        )

    def create_glossary_upload_job(self, object_path: str) -> int:
        """E22 1단계. 올리기 전에 삭제 작업(pending)을 넣는다. 도중에 멈추면 이 작업이 남아 객체를 지울 대상이 된다."""
        response = self._request(
            "POST",
            "/rest/v1/storage_delete_jobs",
            json={"bucket": self._glossary_bucket(), "object_path": object_path},
            headers={**self._headers(), "Prefer": "return=representation"},
            params={"select": "id"},
        )
        if response.status_code != 201:
            raise SupabaseConfigError(f"storage_delete_jobs insert status {response.status_code}")
        return int(response.json()[0]["id"])

    def upload_glossary_image(self, object_path: str, data: bytes, content_type: str) -> None:
        """E22 2단계. 같은 경로가 있으면 덮어쓰지 않고 실패한다. 연결 실패·5xx는 SupabaseUnavailable(503)이다."""
        bucket = self._glossary_bucket()
        response = self._request(
            "POST",
            f"/storage/v1/object/{bucket}/{quote(object_path, safe='/')}",
            content=data,
            headers={**self._headers(), "Content-Type": content_type, "x-upsert": "false"},
        )
        if response.status_code != 200:
            # 버킷 없음·크기·형식 제한·키 권한. 앱이 먼저 검사하므로 나오면 설정 문제다.
            raise SupabaseConfigError(f"storage upload status {response.status_code}")

    def add_glossary_image(self, term_id: int, object_path: str, alt: str | None, job_id: int) -> int | None:
        """E22 3단계. 이미지 행을 넣고 1단계 작업을 지운다. 그 사이 사전 설명이 지워졌으면 None이다."""
        result = self.rpc(
            "glossary_add_image",
            {"p_term_id": int(term_id), "p_storage_path": object_path, "p_alt": alt, "p_job_id": int(job_id)},
        )
        return None if result is None else int(result)

    def remove_glossary_objects(self, jobs: list[dict[str, Any]]) -> None:
        """삭제 작업의 객체를 지우고 작업을 done으로 바꾼다. 실패하면 예외를 내고 작업은 pending으로 남는다."""
        if not jobs:
            return
        bucket = self._glossary_bucket()
        response = self._request(
            "DELETE",
            f"/storage/v1/object/{bucket}",
            json={"prefixes": [job["object_path"] for job in jobs]},
            headers=self._headers(),
        )
        if response.status_code != 200:
            raise SupabaseConfigError(f"storage delete status {response.status_code}")
        ids = ",".join(str(int(job["job_id"])) for job in jobs)
        done = self._request(
            "PATCH",
            "/rest/v1/storage_delete_jobs",
            params={"id": f"in.({ids})", "status": "eq.pending"},
            json={"status": "done", "done_at": datetime.now(timezone.utc).isoformat()},
            headers={**self._headers(), "Prefer": "return=minimal"},
        )
        if done.status_code not in (200, 204):
            raise SupabaseConfigError(f"storage_delete_jobs update status {done.status_code}")

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
