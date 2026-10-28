"""공통 계층이 읽는 환경변수. 값은 코드·로그·응답에 남기지 않는다."""

import os
import re

# 세션 쿠키 이름. 값은 Supabase 액세스 토큰이다(Q-N10, MEG-62 구현 결정).
SESSION_COOKIE = "cs_session"

DEFAULT_ALLOWED_ORIGINS = "http://localhost:5173"

# 출처는 scheme://host[:port]만 받는다. 경로·질의·와일드카드는 받지 않는다.
_ORIGIN_SHAPE = re.compile(r"https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?|https?://\[[0-9A-Fa-f:]+\](:[0-9]{1,5})?")


class ConfigError(Exception):
    """환경변수 값이 잘못됐다. 앱 시작 때 터져서 잘못된 설정으로 뜨지 않게 한다."""


def allowed_origins() -> frozenset[str]:
    """상태를 바꾸는 요청을 받을 출처. 운영 주소는 ALLOWED_ORIGINS로 넣는다.

    운영(VERCEL_ENV=production)에서 비어 있으면 로컬 주소를 대신 허용하지 않고 시작을 막는다.
    """
    raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if not raw:
        if os.environ.get("VERCEL_ENV") == "production":
            raise ConfigError("ALLOWED_ORIGINS must be set in production")
        raw = DEFAULT_ALLOWED_ORIGINS
    origins = set()
    for item in raw.split(","):
        origin = item.strip().rstrip("/").lower()
        if not origin:
            continue
        if not _ORIGIN_SHAPE.fullmatch(origin):
            # 값 자체는 오류 문구에 넣지 않는다.
            raise ConfigError("ALLOWED_ORIGINS has an invalid entry: expected scheme://host[:port]")
        origins.add(origin)
    if not origins:
        raise ConfigError("ALLOWED_ORIGINS has no usable entry")
    return frozenset(origins)
