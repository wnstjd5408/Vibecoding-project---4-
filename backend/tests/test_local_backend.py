"""Local guide safety boundaries; no Docker, Auth or network is used here."""

import json

import pytest

from scripts import local_backend as dev


@pytest.mark.parametrize('url', [
    'https://project.supabase.co', 'http://localhost:55321', 'http://127.0.0.1.example.com:55321',
    'http://127.0.0.1:55321@remote.test', 'http://127.0.0.1:55321/path',
    'http://127.0.0.1:55321?target=remote', 'http://127.0.0.1:55321#fragment',
    'http://127.0.0.1:99999', 'http://127.0.0.1', 'http://127.0.0.1:0',
    'http://user@127.0.0.1:55321', 'http://[::1]:55321',
])
def test_remote_or_ambiguous_target_rejected(url):
    with pytest.raises(dev.SetupError):
        dev.local_url(url)


def test_remote_environment_rejected_before_cli_or_write(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://remote.supabase.co')
    monkeypatch.setattr(dev, 'config', lambda: {'api': {'port': 55321}})
    monkeypatch.setattr(dev, 'cli', lambda *args: pytest.fail('CLI must not run'))
    with pytest.raises(dev.SetupError):
        dev.fixture()


def test_redirect_response_never_accepted():
    import httpx
    calls = []
    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(302, headers={'Location': 'https://remote.test'})
    with httpx.Client(base_url='http://127.0.0.1:55321', follow_redirects=False,
                      transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(dev.SetupError):
            dev.request(client, 'POST', '/auth/v1/admin/users')
    assert len(calls) == 1


def test_prepare_isolated_config_no_remote_state(tmp_path, monkeypatch):
    import shutil
    source = dev.ROOT / 'supabase'
    shutil.copytree(source, tmp_path / 'supabase', ignore=shutil.ignore_patterns('.temp', '.branches'))
    (tmp_path / 'supabase/.temp').mkdir(exist_ok=True)
    (tmp_path / 'supabase/.temp/project-ref').write_text('do-not-copy')
    monkeypatch.setattr(dev, 'ROOT', tmp_path)
    monkeypatch.setattr(dev, 'LOCAL', tmp_path / '.local-backend')
    dev.prepare(56320)
    conf = dev.config()
    assert conf['api']['port'] == 56321
    assert conf['db']['port'] == 56322
    assert conf['db']['shadow_port'] == 56320
    assert conf['project_id'].startswith('local-handoff-')
    assert not (dev.LOCAL / 'supabase/.temp').exists()
    with pytest.raises(dev.SetupError):
        dev.prepare(57320)


def test_remote_docker_rejected(monkeypatch):
    monkeypatch.delenv('DOCKER_HOST', raising=False)
    monkeypatch.delenv('DOCKER_CONTEXT', raising=False)
    monkeypatch.setattr(dev, 'run', lambda *args: json.dumps([{'Endpoints': {'docker': {'Host': 'ssh://remote'}}}]))
    with pytest.raises(dev.SetupError):
        dev.docker_local()


def test_cli_url_must_match_isolated_config(monkeypatch):
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.setattr(dev, 'config', lambda: {'api': {'port': 55321}})
    monkeypatch.setattr(dev, 'cli', lambda *args: json.dumps({'API_URL': 'http://127.0.0.1:54321'}))
    with pytest.raises(dev.SetupError):
        dev.connection()
