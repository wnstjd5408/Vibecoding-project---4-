"""공통 계층 시험용 앱과 가짜 Supabase. 네트워크·DB 없이 돈다."""

import hashlib
from dataclasses import dataclass, field

from fastapi import Depends, FastAPI, Header
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import accounts, notes
from app.auth import SessionUser, get_session_user, require_login, require_operator
from app.common import install_common_layer
from app.config import SESSION_COOKIE
from app.errors import ApiError
from app.rate_limit import RateRule, rate_limited
from app.supabase import AuthSession, Profile, SupabaseUnavailable, get_supabase

ALLOWED_ORIGIN = "http://localhost:5173"
LIMITED_RULE = RateRule("test_limit", 2, 60)


@dataclass
class FakeSupabase:
    # 세션 토큰 -> 사용자 id, 사용자 id -> profiles 행
    sessions: dict[str, str] = field(default_factory=dict)
    profiles: dict[str, Profile] = field(default_factory=dict)
    down: bool = False
    # 고정 시계(UTC 초). 실제 시계를 쓰면 시험이 60초 창 경계에서 간헐적으로 실패한다.
    now: float = 1_700_000_010.0
    rpc_calls: list[tuple[str, dict]] = field(default_factory=list)
    _counters: dict[tuple[str, int], int] = field(default_factory=dict)
    # Auth 흉내: 이메일 -> (비밀번호, 사용자 id). 세션(sid)마다 액세스·리프레시 토큰을 낸다.
    accounts: dict[str, tuple[str, str]] = field(default_factory=dict)
    auth_down: bool = False
    auth_calls: list[str] = field(default_factory=list)
    # Auth 호출마다 넘긴 Sb-Forwarded-For 값
    forwarded: list[str | None] = field(default_factory=list)
    _access_sid: dict[str, int] = field(default_factory=dict)
    _refresh_sid: dict[str, int] = field(default_factory=dict)
    _used_refresh: set[str] = field(default_factory=set)
    _revoked: set[int] = field(default_factory=set)
    _sid_user: dict[int, str] = field(default_factory=dict)
    _serial: int = 0
    # 과목·노트 표 흉내. 노트 행은 표의 열 + subject_ids(note_subjects 연결)다.
    subjects: list[dict] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)
    # list_notes를 부를 때마다 넘긴 include_unpublished 값
    note_queries: list[bool] = field(default_factory=list)
    # E05: 사전 용어(terms + glossary_entries) 행, Storage 노트 이미지 버킷에 있는 경로, 서명 요청 기록
    glossary: list[dict] = field(default_factory=list)
    stored_images: set[str] = field(default_factory=set)
    storage_down: bool = False
    sign_calls: list[tuple[list[str], int]] = field(default_factory=list)
    # get_note를 부를 때마다 넘긴 (note_id, include_unpublished)
    note_reads: list[tuple[int, bool]] = field(default_factory=list)

    def add_user(
        self, token: str, user_id: str, role: str = "member", is_active: bool = True, display_name: str | None = None
    ) -> None:
        self.sessions[token] = user_id
        self.profiles[user_id] = Profile(role=role, is_active=is_active, display_name=display_name)

    def add_account(
        self,
        email: str,
        password: str,
        user_id: str,
        role: str = "member",
        is_active: bool = True,
        display_name: str | None = "Member",
        profile: bool = True,
    ) -> None:
        self.accounts[email] = (password, user_id)
        if profile:
            self.profiles[user_id] = Profile(role=role, is_active=is_active, display_name=display_name)

    def _auth(self, name: str) -> None:
        self.auth_calls.append(name)
        if self.down or self.auth_down:
            raise SupabaseUnavailable("down")

    def _issue(self, sid: int) -> AuthSession:
        self._serial += 1
        access, refresh = f"access.{self._serial}.sig", f"refresh{self._serial}"
        user_id = self._sid_user[sid]
        self.sessions[access] = user_id
        self._access_sid[access] = sid
        self._refresh_sid[refresh] = sid
        return AuthSession(access_token=access, refresh_token=refresh, user_id=user_id, expires_in=3600)

    def sign_in_with_password(self, email: str, password: str, forwarded_for: str | None = None) -> AuthSession | None:
        self._auth("password")
        self.forwarded.append(forwarded_for)
        account = self.accounts.get(email.lower())
        if account is None or account[0] != password:
            return None
        sid = len(self._sid_user) + 1
        self._sid_user[sid] = account[1]
        return self._issue(sid)

    def refresh_session(self, refresh_token: str, forwarded_for: str | None = None) -> AuthSession | None:
        self._auth("refresh")
        self.forwarded.append(forwarded_for)
        sid = self._refresh_sid.get(refresh_token)
        if sid is None or sid in self._revoked:
            return None
        if refresh_token in self._used_refresh:
            # 실제 Auth처럼 이미 쓴 리프레시 토큰을 다시 쓰면 세션 전체를 끊는다.
            self.revoke(sid)
            return None
        self._used_refresh.add(refresh_token)
        return self._issue(sid)

    def sign_out(self, access_token: str) -> bool:
        self._auth("logout")
        sid = self._access_sid.get(access_token)
        if sid is None or sid in self._revoked or access_token not in self.sessions:
            return False
        self.revoke(sid)
        return True

    def revoke(self, sid: int) -> None:
        self._revoked.add(sid)
        for token, token_sid in self._access_sid.items():
            if token_sid == sid:
                self.sessions.pop(token, None)

    def expire_access(self, access_token: str) -> None:
        """액세스 토큰 수명이 끝난 것처럼 Auth가 거절하게 한다. 리프레시 토큰은 그대로다."""
        self.sessions.pop(access_token, None)

    def session_alive(self, access_or_refresh: str) -> bool:
        sid = self._access_sid.get(access_or_refresh) or self._refresh_sid.get(access_or_refresh)
        return sid is not None and sid not in self._revoked

    def get_auth_user_id(self, access_token: str) -> str | None:
        if self.down:
            raise SupabaseUnavailable("down")
        self.auth_calls.append("user")
        return self.sessions.get(access_token)

    def get_profile(self, user_id: str) -> Profile | None:
        if self.down:
            raise SupabaseUnavailable("down")
        return self.profiles.get(user_id)

    def add_note(
        self,
        note_id: int,
        title: str,
        studied_on: str | None,
        subject_ids: list[int],
        is_published: bool = True,
        parent_note_id: int | None = None,
        revision: int = 1,
        needs_review: bool = False,
        body_markdown: str = "",
        sources: list[dict] | None = None,
        images: list[dict] | None = None,
    ) -> None:
        self.notes.append(
            {
                "id": note_id,
                "title": title,
                "studied_on": studied_on,
                "parent_note_id": parent_note_id,
                "is_published": is_published,
                "revision": revision,
                "needs_review": needs_review,
                "subject_ids": subject_ids,
                "body_markdown": body_markdown,
                # note_sources 행(id, url, label)과 note_images 행(notion_block_id, storage_path, alt)
                "sources": sources or [],
                "images": images or [],
            }
        )

    def add_glossary_term(self, term_id: int, key: str, label: str) -> None:
        self.glossary.append({"id": term_id, "key": key, "label": label})

    def list_subjects(self) -> list[dict]:
        if self.down:
            raise SupabaseUnavailable("down")
        return sorted(({"id": s["id"], "name": s["name"]} for s in self.subjects), key=lambda s: s["id"])

    def list_notes(self, include_unpublished: bool) -> list[dict]:
        """SupabaseClient.list_notes와 같은 거르기·열·정렬(studied_on 내림차순, 없으면 뒤, 같으면 id 내림차순)."""
        if self.down:
            raise SupabaseUnavailable("down")
        self.note_queries.append(include_unpublished)
        rows = [n for n in self.notes if include_unpublished or n["is_published"]]
        rows.sort(key=lambda n: n["id"], reverse=True)
        rows.sort(key=lambda n: n["studied_on"] or "", reverse=True)
        columns = ["id", "title", "studied_on", "parent_note_id"]
        if include_unpublished:
            columns += ["is_published", "revision", "needs_review"]
        return [
            {**{c: n[c] for c in columns}, "note_subjects": [{"subject_id": sid} for sid in n["subject_ids"]]}
            for n in rows
        ]

    def get_note(self, note_id: int, include_unpublished: bool) -> dict | None:
        """SupabaseClient.get_note와 같은 거르기와 내장 열(note_subjects·note_sources·note_images)."""
        if self.down:
            raise SupabaseUnavailable("down")
        self.note_reads.append((note_id, include_unpublished))
        names = {s["id"]: s["name"] for s in self.subjects}
        for n in self.notes:
            if n["id"] == note_id and (include_unpublished or n["is_published"]):
                return {
                    **{c: n[c] for c in ("id", "revision", "title", "studied_on", "body_markdown")},
                    "note_subjects": [{"subjects": {"id": sid, "name": names[sid]}} for sid in n["subject_ids"]],
                    "note_sources": list(n["sources"]),
                    "note_images": list(n["images"]),
                }
        return None

    def list_glossary_terms(self) -> list[dict]:
        if self.down:
            raise SupabaseUnavailable("down")
        return sorted(self.glossary, key=lambda t: t["id"])

    def sign_note_images(self, paths: list[str], expires_in: int) -> dict[str, str]:
        """Storage 흉내: 버킷에 없는 경로는 결과에서 빠진다."""
        if self.down or self.storage_down:
            raise SupabaseUnavailable("down")
        self.sign_calls.append((paths, expires_in))
        return {p: f"https://storage.example.test/signed/{p}?token=EXAMPLE_ONLY" for p in paths if p in self.stored_images}

    def keyed_hash(self, value: str) -> str:
        return hashlib.sha256(f"fake-secret:{value}".encode()).hexdigest()[:32]

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def rpc(self, name: str, payload: dict):
        """rate_limit_hit·rate_limit_release와 같은 고정 창 계산."""
        assert name in ("rate_limit_hit", "rate_limit_release")
        if self.down:
            raise SupabaseUnavailable("down")
        self.rpc_calls.append((name, payload))
        window = int(payload["p_window_seconds"])
        start = int(self.now // window)
        counter_key = (payload["p_key"], start)
        if name == "rate_limit_release":
            hits = self._counters.get(counter_key, 0)
            if hits > 1:
                self._counters[counter_key] = hits - 1
            else:
                self._counters.pop(counter_key, None)
            return None
        hits = self._counters.get(counter_key, 0) + 1
        self._counters[counter_key] = hits
        retry_after = max(int((start + 1) * window - self.now) + 1, 1)
        return [{"allowed": hits <= payload["p_limit"], "retry_after_seconds": retry_after}]

    def hits(self, key: str, window: int) -> int:
        return self._counters.get((key, int(self.now // window)), 0)


class Item(BaseModel):
    title: str = Field(min_length=1, max_length=5)
    understanding: int = Field(ge=1, le=5)


class MinItem(BaseModel):
    name: str = Field(min_length=3)


class NonEmptyItem(BaseModel):
    name: str = Field(min_length=1)


class StrictItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str


class PathItem(BaseModel):
    path: str


class Child(BaseModel):
    path: str


class Parent(BaseModel):
    items: list[Child]


def build_app(fake: FakeSupabase) -> FastAPI:
    app = FastAPI()
    install_common_layer(app)
    app.dependency_overrides[get_supabase] = lambda: fake

    @app.get("/api/ping")
    def ping(user: SessionUser | None = Depends(get_session_user)):
        return {"user_id": user.user_id if user else None}

    @app.get("/api/me")
    def me(user: SessionUser = Depends(require_login)):
        return {"user_id": user.user_id, "role": user.role}

    @app.get("/api/operator")
    def operator(user: SessionUser = Depends(require_operator)):
        return {"ok": True}

    @app.api_route("/api/write", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def write():
        return {"ok": True}

    @app.post("/api/items")
    def create_item(item: Item):
        return {"ok": True}

    @app.post("/api/min3")
    def min3(item: MinItem):
        return {"ok": True}

    @app.post("/api/nonempty")
    def nonempty(item: NonEmptyItem):
        return {"ok": True}

    @app.get("/api/header")
    def header(idempotency_key: int = Header()):
        return {"ok": True}

    @app.post("/api/strict")
    def strict(item: StrictItem):
        return {"ok": True}

    @app.post("/api/pathitem")
    def pathitem(item: PathItem):
        return {"ok": True}

    @app.post("/api/parent")
    def parent(item: Parent):
        return {"ok": True}

    @app.get("/api/http/{status}")
    def http_status(status: int):
        raise StarletteHTTPException(status, "internal wording must not leak")

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    @app.get("/api/raise")
    def raise_error(code: str, detail: str | None = None):
        raise ApiError(code, detail or None)

    @app.get("/api/limited", dependencies=[Depends(rate_limited(LIMITED_RULE))])
    def limited():
        return {"ok": True}

    @app.get("/outside")
    def outside():
        return {"ok": True}

    return app


def build_accounts_app(fake: FakeSupabase) -> FastAPI:
    """E01~E03 라우터를 붙인 시험 앱. 세션 의존성을 쓰고 오류를 내는 경로를 하나 더 둔다."""
    app = FastAPI()
    install_common_layer(app)
    app.dependency_overrides[get_supabase] = lambda: fake
    app.include_router(accounts.router)

    @app.get("/api/session-then-404")
    def session_then_404(user: SessionUser | None = Depends(get_session_user)):
        raise ApiError("not_found")

    return app


def build_notes_app(fake: FakeSupabase) -> FastAPI:
    """E04·E05 라우터를 붙인 시험 앱."""
    app = FastAPI()
    install_common_layer(app)
    app.dependency_overrides[get_supabase] = lambda: fake
    app.include_router(notes.router)
    return app


def cookie(token: str) -> dict[str, str]:
    # 요청별 cookies= 인자는 쓰지 않는 방식으로 바뀌고 있어 Cookie 헤더로 보낸다.
    return {"Cookie": f"{SESSION_COOKIE}={token}"}


def origin(value: str = ALLOWED_ORIGIN) -> dict[str, str]:
    return {"Origin": value}
