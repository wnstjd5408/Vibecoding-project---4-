"""Deletion must never reach an unrelated account or an unverified target."""
import httpx
import pytest

from scripts import local_account as account
from scripts.local_backend import SetupError

UID = '17200000-0000-4000-8000-000000000001'


def test_invalid_id_does_not_connect(monkeypatch):
    monkeypatch.setattr(account, 'connection', lambda: pytest.fail('must not connect'))
    with pytest.raises(ValueError):
        account.account('cleanup', '../../users')


def test_target_validation_failure_does_not_send_requests(monkeypatch):
    def reject():
        raise SetupError('remote target rejected')
    monkeypatch.setattr(account, 'connection', reject)
    monkeypatch.setattr(account.httpx, 'Client', lambda **kw: pytest.fail('must not request'))
    with pytest.raises(SetupError):
        account.account('cleanup', UID)


@pytest.mark.parametrize('mismatch', ['email', 'role', 'name', 'missing'])
def test_cleanup_refuses_identity_mismatch(monkeypatch, mismatch):
    calls = []
    def handler(req):
        calls.append(req.method)
        if req.url.path.startswith('/auth'):
            return httpx.Response(200, json={'id': UID, 'email':
                'operator@example.test' if mismatch == 'email' else account.EMAIL})
        profile = {'user_id': UID, 'role': 'operator' if mismatch == 'role' else 'member',
                   'is_active': True, 'display_name': 'other' if mismatch == 'name' else account.DISPLAY_NAME}
        return httpx.Response(200, json=[] if mismatch == 'missing' else [profile])
    original = httpx.Client
    monkeypatch.setattr(account, 'connection', lambda: ('http://127.0.0.1:55321', 'synthetic-key'))
    monkeypatch.setattr(account.httpx, 'Client', lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    with pytest.raises(SetupError):
        account.account('cleanup', UID)
    assert 'DELETE' not in calls
