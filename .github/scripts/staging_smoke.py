"""Read-only smoke of the exact CD deployment; never expose response bodies/tokens."""
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit

import staging_cd as cd


def oidc_token(env):
    url = env.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    parsed = urlsplit(url)
    cd.require(parsed.scheme == "https" and parsed.hostname
               and parsed.hostname.endswith(".actions.githubusercontent.com")
               and not parsed.username and not parsed.password and parsed.port in (None, 443),
               "Invalid GitHub OIDC endpoint.")
    bearer = env.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    cd.require(bool(bearer), "GitHub OIDC permission is missing.")
    # Default GitHub audience matches the Vercel guided GitHub account form.
    result = cd.request("https://" + parsed.netloc, bearer,
                        parsed.path + ("?" + parsed.query if parsed.query else ""))
    token = result.get("value", "")
    cd.require(isinstance(token, str) and re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token),
               "Invalid OIDC response.")
    return token


def health_request(url, token):
    # Pass authorization only on stdin, never in argv, output, files or URLs.
    config = f'url = "{url}"\nheader = "x-vercel-trusted-oidc-idp-token: {token}"\n'
    try:
        result = subprocess.run(
            ["curl", "--disable", "--config", "-", "--silent", "--show-error",
             "--proto", "=https", "--max-time", "10", "--max-filesize", "4096",
             "--include", "--header", "Accept: application/json"],
            input=config, capture_output=True, text=True, timeout=12, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise cd.Stop("Health transport failed or timed out.") from None
    cd.require(result.returncode == 0, "Health transport failed or timed out.")
    # curl may prepend a proxy CONNECT response; only accept the final response.
    blocks = result.stdout.replace("\r\n", "\n").split("\n\n")
    while len(blocks) > 2 and blocks[1].startswith("HTTP/"):
        blocks.pop(0)
    cd.require(len(blocks) >= 2, "Health response is malformed.")
    lines = blocks[0].splitlines()
    cd.require(bool(lines) and re.fullmatch(r"HTTP/\S+ 200(?: .*)?", lines[0]),
               "Health HTTP status is not 200 (redirects are not followed).")
    headers = {}
    for line in lines[1:]:
        key, sep, value = line.partition(":")
        cd.require(bool(sep), "Health response headers are malformed.")
        key = key.lower()
        headers[key] = headers.get(key, "") + "," + value.strip()
    content_type = headers.get("content-type", "").lstrip(",").split(";")[0].strip().lower()
    cd.require(content_type == "application/json", "Health response is not JSON.")
    cache = {part.strip().lower() for part in headers.get("cache-control", "").split(",")}
    cd.require({"private", "no-store"}.issubset(cache) and not ({"public", "s-maxage"} & cache)
               and not any(part.startswith("s-maxage=") for part in cache), "Health cache policy is invalid.")
    try:
        body = json.loads("\n\n".join(blocks[1:]))
    except (ValueError, TypeError):
        raise cd.Stop("Health JSON is invalid.") from None
    cd.require(body == {"status": "ok"}, "Health JSON does not match the contract.")


def smoke(env, api, token_factory=oidc_token, request=health_request, sleep=time.sleep):
    cd.validate_context(env, {"git": {"deploymentEnabled": {"staging": False}}})
    identifier = cd.deployment_id({"id": env.get("STAGING_DEPLOYMENT_ID", "")})
    deployment = api.vercel("/v13/deployments/" + identifier)
    cd.verify(deployment, env)
    cd.require(cd.deployment_id(deployment) == identifier and cd.state(deployment) == "READY"
               and deployment.get("meta", {}).get("stagingCd") == "v1", "Deployment is not a Ready CD deployment.")
    host = deployment.get("url", "")
    cd.require(isinstance(host, str) and re.fullmatch(r"[a-zA-Z0-9-]+\.vercel\.app", host),
               "Invalid deployment hostname.")

    def check_head():
        cd.require(api.github(f"/repos/{env['GITHUB_REPOSITORY']}/git/ref/heads/staging")["object"]["sha"]
                   == env["GITHUB_SHA"], "Staging advanced; smoke result is stale.")

    check_head()
    token = token_factory(env)
    for attempt in range(1, 4):
        check_head()
        try:
            request("https://" + host + "/api/health", token)
        except cd.Stop:
            print(f"Staging smoke attempt {attempt}/3 failed; response content omitted.")
            if attempt == 3:
                cd.record(env, "SMOKE_FAILED — health contract not verified", deployment)
                raise cd.Stop("Health smoke failed after 3 attempts.") from None
            sleep(5)
        else:
            check_head()
            cd.record(env, "SMOKE_PASSED — HTTP 200 / JSON ok / private,no-store; DB/Auth/AI untested", deployment)
            return


def main():
    try:
        smoke(os.environ, cd.API(os.environ))
    except cd.Stop as exc:
        print(f"Staging smoke stopped: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("Staging smoke stopped: unexpected response; inspect privately.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
