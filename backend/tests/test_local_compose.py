import json
import subprocess

import pytest

from scripts import local_compose as compose
from scripts import local_backend as local


def test_rejects_unverified_environment_before_network_inspection(monkeypatch):
    def reject():
        raise local.SetupError('remote rejected')
    monkeypatch.setattr(local, 'load_environment', reject)
    monkeypatch.setattr(local, 'run', lambda *a: pytest.fail('must not inspect'))
    with pytest.raises(local.SetupError):
        compose.configure()


def test_network_mismatch_never_writes_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(local, 'LOCAL', tmp_path)
    monkeypatch.setattr(local, 'load_environment', lambda: None)
    monkeypatch.setattr(local, 'run', lambda *a: json.dumps({'other-project': {}}))
    with pytest.raises(local.SetupError):
        compose.configure()
    assert not (tmp_path / 'compose-backend.env').exists()


def test_backend_receives_only_required_local_values(monkeypatch, tmp_path):
    monkeypatch.setattr(local, 'LOCAL', tmp_path)
    monkeypatch.setattr(local, 'load_environment', lambda: None)
    monkeypatch.setattr(local, 'project_id', lambda: 'isolated')
    monkeypatch.setattr(local, 'run', lambda *a: json.dumps({'supabase_network_isolated': {}}))
    monkeypatch.setenv('SUPABASE_SECRET_KEY', 'synthetic-test-key')
    monkeypatch.setenv('LOCAL_TEST_PASSWORD', 'must-not-be-forwarded')
    compose.configure()
    content = (tmp_path / 'compose-backend.env').read_text()
    assert 'http://supabase_kong_isolated:8000' in content
    assert 'must-not-be-forwarded' not in content
    assert len(content.splitlines()) == 3


def test_compose_ignores_inherited_project_and_override_files(monkeypatch):
    monkeypatch.setattr(local, 'docker_local', lambda: None)
    monkeypatch.setenv('COMPOSE_FILE', 'unrelated.yaml')
    monkeypatch.setenv('COMPOSE_PROJECT_NAME', 'other')
    monkeypatch.setenv('LOCAL_SUPABASE_NETWORK', 'remote')
    def run(args, **kw):
        assert '--project-name' in args and '--file' in args
        assert not any(k.startswith('COMPOSE_') for k in kw['env'])
        assert kw['env']['LOCAL_SUPABASE_NETWORK'] == f'supabase_network_{local.project_id()}'
        assert '-v' not in args and '--volumes' not in args
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(compose.subprocess, 'run', run)
    compose.invoke('down')


def test_compose_failure_hides_output(monkeypatch):
    monkeypatch.setattr(local, 'docker_local', lambda: None)
    monkeypatch.setattr(compose.subprocess, 'run', lambda *a, **kw:
        subprocess.CompletedProcess([], 1, stdout='secret-value', stderr='secret-value'))
    with pytest.raises(local.SetupError, match='Compose failed') as result:
        compose.invoke('up')
    assert 'secret-value' not in str(result.value)


@pytest.mark.parametrize('command', ['setup', 'up'])
def test_existing_environment_is_not_reseeded(monkeypatch, tmp_path, command):
    monkeypatch.setattr(local, 'LOCAL', tmp_path)
    (tmp_path / '.env').write_text('synthetic')
    monkeypatch.setattr(compose.sys, 'argv', ['local_compose', command])
    monkeypatch.setattr(local, 'config', lambda: {})
    monkeypatch.setattr(local, 'cli', lambda *a: '')
    monkeypatch.setattr(local, 'fixture', lambda: pytest.fail('existing data must remain'))
    monkeypatch.setattr(compose, 'configure', lambda: None)
    monkeypatch.setattr(compose, 'invoke', lambda *a: None)
    compose.main()


def test_stop_orders_apps_before_db_and_never_removes_volumes(monkeypatch):
    calls = []
    monkeypatch.setattr(compose.sys, 'argv', ['local_compose', 'stop'])
    monkeypatch.setattr(local, 'config', lambda: {})
    monkeypatch.setattr(compose, 'invoke', lambda *a: calls.append(a))
    monkeypatch.setattr(local, 'cli', lambda *a: calls.append(a))
    compose.main()
    assert calls == [('down',), ('stop',)]


def test_fresh_setup_prepares_checks_then_starts_apps(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(local, 'LOCAL', tmp_path / 'new')
    monkeypatch.setattr(compose.sys, 'argv', ['local_compose', 'setup', '--base-port', '57320'])
    monkeypatch.setattr(local, 'prepare', lambda port: calls.append(('prepare', port)))
    monkeypatch.setattr(local, 'config', lambda: {})
    monkeypatch.setattr(local, 'cli', lambda *a: calls.append(('db', a[0])))
    monkeypatch.setattr(local, 'fixture', lambda: calls.append('fixture'))
    monkeypatch.setattr(local, 'check', lambda: calls.append('check'))
    monkeypatch.setattr(compose, 'configure', lambda: calls.append('configure'))
    monkeypatch.setattr(compose, 'invoke', lambda *a: calls.append(('compose', a[0])))
    compose.main()
    assert calls == [('prepare', 57320), ('db', 'start'), 'fixture', 'check', 'configure', ('compose', 'up')]
