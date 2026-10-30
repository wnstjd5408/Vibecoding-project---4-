import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.supabase import AccountInputRejected, EmailExists, SupabaseClient, SupabaseUnavailable
from support import FakeSupabase, build_accounts_app, cookie, origin

USER_ID = '00000000-0000-0000-0000-000000000067'
BODY = {'email': 'new@example.com', 'display_name': '새 사용자', 'initial_password': 'synthetic-test-only!'}
PATH = '/api/admin/users'


class IssuanceSupabase(FakeSupabase):
    fail_profile = False
    fail_delete = False
    created = 0
    deleted = 0

    def create_auth_user(self, email, password):
        self._auth('create')
        if email in self.accounts:
            raise EmailExists()
        self.created += 1
        self.accounts[email] = (password, USER_ID)
        return USER_ID

    def create_member_profile(self, user_id, display_name):
        if self.fail_profile:
            raise SupabaseUnavailable(BODY['initial_password'])
        from app.supabase import Profile
        self.profiles[user_id] = Profile('member', True, display_name)

    def delete_auth_user(self, user_id):
        self.deleted += 1
        if self.fail_delete:
            raise SupabaseUnavailable(BODY['initial_password'])
        self.accounts = {k: v for k, v in self.accounts.items() if v[1] != user_id}
        self.profiles.pop(user_id, None)


@pytest.fixture
def setup():
    fake = IssuanceSupabase()
    fake.add_user('operator', str(uuid.uuid4()), 'operator')
    fake.add_user('member', str(uuid.uuid4()))
    fake.add_user('inactive', str(uuid.uuid4()), 'operator', False)
    with TestClient(build_accounts_app(fake), base_url='https://testserver') as client:
        yield fake, client


def issue(client, body=None, token='operator'):
    return client.post(PATH, json=BODY if body is None else body, headers={**origin(), **cookie(token)})


def test_issue_then_login_and_me(setup, caplog):
    fake, client = setup
    response = issue(client)
    assert response.status_code == 201
    assert response.json() == {'id': USER_ID, 'role': 'member'}
    assert response.headers['cache-control'] == 'private, no-store'
    assert fake.profiles[USER_ID].is_active
    client.cookies.clear()
    login = client.post('/api/auth/login', json={'email': BODY['email'], 'password': BODY['initial_password']}, headers=origin())
    assert login.status_code == 200
    assert login.json()['user'] == {'role': 'member', 'display_name': BODY['display_name']}
    assert client.get('/api/me').json()['authenticated'] is True
    assert BODY['initial_password'] not in response.text + caplog.text


@pytest.mark.parametrize('token,status', [('', 401), ('member', 403), ('inactive', 401)])
def test_role_matrix_before_validation(setup, token, status):
    fake, client = setup
    assert issue(client, {}, token).status_code == status
    assert fake.created == 0


def test_origin_before_auth(setup):
    fake, client = setup
    response = client.post(PATH, json=BODY, headers=cookie('operator'))
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'origin_not_allowed'
    assert fake.created == 0


def test_duplicate_does_not_delete_original(setup):
    fake, client = setup
    assert issue(client).status_code == 201
    response = issue(client, {**BODY, 'email': ' NEW@EXAMPLE.COM '})
    assert response.status_code == 409
    assert response.json()['error']['detail'] == 'email_exists'
    assert fake.created == 1 and fake.deleted == 0


@pytest.mark.parametrize('fail_delete', [False, True])
def test_profile_failure_compensates_or_logs_cleanup_id(setup, caplog, fail_delete):
    fake, client = setup
    fake.fail_profile, fake.fail_delete = True, fail_delete
    response = issue(client)
    assert response.status_code == 500
    assert response.json()['error']['code'] == 'internal_error'
    assert fake.deleted == 1
    assert bool(fake.accounts) is fail_delete
    assert (USER_ID in caplog.text) is fail_delete
    if fail_delete:
        assert response.headers['x-request-id'] in caplog.text
    assert BODY['email'] not in caplog.text
    assert BODY['initial_password'] not in response.text + caplog.text
    if not fail_delete:
        fake.fail_profile = False
        assert issue(client).status_code == 201


@pytest.mark.parametrize('change', [
    {'email': 'bad'}, {'display_name': ''}, {'display_name': 'x' * 101},
    {'initial_password': ''}, {'initial_password': '한' * 25},
    {'role': 'operator'}, {'is_active': False},
])
def test_invalid_input_has_no_side_effect(setup, change):
    fake, client = setup
    response = issue(client, {**BODY, **change})
    assert response.status_code == 422
    assert fake.created == 0
    assert BODY['initial_password'] not in response.text


def test_auth_outage_does_not_attempt_profile_or_cleanup(setup):
    fake, client = setup
    fake.auth_down = True
    response = issue(client)
    assert response.status_code == 503
    assert fake.created == fake.deleted == 0


def test_write_limit_prevents_auth_call(setup):
    fake, client = setup
    for _ in range(30):
        issue(client)
    response = issue(client)
    assert response.status_code == 429
    assert int(response.headers['retry-after']) > 0
    assert fake.auth_calls.count('create') == 30


def provider(handler):
    return SupabaseClient('http://localhost', 'synthetic-key', httpx.Client(transport=httpx.MockTransport(handler)))


def test_provider_requests_and_fixed_role(monkeypatch):
    monkeypatch.setattr("app.supabase.uuid.uuid4", lambda: uuid.UUID(USER_ID))
    seen = []
    def handler(request):
        seen.append((request.method, request.url.path, json.loads(request.content)))
        assert request.headers['apikey'] == 'synthetic-key'
        if request.method == 'POST' and request.url.path.endswith('/admin/users'):
            return httpx.Response(200, json={'id': USER_ID})
        return httpx.Response(201 if request.method == 'POST' else 200)
    client = provider(handler)
    assert client.create_auth_user(BODY['email'], BODY['initial_password']) == USER_ID
    client.create_member_profile(USER_ID, BODY['display_name'])
    client.delete_auth_user(USER_ID)
    assert seen == [
        ('POST', '/auth/v1/admin/users', {'id': USER_ID, 'email': BODY['email'], 'password': BODY['initial_password'], 'email_confirm': True}),
        ('POST', '/rest/v1/profiles', {'user_id': USER_ID, 'role': 'member', 'is_active': True, 'display_name': BODY['display_name']}),
        ('DELETE', f'/auth/v1/admin/users/{USER_ID}', {'should_soft_delete': False}),
    ]


@pytest.mark.parametrize('code,exception', [('email_exists', EmailExists), ('weak_password', AccountInputRejected), ('email_address_invalid', AccountInputRejected)])
def test_auth_error_mapping(code, exception):
    client = provider(lambda r: httpx.Response(422, json={'error_code': code, 'msg': BODY['initial_password']}))
    with pytest.raises(exception) as caught:
        client.create_auth_user(BODY['email'], BODY['initial_password'])
    assert BODY['initial_password'] not in str(caught.value)


@pytest.mark.parametrize('body', [{}, {'id': 'bad'}, [], None])
def test_malformed_create_response(body):
    with pytest.raises(SupabaseUnavailable):
        provider(lambda r: httpx.Response(200, json=body)).create_auth_user(BODY['email'], BODY['initial_password'])


def transport_app(handler):
    """Real endpoint and HTTP adapter; only operator identity and local quota are stubbed."""
    from app.auth import SessionUser, require_operator
    from app.rate_limit import get_rate_limiter
    from app.supabase import get_supabase
    fake = FakeSupabase()
    app = build_accounts_app(fake)
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[require_operator] = lambda: SessionUser(USER_ID, 'operator')
    class Limiter:
        def check(self, *args):
            pass
    app.dependency_overrides[get_rate_limiter] = lambda: Limiter()
    db = provider(handler)
    return TestClient(app)


@pytest.mark.parametrize('failure', ['timeout', 'server_error', 'malformed', 'wrong_id'])
def test_committed_auth_response_loss_is_compensated_and_can_be_reissued(failure, caplog):
    users = set()
    attempts, deletions, profiles = [], [], []
    def handler(request):
        if request.method == 'DELETE':
            user_id = request.url.path.rsplit('/', 1)[1]
            deletions.append(user_id)
            users.remove(user_id)
            return httpx.Response(200)
        data = json.loads(request.content)
        if request.url.path == '/auth/v1/admin/users':
            attempts.append(data.get('id'))
            if users:
                return httpx.Response(422, json={'error_code': 'email_exists'})
            users.add(data.get('id'))
            if len(attempts) == 1:
                if failure == 'timeout':
                    raise httpx.ReadTimeout('sensitive upstream text')
                if failure == 'server_error':
                    return httpx.Response(502)
                return httpx.Response(200, json={'id': USER_ID} if failure == 'wrong_id' else {})
            return httpx.Response(200, json={'id': data['id']})
        profiles.append(data['user_id'])
        return httpx.Response(201)
    with transport_app(handler) as client:
        first = issue(client)
        assert first.status_code == 503
        assert not users and not profiles
        assert deletions == [attempts[0]]
        assert attempts[0] in caplog.text
        assert first.headers['x-request-id'] in caplog.text
        second = issue(client)
        assert second.status_code == 201
        assert attempts[1] != attempts[0]
        assert users == set(profiles) == {second.json()['id']}
    assert 'sensitive upstream text' not in caplog.text
    assert BODY['initial_password'] not in caplog.text
    assert BODY['email'] not in caplog.text


@pytest.mark.parametrize('delete_status', [404, 503])
def test_uncertain_cleanup_keeps_id_for_manual_reconciliation(delete_status, caplog):
    ids = []
    def handler(request):
        if request.method == 'POST':
            ids.append(json.loads(request.content).get('id'))
            raise httpx.ReadTimeout('unknown commit outcome')
        assert request.url.path.endswith(ids[0])
        return httpx.Response(delete_status)
    with transport_app(handler) as client:
        response = issue(client)
    assert response.status_code == 503
    assert len(ids) == 1
    assert 'cleanup_unconfirmed' in caplog.text
    assert ids[0] in caplog.text
    assert ids[0] not in response.text
    assert BODY['initial_password'] not in caplog.text


@pytest.mark.parametrize('retry_after,expected', [('30', 30), (None, 60), ('bad', 60), ('-5', 1)])
def test_provider_rate_limit_preserves_contract_and_never_deletes(retry_after, expected):
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(429, headers={'Retry-After': retry_after} if retry_after else {},
                              json={'error_code': 'over_request_rate_limit'})
    with transport_app(handler) as client:
        response = issue(client)
    assert response.status_code == 429
    assert response.json()['error']['code'] == 'rate_limited'
    assert response.json()['error']['retry_after_seconds'] == expected
    assert response.headers['retry-after'] == str(expected)
    assert calls == ['POST']


def test_provider_rate_limit_http_date(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    fixed = datetime(2030, 1, 1, tzinfo=timezone.utc)
    class Clock:
        @staticmethod
        def now(tz):
            return fixed
    monkeypatch.setattr('app.supabase.datetime', Clock)
    deadline = format_datetime(fixed + timedelta(seconds=30), usegmt=True)
    with transport_app(lambda r: httpx.Response(429, headers={'Retry-After': deadline})) as client:
        response = issue(client)
    assert response.status_code == 429
    assert int(response.headers['retry-after']) == 30


def test_real_adapter_duplicate_does_not_delete_existing_user():
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(422, json={'error_code': 'email_exists'})
    with transport_app(handler) as client:
        response = issue(client)
    assert response.status_code == 409
    assert calls == ['POST']
