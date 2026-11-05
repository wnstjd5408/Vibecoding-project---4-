"""Deploy only a tested staging push. Standard library only; never print API bodies."""

import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler


class Stop(RuntimeError):
    """A safe, operator-readable failure (never includes remote error bodies)."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def require(condition, message):
    if not condition:
        raise Stop(message)


def request(host, token, path, method="GET", body=None, query=None):
    url = host + path + ("?" + urlencode(query) if query else "")
    data = None if body is None else json.dumps(body).encode()
    req = Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json",
        "Accept": "application/json", "User-Agent": "staging-cd",
    })
    try:
        with build_opener(NoRedirect).open(req, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        raise Stop(f"{method} request failed (HTTP {exc.code}); inspect provider privately.") from None
    except (URLError, TimeoutError, OSError, ValueError):
        # In particular, never retry an ambiguous POST automatically.
        raise Stop(f"{method} response unavailable; do not blindly retry deployment creation.") from None


class API:
    def __init__(self, env):
        self.env = env

    def github(self, path):
        return request("https://api.github.com", self.env["GH_TOKEN"], path)

    def vercel(self, path, method="GET", body=None, query=None):
        return request("https://api.vercel.com", self.env["VERCEL_TOKEN"], path,
                       method, body, {**(query or {}), "teamId": self.env["VERCEL_TEAM_ID"]})


def validate_context(env, config):
    require(env.get("GITHUB_EVENT_NAME") == "push", "Only push events may deploy.")
    require(env.get("GITHUB_REF") == "refs/heads/staging", "Only staging may deploy.")
    require(env.get("PRODUCT_CI_RESULT") == "success", "Product CI must succeed.")
    for key, pattern in {
        "GITHUB_SHA": r"[a-f0-9]{40}",
        "GITHUB_REPOSITORY": r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
        "GITHUB_RUN_ID": r"[0-9]+", "GITHUB_RUN_ATTEMPT": r"[1-9][0-9]*",
        "VERCEL_PROJECT_ID": r"prj_[A-Za-z0-9]+",
        "VERCEL_TEAM_ID": r"team_[A-Za-z0-9]+",
    }.items():
        require(re.fullmatch(pattern, env.get(key, "")), f"Missing or invalid {key}.")
    for key in ("GH_TOKEN", "VERCEL_TOKEN"):
        require(bool(env.get(key)), f"Missing {key}.")
    # Exact map prevents an overlapping enabled wildcard from re-enabling staging.
    require(config.get("git", {}).get("deploymentEnabled") == {"staging": False},
            "staging Git auto-deploy must be disabled in the tested configuration.")


def deployment_id(deployment):
    value = deployment.get("id") or deployment.get("uid") or ""
    require(re.fullmatch(r"dpl_[A-Za-z0-9]+", value), "Invalid deployment ID.")
    return value


def state(deployment):
    return deployment.get("readyState") or deployment.get("state")


def verify(deployment, env):
    source = deployment.get("gitSource") or {}
    require(deployment.get("projectId") == env["VERCEL_PROJECT_ID"], "Wrong deployment project.")
    require(deployment.get("target") in (None, "preview"), "Deployment is not Preview.")
    require(not deployment.get("customEnvironment"), "Custom environment is not permitted.")
    require(source.get("type") == "github" and source.get("ref") == "staging"
            and source.get("sha") == env["GITHUB_SHA"], "Deployment SHA or branch does not match CI.")
    deployment_id(deployment)


def record(env, status, deployment=None):
    # Only validated, allowlisted fields: no API bodies, env values, tokens or build logs.
    lines = ["### Staging CD", f"- SHA: `{env['GITHUB_SHA']}`",
             "- Environment: Preview / staging", f"- Result: {status}",
             f"- CI run: https://github.com/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}",
             f"- Attempt: {env['GITHUB_RUN_ATTEMPT']}"]
    if deployment:
        lines.append(f"- Deployment: `{deployment_id(deployment)}`")
        url = deployment.get("url", "")
        require(re.fullmatch(r"[a-zA-Z0-9-]+\.vercel\.app", url), "Invalid deployment URL.")
        lines.append(f"- URL: https://{url}")
    text = "\n".join(lines) + "\n"
    print(text)
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
            output.write(text)


def list_staging(api, project):
    result = []
    query = {"projectId": project, "branch": "staging", "limit": 100}
    seen = set()
    for _ in range(20):
        page = api.vercel("/v7/deployments", query=query)
        result.extend(page["deployments"])
        cursor = (page.get("pagination") or {}).get("next")
        if cursor is None:
            return result
        require(cursor not in seen, "Deployment pagination did not advance.")
        seen.add(cursor)
        query["until"] = cursor
    raise Stop("Deployment history exceeded scan limit; review before deploying.")


def deploy(env, config, api, sleep=time.sleep, monotonic=time.monotonic):
    validate_context(env, config)
    repository = env["GITHUB_REPOSITORY"]
    sha = env["GITHUB_SHA"]

    def current_head():
        return api.github(f"/repos/{repository}/git/ref/heads/staging")["object"]["sha"]

    if current_head() != sha:
        record(env, "STALE — no deployment created")
        return
    project = api.vercel("/v9/projects/" + env["VERCEL_PROJECT_ID"])
    link = project.get("link") or {}
    require(project.get("id") == env["VERCEL_PROJECT_ID"]
            and link.get("type") == "github"
            and f"{link.get('org')}/{link.get('repo')}" == repository
            and link.get("productionBranch") == "main", "Unexpected project Git connection.")
    require(project.get("autoExposeSystemEnvs") is True, "System environment variables must be exposed.")
    deployments = list_staging(api, env["VERCEL_PROJECT_ID"])
    matches = []
    for candidate in deployments:
        meta = candidate.get("meta") or {}
        source = candidate.get("gitSource") or {}
        candidate_sha = source.get("sha") or meta.get("githubCommitSha")
        if candidate_sha == sha:
            matches.append(candidate)
        elif state(candidate) not in ("READY", "ERROR", "CANCELED", "BLOCKED"):
            raise Stop("Another staging deployment is active or has unknown state; reconcile it first.")
    require(len(matches) <= 1, "Multiple deployments match this SHA; reconcile duplicates first.")
    if matches:
        deployment = api.vercel("/v13/deployments/" + deployment_id(matches[0]))
        verify(deployment, env)
        require((deployment.get("meta") or {}).get("stagingCd") == "v1",
                "Existing deployment is not from this CD path; manual reconciliation required.")
    else:
        # A re-run could follow a lost POST response. Never create a second request.
        require(env["GITHUB_RUN_ATTEMPT"] == "1",
                "No deployment found on re-run; confirm prior request outcome, then use a new approved commit.")
        if current_head() != sha:
            record(env, "STALE — no deployment created")
            return
        deployment = api.vercel("/v13/deployments", method="POST", body={
            "name": project["name"], "project": env["VERCEL_PROJECT_ID"],
            # Omit target: the API defaults to Preview. 'staging' is a different API target.
            "gitSource": {"type": "github", "org": link["org"], "repo": link["repo"],
                          "ref": "staging", "sha": sha},
            "meta": {"stagingCd": "v1", "ciRunId": env["GITHUB_RUN_ID"]},
        })
        # Record the accepted request before polling, even if the runner later dies.
        record(env, "REQUEST_ACCEPTED — awaiting verification", deployment)
        deployment = api.vercel("/v13/deployments/" + deployment_id(deployment))
    deadline = monotonic() + 18 * 60
    while True:
        verify(deployment, env)
        ready = state(deployment)
        if ready == "READY":
            require(current_head() == sha,
                    "Deployment became Ready after staging advanced; do not accept it as the current staging version.")
            record(env, "READY — runtime smoke remains a separate check", deployment)
            if env.get("GITHUB_OUTPUT"):
                with open(env["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                    output.write(f"deployment_id={deployment_id(deployment)}\n")
            return
        require(ready in ("INITIALIZING", "QUEUED", "BUILDING"),
                "Deployment failed, was canceled/blocked, or returned unknown state.")
        require(monotonic() < deadline,
                "Deployment wait timed out; inspect the existing deployment before any new attempt.")
        sleep(10)
        deployment = api.vercel("/v13/deployments/" + deployment_id(deployment))


def main():
    try:
        config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
        deploy(os.environ, config, API(os.environ))
    except Stop as exc:
        print(f"Staging CD stopped: {exc}", file=sys.stderr)
        return 1
    except Exception:
        # Unexpected schema/transport errors must not expose secret-bearing API responses.
        print("Staging CD stopped: unexpected response; inspect privately before retrying.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
