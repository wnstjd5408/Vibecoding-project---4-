"""Block main changes whose tree was not accepted on STG (MEG-218, release flow v3).

A release candidate branch ``meg-<n>-release`` may reach main only when the tag
``stg-accepted/meg-<n>`` exists and its commit has exactly the same tree as the
candidate. The tag is created by a repository admin after the STG batch E2E is
accepted; a tag ruleset keeps everyone else (including the AI account) from
creating it.

Standard library only. Reads the GitHub API; never checks out or runs PR code
and never prints API bodies. Every failure, including unexpected ones, ends in
RELEASE_TREE_BLOCKED (fail closed).
"""

import json
import os
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

RELEASE_BRANCH = re.compile(r"^meg-([0-9]+)-release$")
TAG_PREFIX = "stg-accepted/meg-"
SHA = re.compile(r"[0-9a-f]{40}")
# GET /commits/{sha}/pulls can be empty for a few seconds after a merge.
PULL_LOOKUP_DELAYS = (0, 5, 10, 20)


class Stop(RuntimeError):
    """A safe, operator-readable failure."""


class NotFound(Exception):
    pass


def require(condition, message):
    if not condition:
        raise Stop(message)


class API:
    def __init__(self, token, repo):
        self.token = token
        self.repo = repo

    def get(self, path):
        req = Request("https://api.github.com/repos/" + self.repo + path, headers={
            "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "release-tree-check",
        })
        try:
            with urlopen(req, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code == 404:
                raise NotFound(path) from None
            raise Stop(f"GitHub API request failed (HTTP {exc.code}).") from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise Stop("GitHub API response unavailable.") from None


def tag_name(branch):
    match = RELEASE_BRANCH.fullmatch(branch or "")
    require(match, "main changes must come from a release candidate branch meg-<n>-release "
                   f"(got {branch!r}). See docs/github-actions.md, Release tree check.")
    return TAG_PREFIX + match.group(1)


def commit_tree(api, sha):
    return api.get("/git/commits/" + sha)["tree"]["sha"]


def accepted_tree(api, tag):
    try:
        obj = api.get("/git/ref/tags/" + quote(tag, safe="/"))["object"]
    except NotFound:
        raise Stop(f"Tag {tag} does not exist. Create it on the STG commit after the batch "
                   "E2E is accepted, then re-run this check.") from None
    for _ in range(3):  # annotated tags point to a tag object first
        if obj["type"] == "commit":
            return obj["sha"], commit_tree(api, obj["sha"])
        require(obj["type"] == "tag", f"Tag {tag} points to an unsupported object.")
        obj = api.get("/git/tags/" + obj["sha"])["object"]
    raise Stop(f"Tag {tag} is nested too deeply.")


def compare_to_tag(api, branch, sha, label):
    """Shared rule for both events: the tree of `sha` must equal the tag's tree."""
    tag = tag_name(branch)
    tag_sha, expected = accepted_tree(api, tag)
    actual = commit_tree(api, sha)
    require(actual == expected, f"{label} tree {actual[:12]} differs from {tag} tree "
                                f"{expected[:12]}. Only the STG-accepted tree may reach main; "
                                "do not assign the production domain.")
    return f"{tag} ({tag_sha[:12]}) tree {expected[:12]} matches {label} {sha[:12]}."


def check_pull_request(api, env):
    require(env.get("PR_HEAD_REPO") == env.get("GITHUB_REPOSITORY"),
            "Release candidates must come from this repository.")
    head_sha = env.get("PR_HEAD_SHA", "")
    require(SHA.fullmatch(head_sha), "Missing pull request head SHA.")
    branch = env.get("PR_HEAD_REF")
    tag_name(branch)  # reject non-release branches before any API call
    # With main-protection's strict policy a stale PR cannot merge; this keeps the
    # check itself honest when it runs. Resolve heads/main first so a tag named
    # "main" cannot stand in for the branch.
    main_sha = api.get("/git/ref/heads/main")["object"]["sha"]
    require(SHA.fullmatch(main_sha), "Could not resolve the main branch.")
    behind = api.get("/compare/" + main_sha + "..." + head_sha).get("behind_by")
    require(behind == 0, "The candidate does not include the latest main. Rebuild it on the "
                         "current main and verify it on STG again.")
    return compare_to_tag(api, branch, head_sha, "candidate")


def merged_main_pulls(api, sha, sleep):
    pulls = []
    for delay in PULL_LOOKUP_DELAYS:
        sleep(delay)
        pulls = [pr for pr in api.get("/commits/" + sha + "/pulls")
                 if pr.get("merged_at") and pr.get("merge_commit_sha") == sha
                 and pr.get("base", {}).get("ref") == "main"]
        if pulls:
            break
    return pulls


def check_push(api, env, sleep=time.sleep):
    sha = env.get("GITHUB_SHA", "")
    require(SHA.fullmatch(sha), "Missing pushed commit SHA.")
    pulls = merged_main_pulls(api, sha, sleep)
    require(len(pulls) == 1, f"Expected exactly one merged main PR for {sha[:12]}, "
                             f"found {len(pulls)}. Direct pushes to main are not accepted.")
    head = pulls[0].get("head") or {}
    require((head.get("repo") or {}).get("full_name") == env.get("GITHUB_REPOSITORY"),
            "Release candidates must come from this repository.")
    return compare_to_tag(api, head.get("ref"), sha, "main")


def run(env, api, sleep=time.sleep):
    event = env.get("GITHUB_EVENT_NAME")
    if event == "pull_request_target":
        return check_pull_request(api, env)
    if event == "push":
        require(env.get("GITHUB_REF") == "refs/heads/main", "Only main pushes are checked.")
        return check_push(api, env, sleep)
    raise Stop(f"Unsupported event {event!r}.")


def main(env=None, api=None, sleep=time.sleep):
    env = os.environ if env is None else env
    try:
        if api is None:
            api = API(env["GH_TOKEN"], env["GITHUB_REPOSITORY"])
        message, code = "RELEASE_TREE_OK: " + run(env, api, sleep), 0
    except Stop as exc:
        message, code = "RELEASE_TREE_BLOCKED: " + str(exc), 1
    except NotFound:
        message, code = "RELEASE_TREE_BLOCKED: a commit or ref was not found through the GitHub API.", 1
    except Exception as exc:  # fail closed with a readable reason, never a raw API body
        message, code = f"RELEASE_TREE_BLOCKED: unexpected {type(exc).__name__}.", 1
    print(message)
    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
