"""Read-only historical staging deployment verification; never switch traffic."""
import os
import re
import sys
import time

import staging_cd as cd
import staging_smoke as health


def verify_recovery(env, api, token_factory=health.oidc_token, probe=health.health_request,
                    sleep=time.sleep):
    cd.require(env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
               and env.get('GITHUB_REF') == 'refs/heads/staging', 'Only manual staging verification is allowed.')
    sha = env.get('RECOVERY_SHA', '')
    cd.require(bool(re.fullmatch(r'[a-f0-9]{40}', sha)), 'Invalid recovery SHA.')
    identifier = cd.deployment_id({'id': env.get('RECOVERY_DEPLOYMENT_ID', '')})
    check_alias = env.get('RECOVERY_CHECK_ALIAS', '')
    cd.require(check_alias in ('true', 'false'), 'Invalid alias check option.')
    deployment = api.vercel('/v13/deployments/' + identifier)
    expected = {**env, 'GITHUB_SHA': sha}
    cd.verify(deployment, expected)
    cd.require(cd.deployment_id(deployment) == identifier, 'Deployment ID mismatch.')
    cd.require(deployment.get('meta', {}).get('stagingCd') == 'v1', 'Not a staging CD deployment.')
    cd.require(cd.state(deployment) == 'READY', 'BUILD_NOT_READY: recovery target is not Ready.')
    host = deployment.get('url', '')
    cd.require(isinstance(host, str) and bool(re.fullmatch(r'[A-Za-z0-9-]+\.vercel\.app', host)),
               'Invalid deployment hostname.')
    run_id = str(deployment.get('meta', {}).get('ciRunId', ''))
    cd.require(bool(re.fullmatch(r'[0-9]+', run_id)), 'Missing originating CI run.')
    run = api.github(f"/repos/{env['GITHUB_REPOSITORY']}/actions/runs/{run_id}")
    cd.require(run.get('head_sha') == sha and run.get('head_branch') == 'staging'
               and run.get('event') == 'push' and run.get('path') == '.github/workflows/product-ci.yml'
               and run.get('status') == 'completed' and run.get('conclusion') == 'success',
               'Originating staging CI is not successful for this SHA.')
    alias = env.get('RECOVERY_STAGING_ALIAS', '')
    if check_alias == 'true':
        cd.require(bool(re.fullmatch(r'[A-Za-z0-9-]+-git-staging-[A-Za-z0-9-]+\.vercel\.app', alias)),
                   'Invalid staging alias.')

    def unchanged():
        current = api.github(f"/repos/{env['GITHUB_REPOSITORY']}/git/ref/heads/staging")
        cd.require(current['object']['sha'] == env['GITHUB_SHA'], 'Staging changed during verification.')
        if check_alias == 'true':
            mapping = api.vercel('/v4/aliases/' + alias)
            cd.require(mapping.get('projectId') == env['VERCEL_PROJECT_ID']
                       and mapping.get('deploymentId') == identifier and not mapping.get('redirect'),
                       'Staging alias does not point to the selected deployment.')

    unchanged()
    token = token_factory(env)
    for attempt in range(3):
        unchanged()
        try:
            probe('https://' + host + '/api/health', token)
            if check_alias == 'true':
                probe('https://' + alias + '/api/health', token)
        except cd.Stop:
            if attempt == 2:
                raise cd.Stop('SMOKE_FAILED: recovery health contract failed after 3 attempts.') from None
            sleep(5)
        else:
            unchanged()
            text = (f'RECOVERY_VERIFIED: deployment={identifier}; sha={sha}; Preview/staging; '
                    f'alias_checked={check_alias}; HTTP 200 / JSON ok / private,no-store. '
                    'Read-only verification; no traffic switch; DB/Auth/AI untested.')
            print(text)
            return text


def main():
    started = time.monotonic()
    try:
        result = verify_recovery(os.environ, cd.API(os.environ))
        code = 0
    except cd.Stop as exc:
        result, code = str(exc), 1
    except Exception:
        result, code = 'RECOVERY_FAILED: unexpected response; inspect privately.', 1
    summary = f'{result}\nElapsed seconds: {time.monotonic() - started:.1f}\n'
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as output:
            output.write(summary)
    return code


if __name__ == '__main__':
    sys.exit(main())
