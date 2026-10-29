"""클라이언트 IP. 속도 제한(rate_limit.py)과 Auth 호출(Sb-Forwarded-For)이 같이 쓴다."""

import ipaddress
import os

from starlette.requests import Request

UNKNOWN_IP = "unknown"


def client_ip(request: Request) -> str:
    """클라이언트 IP. 소켓 주소를 쓰고, Vercel 위에서만 Vercel이 넣는 헤더를 믿는다.

    X-Forwarded-For는 클라이언트가 보낸 값이 앞에 붙을 수 있어 쓰지 않는다. x-vercel-forwarded-for도
    Vercel 밖에서는 클라이언트가 위조할 수 있으므로 Vercel 환경(VERCEL 환경변수)에서만 믿는다.
    """
    candidates = []
    if os.environ.get("VERCEL"):
        candidates.append(request.headers.get("x-vercel-forwarded-for", "").split(",")[0].strip())
    if request.client:
        candidates.append(request.client.host)
    for value in candidates:
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            continue
    return UNKNOWN_IP


def ip_bucket(ip: str) -> str:
    """속도 제한 키로 쓸 IP 묶음. IPv6는 /64로 묶는다.

    한 사용자(회선)가 보통 /64 하나를 받아 그 안의 주소를 마음대로 바꿀 수 있어서, 주소 하나씩 세면
    제한을 우회할 수 있다. IPv4와 알 수 없는 값은 그대로 쓴다. IPv4를 담은 IPv6 주소(::ffff:a.b.c.d)는
    IPv4로 푼다. 그대로 /64로 묶으면 모든 IPv4 사용자가 한 묶음(::/64)이 된다.
    """
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if address.version == 6 and address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return ip
