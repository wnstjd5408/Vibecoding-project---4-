"""MEG-67: opt-in local Supabase integration. Never accepts a remote URL.

Set MEG67_TEST_SUPABASE_URL and MEG67_TEST_SUPABASE_KEY for a disposable local stack.
"""
import os
import secrets
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.supabase import SupabaseClient, get_supabase
from support import origin


@pytest.fixture
def local_accounts():
    url = os.environ.get('MEG67_TEST_SUPABASE_URL')
    key = os.environ.get('MEG67_TEST_SUPABASE_KEY')
    if not url or not key:
        pytest.skip('disposable local Supabase not configured')
    assert urlparse(url).hostname in ('localhost', '127.0.0.1'), 'remote writes forbidden'
    db = SupabaseClient(url, key)
    created = []
    create = db.create_auth_user
    def tracked_create(email, password):
        user_id = create(email, password)
        created.append(user_id)
        return user_id
    db.create_auth_user = tracked_create
    password = secrets.token_urlsafe(24)
    email = f'meg67-operator-{uuid4().hex}@example.com'
    operator_id = db.create_auth_user(email, password)
    response = db._request('POST', '/rest/v1/profiles', headers=db._headers(), json={
        'user_id': operator_id, 'role': 'operator', 'is_active': True, 'display_name': 'Test operator',
    })
    assert response.status_code == 201
    app.dependency_overrides[get_supabase] = lambda: db
    try:
        with TestClient(app, base_url='https://testserver') as operator:
            response = operator.post('/api/auth/login', json={'email': email, 'password': password}, headers=origin())
            assert response.status_code == 200
            yield db, operator, created
    finally:
        app.dependency_overrides.pop(get_supabase, None)
        for user_id in reversed(created):
            response = db._request('GET', f'/auth/v1/admin/users/{user_id}', headers=db._headers())
            if response.status_code == 200:
                db.delete_auth_user(user_id)


def payload():
    return {'email': f'meg67-member-{uuid4().hex}@example.com', 'display_name': 'Integration member',
            'initial_password': secrets.token_urlsafe(24)}


def test_local_issue_login_roles_and_duplicate(local_accounts):
    db, operator, created = local_accounts
    body = payload()
    response = operator.post('/api/admin/users', json=body, headers=origin())
    assert response.status_code == 201
    assert response.json() == {'id': created[-1], 'role': 'member'}
    assert db.get_profile(created[-1]).is_active
    duplicate = operator.post('/api/admin/users', json=body, headers=origin())
    assert duplicate.status_code == 409
    assert duplicate.json()['error']['detail'] == 'email_exists'
    with TestClient(app, base_url='https://testserver') as member:
        assert member.post('/api/admin/users', json=body, headers=origin()).status_code == 401
        login = member.post('/api/auth/login', json={'email': body['email'], 'password': body['initial_password']}, headers=origin())
        assert login.status_code == 200
        assert login.json()['user']['role'] == 'member'
        assert member.get('/api/me').json()['authenticated'] is True
        assert member.post('/api/admin/users', json=body, headers=origin()).status_code == 403


def test_local_profile_constraint_failure_removes_auth_user(local_accounts, monkeypatch):
    db, operator, created = local_accounts
    insert = db.create_member_profile
    # Real REST insert violates the schema check; no shared schema changes are needed.
    monkeypatch.setattr(db, 'create_member_profile', lambda user_id, name: insert(user_id, 'x' * 101))
    response = operator.post('/api/admin/users', json=payload(), headers=origin())
    assert response.status_code == 500
    user_id = created[-1]
    auth = db._request('GET', f'/auth/v1/admin/users/{user_id}', headers=db._headers())
    assert auth.status_code == 404
    assert db.get_profile(user_id) is None


def test_local_weak_password_has_no_account(local_accounts):
    db, operator, created = local_accounts
    count = len(created)
    response = operator.post('/api/admin/users', json={**payload(), 'initial_password': 'x'}, headers=origin())
    assert response.status_code == 422
    assert len(created) == count


def test_local_committed_auth_response_loss_allows_reissue(local_accounts, monkeypatch):
    """Drop a real Auth success response after the server commits the user."""
    import json
    import httpx
    db, operator, created = local_accounts
    class LoseOneResponse(httpx.HTTPTransport):
        lost_id = None
        def handle_request(self, request):
            response = super().handle_request(request)
            if request.method == 'POST' and request.url.path == '/auth/v1/admin/users' and self.lost_id is None:
                assert response.status_code == 200
                self.lost_id = json.loads(request.content)['id']
                response.close()
                raise httpx.ReadTimeout('injected response loss', request=request)
            return response
    transport = LoseOneResponse()
    body = payload()
    with httpx.Client(transport=transport, timeout=5) as http:
        with monkeypatch.context() as patch:
            patch.setattr(db, '_http', http)
            response = operator.post('/api/admin/users', json=body, headers=origin())
            assert response.status_code == 503
            assert transport.lost_id is not None
            assert db._request('GET', f'/auth/v1/admin/users/{transport.lost_id}', headers=db._headers()).status_code == 404
            assert db.get_profile(transport.lost_id) is None
            reissue = operator.post('/api/admin/users', json=body, headers=origin())
            assert reissue.status_code == 201
            assert reissue.json()['id'] != transport.lost_id
            assert db.sign_in_with_password(body['email'], body['initial_password']) is not None
