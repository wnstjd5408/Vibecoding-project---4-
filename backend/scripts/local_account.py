"""Inspect or remove the single synthetic E24 onboarding account, locally only."""

import argparse
import sys
from uuid import UUID

import httpx

from scripts.local_backend import SetupError, connection, request, require

EMAIL = 'onboarding-e24@example.com'
DISPLAY_NAME = '합성 온보딩 사용자'


def account(action: str, user_id: str) -> None:
    uid = str(UUID(user_id))
    url, key = connection()  # checks local Docker, worktree project and loopback URL
    with httpx.Client(base_url=url, headers={'apikey': key, 'Authorization': f'Bearer {key}'},
                      trust_env=False, follow_redirects=False, timeout=15) as client:
        user = request(client, 'GET', f'/auth/v1/admin/users/{uid}').json()
        rows = request(client, 'GET', '/rest/v1/profiles', params={
            'user_id': f'eq.{uid}', 'select': 'user_id,role,is_active,display_name',
        }).json()
        require(user.get('id') == uid and user.get('email') == EMAIL, 'onboarding Auth identity')
        require(len(rows) == 1 and rows[0] == {
            'user_id': uid, 'role': 'member', 'is_active': True, 'display_name': DISPLAY_NAME,
        }, 'onboarding profile identity')
        if action == 'cleanup':
            request(client, 'DELETE', f'/auth/v1/admin/users/{uid}')
            require(client.get(f'/auth/v1/admin/users/{uid}').status_code == 404, 'Auth removal')
            require(request(client, 'GET', '/rest/v1/profiles', params={
                'user_id': f'eq.{uid}', 'select': 'user_id',
            }).json() == [], 'profile removal')
            print('PASS: removed only the specified synthetic local account and its profile.')
        else:
            print('PASS: synthetic Auth identity and active member profile match.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('inspect', 'cleanup'))
    parser.add_argument('--id', required=True, help='UUID from the successful E24 response')
    args = parser.parse_args()
    try:
        account(args.action, args.id)
    except (SetupError, ValueError, httpx.HTTPError, OSError, KeyError) as exc:
        print(str(exc) if isinstance(exc, SetupError) else 'Local account check failed; details hidden.',
              file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
