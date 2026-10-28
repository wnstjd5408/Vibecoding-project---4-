"""공통 계층이 읽는 환경변수. 값은 코드·로그·응답에 남기지 않는다."""

import os

# 세션 쿠키 이름. 값은 Supabase 액세스 토큰이다(Q-N10, MEG-62 구현 결정).
SESSION_COOKIE = "cs_session"

DEFAULT_ALLOWED_ORIGINS = "http://localhost:5173"


def allowed_origins() -> frozenset[str]:
    """상태를 바꾸는 요청을 받을 출처. 운영 주소는 ALLOWED_ORIGINS로 넣는다."""
    raw = os.environ.get("ALLOWED_ORIGINS") or DEFAULT_ALLOWED_ORIGINS
    return frozenset(origin.strip().rstrip("/").lower() for origin in raw.split(",") if origin.strip())
