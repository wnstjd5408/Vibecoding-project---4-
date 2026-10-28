"""공통 계층 시험용 앱과 가짜 Supabase. 네트워크·DB 없이 돈다."""

import hashlib
import time
from dataclasses import dataclass, field

from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import SessionUser, get_session_user, require_login, require_operator
from app.common import install_common_layer
from app.config import SESSION_COOKIE
from app.errors import ApiError
from app.rate_limit import RateRule, rate_limited
from app.supabase import Profile, SupabaseUnavailable, get_supabase

ALLOWED_ORIGIN = "http://localhost:5173"
LIMITED_RULE = RateRule("test_limit", 2, 60)


@dataclass
class FakeSupabase:
    # 세션 토큰 -> 사용자 id, 사용자 id -> profiles 행
    sessions: dict[str, str] = field(default_factory=dict)
    profiles: dict[str, Profile] = field(default_factory=dict)
    down: bool = False
    rpc_calls: list[tuple[str, dict]] = field(default_factory=list)
    _counters: dict[tuple[str, int], int] = field(default_factory=dict)

    def add_user(self, token: str, user_id: str, role: str = "member", is_active: bool = True) -> None:
        self.sessions[token] = user_id
        self.profiles[user_id] = Profile(role=role, is_active=is_active)

    def get_auth_user_id(self, access_token: str) -> str | None:
        if self.down:
            raise SupabaseUnavailable("down")
        return self.sessions.get(access_token)

    def get_profile(self, user_id: str) -> Profile | None:
        if self.down:
            raise SupabaseUnavailable("down")
        return self.profiles.get(user_id)

    def keyed_hash(self, value: str) -> str:
        return hashlib.sha256(f"fake-secret:{value}".encode()).hexdigest()[:32]

    def rpc(self, name: str, payload: dict):
        """rate_limit_hit과 같은 고정 창 계산(p_increment가 false이면 세지 않고 닿았는지만 본다)."""
        assert name == "rate_limit_hit"
        if self.down:
            raise SupabaseUnavailable("down")
        self.rpc_calls.append((name, payload))
        window = int(payload["p_window_seconds"])
        now = time.time()
        start = int(now // window)
        counter_key = (payload["p_key"], start)
        if payload["p_increment"]:
            hits = self._counters.get(counter_key, 0) + 1
            self._counters[counter_key] = hits
            allowed = hits <= payload["p_limit"]
        else:
            allowed = self._counters.get(counter_key, 0) < payload["p_limit"]
        retry_after = max(int((start + 1) * window - now) + 1, 1)
        return [{"allowed": allowed, "retry_after_seconds": retry_after}]


class Item(BaseModel):
    title: str = Field(min_length=1, max_length=5)
    understanding: int = Field(ge=1, le=5)


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


def cookie(token: str) -> dict[str, str]:
    # 요청별 cookies= 인자는 쓰지 않는 방식으로 바뀌고 있어 Cookie 헤더로 보낸다.
    return {"Cookie": f"{SESSION_COOKIE}={token}"}


def origin(value: str = ALLOWED_ORIGIN) -> dict[str, str]:
    return {"Origin": value}
