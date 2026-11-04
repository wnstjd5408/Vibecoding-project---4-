"""MEG-54 AC-1: 발급 -> 로그인 -> 로그아웃을 한 번에 잇는 로컬 통합 시험.

MEG67_TEST_SUPABASE_URL, MEG67_TEST_SUPABASE_KEY를 일회용 로컬 Supabase로 설정해야 돈다.
설정이 없으면 건너뛰고, 원격 주소는 fixture가 거부한다. 합성 계정만 만들고 시험 뒤 지운다.
"""
import secrets

from fastapi.testclient import TestClient

from app.config import SESSION_COOKIE
from app.main import app
from support import origin
from test_account_issuance_local import local_accounts, payload  # noqa: F401  (fixture 재사용)


def unique_client_ip():
    """실행마다 다른 문서용 IP(TEST-NET-3). 모든 TestClient가 같은 'unknown' IP 버킷(15분 30회)을 쓰지 않게 한다."""
    return f'203.0.113.{secrets.randbelow(254) + 1}'


def test_local_issue_login_logout_returns_to_visitor(local_accounts):  # noqa: F811
    db, operator, created = local_accounts
    body = payload()

    # 1. 운영자가 계정을 발급한다.
    issued = operator.post('/api/admin/users', json=body, headers=origin())
    assert issued.status_code == 201
    assert issued.json() == {'id': created[-1], 'role': 'member'}
    assert db.get_profile(created[-1]).is_active

    credentials = {'email': body['email'], 'password': body['initial_password']}
    client_ip = unique_client_ip()
    with TestClient(app, base_url='https://testserver', client=(client_ip, 50000)) as member:
        # 2. 발급받은 계정으로 로그인하면 로그인 기능이 열린다.
        assert member.get('/api/me').json() == {'authenticated': False}
        login = member.post('/api/auth/login', json=credentials, headers=origin())
        assert login.status_code == 200
        assert login.json()['user']['role'] == 'member'
        session_cookie = member.cookies.get(SESSION_COOKIE)
        assert session_cookie
        me = member.get('/api/me').json()
        assert me['authenticated'] is True
        assert me['role'] == 'member'

        # 3. 로그아웃하면 방문자로 돌아간다.
        assert member.post('/api/auth/logout', headers=origin()).status_code == 204
        assert member.get('/api/me').json() == {'authenticated': False}
        assert member.post('/api/admin/users', json=payload(), headers=origin()).status_code == 401

        # 4. 로그아웃 전의 세션 쿠키를 그대로 보내도 로그인 상태가 되지 않는다(서버 쪽 세션 폐기).
        with TestClient(app, base_url='https://testserver', client=(client_ip, 50001)) as replay:
            stale = replay.get('/api/me', headers={'Cookie': f'{SESSION_COOKIE}={session_cookie}'})
            assert stale.json() == {'authenticated': False}

        # 5. 계정은 남아 있어 다시 로그인할 수 있다.
        again = member.post('/api/auth/login', json=credentials, headers=origin())
        assert again.status_code == 200
        assert member.get('/api/me').json()['authenticated'] is True
