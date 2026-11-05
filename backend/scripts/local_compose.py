"""Compose app lifecycle using the existing, isolated local Supabase project."""
import argparse
import json
import os
import subprocess
import sys

import httpx

from scripts import local_backend as local


def invoke(*args: str) -> None:
    local.docker_local()
    env = {k: v for k, v in os.environ.items() if not k.startswith('COMPOSE_')}
    env['LOCAL_SUPABASE_NETWORK'] = f'supabase_network_{local.project_id()}'
    result = subprocess.run([
        'docker', 'compose', '--project-name', f'{local.project_id()}-app',
        '--file', str(local.ROOT / 'compose.yaml'), '--env-file', str(local.LOCAL / 'compose-backend.env'),
        *args,
    ], cwd=local.ROOT, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        # Build/config/inspect output may contain secrets. Do not echo it.
        raise local.SetupError(f'Compose failed (exit {result.returncode}); see docs/local-compose-guide.md.')


def configure() -> None:
    local.load_environment()  # validates local CLI identity and secret without printing
    project = local.project_id()
    networks = json.loads(local.run(['docker', 'inspect', '--format',
        '{{json .NetworkSettings.Networks}}', f'supabase_kong_{project}']))
    if f'supabase_network_{project}' not in networks:
        raise local.SetupError('Supabase network mismatch; no app started.')
    path = local.LOCAL / 'compose-backend.env'
    content = (f'SUPABASE_URL=http://supabase_kong_{project}:8000\n'
               f'SUPABASE_SECRET_KEY={os.environ["SUPABASE_SECRET_KEY"]}\n'
               'ALLOWED_ORIGINS=http://localhost:5173\n')
    path.write_text(content, encoding='utf-8')
    if os.name != 'nt':
        path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('setup', 'up', 'down', 'stop'))
    parser.add_argument('--base-port', type=int, default=55320, help='Only for a new setup')
    args = parser.parse_args()
    try:
        if not 1024 <= args.base_port <= 65525:
            raise local.SetupError('base-port must be between 1024 and 65525')
        if args.command == 'setup' and not local.LOCAL.exists():
            local.prepare(args.base_port)
        local.config()
        if args.command in ('setup', 'up'):
            print('Starting this worktree Supabase; existing data is preserved.', flush=True)
            local.cli('start', '-x', 'realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor')
            if args.command == 'setup' and not (local.LOCAL / '.env').exists():
                local.fixture()
                local.check()
            configure()
            print('Building and starting Compose apps; first build may take several minutes.', flush=True)
            invoke('up', '--build', '--detach', '--wait', '--wait-timeout', '120')
            print('PASS: apps healthy at http://localhost:5173; verify real login separately.')
        else:
            # Does not require Auth/DB to be reachable and never removes DB volumes.
            invoke('down')
            if args.command == 'stop':
                local.cli('stop')
                print('Apps and this worktree Supabase stopped; database data retained.')
            else:
                print('Apps stopped; Supabase and database data retained.')
    except (local.SetupError, OSError, ValueError, KeyError, httpx.HTTPError) as exc:
        print(str(exc) if isinstance(exc, local.SetupError) else 'Local Compose failed; details hidden.', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
