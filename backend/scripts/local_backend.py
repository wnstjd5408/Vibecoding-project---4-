"""Guide companion: isolated local Supabase, synthetic fixtures and real Auth checks.

Run from backend with `uv run python -m scripts.local_backend --help`.
Never accepts a remote target, prints credentials, or changes product configuration.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tomllib
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local-backend'
CLI = 'supabase@2.121.0'
ACCOUNTS = ('operator', 'member-a', 'member-b', 'inactive')
USER_IDS = {name: f'13200000-0000-4000-8000-{i:012d}' for i, name in enumerate(ACCOUNTS, 1)}


class SetupError(Exception):
    pass


def local_url(value: str) -> str:
    """Literal loopback only; no DNS, credentials, redirects, proxies or remote URL."""
    try:
        u = urlsplit(value)
        valid = (u.scheme == 'http' and u.hostname == '127.0.0.1' and u.port
                 and u.username is None and u.password is None
                 and u.path in ('', '/') and not u.query and not u.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise SetupError('Only http://127.0.0.1:<port> is allowed; no request was sent.')
    return value.rstrip('/')


def run(args: list[str], *, input_text: str | None = None) -> str:
    result = subprocess.run(args, input=input_text, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', cwd=ROOT)
    if result.returncode:
        # CLI status and SQL errors can contain credentials. Never echo captured output.
        raise SetupError(f'{Path(args[0]).stem} failed (exit {result.returncode}); see guide troubleshooting.')
    return result.stdout


def docker_local() -> None:
    if os.environ.get('DOCKER_HOST') or os.environ.get('DOCKER_CONTEXT'):
        raise SetupError('Unset DOCKER_HOST/DOCKER_CONTEXT and select a local Docker context.')
    context = json.loads(run(['docker', 'context', 'inspect']))[0]
    host = context['Endpoints']['docker']['Host']
    if not (host.startswith('npipe://') or host.startswith('unix://')):
        raise SetupError('A local Docker socket is required.')


def cli(*args: str) -> str:
    docker_local()
    npx = shutil.which('npx.cmd' if os.name == 'nt' else 'npx')
    if not npx:
        raise SetupError('Install Node.js 24 (npx required).')
    return run([npx, '--yes', CLI, '--workdir', str(LOCAL), *args])


def project_id() -> str:
    suffix = hashlib.sha256(str(ROOT).encode()).hexdigest()[:10]
    return f'local-handoff-{suffix}'


def config() -> dict:
    path = LOCAL / 'supabase/config.toml'
    if not path.exists():
        raise SetupError('Run prepare first.')
    data = tomllib.loads(path.read_text(encoding='utf-8'))
    if data['project_id'] != project_id():
        raise SetupError('Local project identity mismatch; do not reuse another worktree directory.')
    return data


def prepare(base_port: int) -> None:
    if LOCAL.exists():
        raise SetupError('.local-backend already exists; reuse it or follow the clean restart guide.')
    # Copy only versioned schema/config inputs, never .temp/project-ref or remote credentials.
    source = ROOT / 'supabase'
    text = (source / 'config.toml').read_text(encoding='utf-8')
    text = re.sub(r'^project_id = .*$', f'project_id = "{project_id()}"', text, flags=re.M)
    ports = {54320: base_port, 54321: base_port+1, 54322: base_port+2,
             54323: base_port+3, 54324: base_port+4, 54327: base_port+7, 54329: base_port+9}
    text = re.sub(r'(?m)^(\s*(?:port|shadow_port|smtp_port|pop3_port)\s*=\s*)(\d+)',
                  lambda m: m[1] + str(ports.get(int(m[2]), int(m[2]))), text)
    # This guide needs only Postgres, Auth and REST. Keep other product config intact.
    for section in ('studio', 'inbucket', 'analytics', 'edge_runtime', 'realtime'):
        text = re.sub(r'(\[' + section + r'\]\s*\n)enabled = true', r'\1enabled = false', text)
    target = LOCAL / 'supabase'
    target.mkdir(parents=True)
    (target / 'config.toml').write_text(text, encoding='utf-8')
    shutil.copytree(source / 'migrations', target / 'migrations')
    shutil.copy2(source / 'seed.sql', target / 'seed.sql')
    print(f'Prepared isolated project; API port {base_port+1}. No service started.')


def connection() -> tuple[str, str]:
    expected = f"http://127.0.0.1:{config()['api']['port']}"
    # Reject an inherited remote setting before even asking the CLI for local keys.
    inherited = os.environ.get('SUPABASE_URL')
    if inherited and local_url(inherited) != expected:
        raise SetupError('SUPABASE_URL does not match this isolated project.')
    status = json.loads(cli('status', '-o', 'json'))
    url = local_url(status['API_URL'])
    if url != expected:
        raise SetupError('CLI API URL does not match local config.')
    key = status.get('SERVICE_ROLE_KEY')
    if not key:
        raise SetupError('Local CLI did not return a service-role key.')
    return url, key


def request(client: httpx.Client, method: str, path: str, **kwargs) -> httpx.Response:
    response = client.request(method, path, **kwargs)
    if response.status_code >= 300:
        raise SetupError(f'Local API request failed (HTTP {response.status_code}); response body hidden.')
    return response


def fixture() -> None:
    url, key = connection()
    env_file = LOCAL / '.env'
    if env_file.exists():
        from dotenv import dotenv_values
        password = dotenv_values(env_file).get('LOCAL_TEST_PASSWORD')
        if not password:
            raise SetupError('Local password missing; follow clean restart guide.')
    else:
        password = secrets.token_urlsafe(24)
        with env_file.open('x', encoding='utf-8') as f:
            f.write(f'SUPABASE_URL={url}\nSUPABASE_SECRET_KEY={key}\n'
                    f'LOCAL_TEST_PASSWORD={password}\nALLOWED_ORIGINS=http://localhost:5173\n')
        if os.name != 'nt':
            env_file.chmod(0o600)
    with httpx.Client(base_url=url, headers={'apikey': key, 'Authorization': f'Bearer {key}'},
                      trust_env=False, follow_redirects=False, timeout=15) as client:
        for name, uid in USER_IDS.items():
            response = client.get(f'/auth/v1/admin/users/{uid}')
            body = {'email': f'{name}@example.test', 'password': password, 'email_confirm': True}
            if response.status_code == 404:
                request(client, 'POST', '/auth/v1/admin/users', json={'id': uid, **body})
            elif response.status_code == 200:
                if response.json().get('email') != body['email']:
                    raise SetupError('Fixture user ID collision; no account overwritten.')
                request(client, 'PUT', f'/auth/v1/admin/users/{uid}', json=body)
            else:
                raise SetupError('Cannot inspect local Auth account; response hidden.')
    sql = (ROOT / 'backend/scripts/local_fixture.sql').read_text(encoding='utf-8')
    docker_local()
    run(['docker', 'exec', '-i', f'supabase_db_{project_id()}', 'psql', '-U', 'postgres',
         '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-q'], input_text=sql)
    print('Synthetic fixture restored. Credentials saved only in .local-backend/.env.')


def load_environment() -> None:
    url, key = connection()
    from dotenv import dotenv_values
    values = dotenv_values(LOCAL / '.env')
    if local_url(values.get('SUPABASE_URL', '')) != url or values.get('SUPABASE_SECRET_KEY') != key:
        raise SetupError('Local .env does not match CLI status; recreate using the guide.')
    for name in ('SUPABASE_URL', 'SUPABASE_SECRET_KEY', 'LOCAL_TEST_PASSWORD', 'ALLOWED_ORIGINS'):
        if not values.get(name):
            raise SetupError('Local environment is incomplete.')
        os.environ[name] = values[name]
    # Product HTTP clients also stay off inherited corporate/remote proxies in this process.
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        os.environ.pop(name, None)
    os.environ['NO_PROXY'] = '127.0.0.1,localhost'


def check() -> None:
    load_environment()
    from fastapi.testclient import TestClient
    from app.main import app
    # Real Auth/REST/RPC; HTTPS ASGI origin preserves Secure cookie behavior without a TLS server.
    origin = {'Origin': 'http://localhost:5173'}
    for name in ACCOUNTS:
        with TestClient(app, base_url='https://localhost') as client:
            response = client.post('/api/auth/login', headers=origin,
                                   json={'email': f'{name}@example.test', 'password': os.environ['LOCAL_TEST_PASSWORD']})
            expected = 401 if name == 'inactive' else 200
            if response.status_code != expected:
                raise SetupError(f'Login check failed for {name}: HTTP {response.status_code}.')
            me = client.get('/api/me').json()
            if me.get('authenticated') != (name != 'inactive'):
                raise SetupError(f'Session check failed for {name}.')
            if name != 'inactive':
                if me.get('role') != ('operator' if name == 'operator' else 'member'):
                    raise SetupError('Role mismatch.')
                cookies = response.headers.get_list('set-cookie')
                if len(cookies) != 2 or not all('secure' in c.lower() and 'httponly' in c.lower() for c in cookies):
                    raise SetupError('Secure/HttpOnly cookie check failed.')
                if client.post('/api/auth/logout', headers=origin).status_code != 204:
                    raise SetupError('Logout failed.')
    with TestClient(app, base_url='https://localhost') as client:
        if client.get('/api/me').json() != {'authenticated': False}:
            raise SetupError('Visitor check failed.')
        if client.post('/api/auth/login', json={}).status_code != 403:
            raise SetupError('Origin check failed.')
    url, key = connection()
    counts = {'profiles': 4, 'terms': 5, 'notes': 1, 'ai_explanations': 4,
              'favorites': 2, 'favorite_events': 4, 'quiz_sets': 2, 'quiz_items': 2, 'reports': 6}
    with httpx.Client(base_url=url, headers={'apikey': key, 'Authorization': f'Bearer {key}'},
                      trust_env=False, follow_redirects=False, timeout=15) as client:
        data = {}
        for table, count in counts.items():
            rows = request(client, 'GET', f'/rest/v1/{table}?select=*').json()
            if len(rows) != count:
                raise SetupError(f'{table}: expected {count} rows, got {len(rows)}; restore fixture before checking.')
            data[table] = rows
        expected_profiles = {(USER_IDS[n], 'operator' if n == 'operator' else 'member', n != 'inactive') for n in ACCOUNTS}
        require({(r['user_id'], r['role'], r['is_active']) for r in data['profiles']} == expected_profiles, 'profiles')
        require({(r['user_id'], r['term_id']) for r in data['favorites']} ==
                {(USER_IDS['member-a'], 132001), (USER_IDS['member-b'], 132002)}, 'favorite ownership')
        require({(r['user_id'], r['term_id'], r['study_date']) for r in data['favorite_events']} == {
            (USER_IDS['member-a'], 132001, '2026-10-29'), (USER_IDS['member-a'], 132001, '2026-10-30'),
            (USER_IDS['member-a'], 132003, '2026-10-30'), (USER_IDS['member-b'], 132002, '2026-10-30')}, 'KST events')
        require(sum(r['status'] == 'open' for r in data['reports']) == 5, 'report states')
        require(sum(r['invalidated_at'] is None for r in data['ai_explanations']) == 3, 'explanation states')
        require({(r['id'], r['ai_explanation_id'], r['quiz_item_id']) for r in data['reports']} == {
            (132001,132001,None), (132002,132002,None), (132003,132003,None),
            (132004,None,132001), (132005,None,132002), (132006,132004,None)}, 'report targets')
        require({(r['id'], r['user_id']) for r in data['quiz_sets']} == {
            (132001, USER_IDS['member-a']), (132002, USER_IDS['member-b'])}, 'quiz ownership')
    print('PASS: real local Auth, profiles, REST, rate-limit RPC, Secure cookies, Origin, visitor and fixture row counts.')
    print('E08/E25/E26 product behavior remains unverified; use the guide acceptance table after implementation.')


def require(condition: bool, label: str) -> None:
    if not condition:
        raise SetupError(f'Fixture check failed: {label}.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'start', 'fixture', 'check', 'serve', 'stop'))
    parser.add_argument('--base-port', type=int, default=55320)
    args = parser.parse_args()
    if not 1024 <= args.base_port <= 65525:
        parser.error('base-port must be between 1024 and 65525')
    try:
        if args.command == 'prepare':
            prepare(args.base_port)
        elif args.command == 'start':
            config()
            cli('start', '-x', 'realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor')
            print('Local Postgres/Auth/REST started; credentials hidden.')
        elif args.command == 'fixture':
            fixture()
        elif args.command == 'check':
            check()
        elif args.command == 'serve':
            load_environment()
            import uvicorn
            uvicorn.run('app.main:app', host='127.0.0.1', port=8000)
        else:
            config()
            cli('stop')
            print('Stopped this isolated project; local data retained.')
    except (SetupError, httpx.HTTPError, OSError, ValueError, KeyError) as exc:
        print(str(exc) if isinstance(exc, SetupError) else f'Local setup failed: {type(exc).__name__} (details hidden).', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
