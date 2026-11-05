import contextlib
import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import release_tree_check as rtc

REPO = "owner/repo"
HEAD = "a" * 40
TAG_COMMIT = "b" * 40
TAG_OBJECT = "c" * 40
MERGE = "d" * 40
TREE = "e" * 40
OTHER_TREE = "f" * 40
MAIN = "1" * 40
NO_SLEEP = lambda _seconds: None  # noqa: E731


class FakeAPI:
    def __init__(self):
        self.responses = {
            "/git/ref/heads/main": {"object": {"type": "commit", "sha": MAIN}},
            "/compare/" + MAIN + "..." + HEAD: {"behind_by": 0},
            "/git/ref/tags/stg-accepted/meg-230": {"object": {"type": "commit", "sha": TAG_COMMIT}},
            "/git/commits/" + TAG_COMMIT: {"tree": {"sha": TREE}},
            "/git/commits/" + HEAD: {"tree": {"sha": TREE}},
            "/git/commits/" + MERGE: {"tree": {"sha": TREE}},
            "/commits/" + MERGE + "/pulls": [merged_pr()],
        }
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        if path not in self.responses:
            raise rtc.NotFound(path)
        value = self.responses[path]
        if isinstance(value, list) and value and isinstance(value[0], list):
            return value.pop(0)  # successive responses
        if isinstance(value, Exception):
            raise value
        return value


def merged_pr(ref="meg-230-release", base="main", merged=True, repo=REPO):
    return {"merged_at": "2026-11-05T00:00:00Z" if merged else None, "merge_commit_sha": MERGE,
            "base": {"ref": base}, "head": {"ref": ref, "repo": {"full_name": repo}}}


def pr_env(**overrides):
    env = {"GITHUB_EVENT_NAME": "pull_request_target", "GITHUB_REPOSITORY": REPO,
           "PR_HEAD_REPO": REPO, "PR_HEAD_REF": "meg-230-release", "PR_HEAD_SHA": HEAD}
    env.update(overrides)
    return env


def push_env(**overrides):
    env = {"GITHUB_EVENT_NAME": "push", "GITHUB_REPOSITORY": REPO,
           "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": MERGE}
    env.update(overrides)
    return env


class PullRequestCheck(unittest.TestCase):
    def test_matching_tree_passes(self):
        self.assertIn("matches candidate", rtc.run(pr_env(), FakeAPI()))

    def test_tree_mismatch_fails(self):
        api = FakeAPI()
        api.responses["/git/commits/" + HEAD] = {"tree": {"sha": OTHER_TREE}}
        with self.assertRaisesRegex(rtc.Stop, "differs from stg-accepted/meg-230"):
            rtc.run(pr_env(), api)

    def test_missing_tag_fails(self):
        api = FakeAPI()
        del api.responses["/git/ref/tags/stg-accepted/meg-230"]
        with self.assertRaisesRegex(rtc.Stop, "does not exist"):
            rtc.run(pr_env(), api)

    def test_non_release_branch_fails_before_any_api_call(self):
        api = FakeAPI()
        for branch in ("meg-219-integration-ci", "staging", "meg-230-release-2",
                       "revert-12-meg-230-release", ""):
            with self.subTest(branch=branch), self.assertRaisesRegex(rtc.Stop, "meg-<n>-release"):
                rtc.run(pr_env(PR_HEAD_REF=branch), api)
        self.assertEqual(api.calls, [])

    def test_candidate_behind_main_fails(self):
        api = FakeAPI()
        api.responses["/compare/" + MAIN + "..." + HEAD] = {"behind_by": 2}
        with self.assertRaisesRegex(rtc.Stop, "latest main"):
            rtc.run(pr_env(), api)

    def test_fork_fails(self):
        with self.assertRaisesRegex(rtc.Stop, "this repository"):
            rtc.run(pr_env(PR_HEAD_REPO="someone/fork"), FakeAPI())

    def test_bad_head_sha_fails(self):
        with self.assertRaisesRegex(rtc.Stop, "head SHA"):
            rtc.run(pr_env(PR_HEAD_SHA="not-a-sha"), FakeAPI())

    def test_annotated_tag_is_dereferenced(self):
        api = FakeAPI()
        api.responses["/git/ref/tags/stg-accepted/meg-230"] = {"object": {"type": "tag", "sha": TAG_OBJECT}}
        api.responses["/git/tags/" + TAG_OBJECT] = {"object": {"type": "commit", "sha": TAG_COMMIT}}
        self.assertIn("matches candidate", rtc.run(pr_env(), api))


class PushCheck(unittest.TestCase):
    def test_merged_candidate_passes(self):
        self.assertIn("matches main", rtc.run(push_env(), FakeAPI(), NO_SLEEP))

    def test_tree_mismatch_fails(self):
        api = FakeAPI()
        api.responses["/git/commits/" + MERGE] = {"tree": {"sha": OTHER_TREE}}
        with self.assertRaisesRegex(rtc.Stop, "do not assign the production domain"):
            rtc.run(push_env(), api, NO_SLEEP)

    def test_pull_association_is_retried(self):
        api = FakeAPI()
        api.responses["/commits/" + MERGE + "/pulls"] = [[], [], [merged_pr()]]
        waits = []
        self.assertIn("matches main", rtc.run(push_env(), api, waits.append))
        self.assertEqual(waits, [0, 5, 10])

    def test_direct_push_without_pr_fails_after_retries(self):
        api = FakeAPI()
        api.responses["/commits/" + MERGE + "/pulls"] = [[], [], [], []]
        waits = []
        with self.assertRaisesRegex(rtc.Stop, "found 0"):
            rtc.run(push_env(), api, waits.append)
        self.assertEqual(waits, list(rtc.PULL_LOOKUP_DELAYS))

    def test_non_release_pr_fails(self):
        api = FakeAPI()
        api.responses["/commits/" + MERGE + "/pulls"] = [[merged_pr("meg-218-release-tree-check")]]
        with self.assertRaisesRegex(rtc.Stop, "meg-<n>-release"):
            rtc.run(push_env(), api, NO_SLEEP)

    def test_unmerged_or_other_base_prs_are_ignored(self):
        api = FakeAPI()
        api.responses["/commits/" + MERGE + "/pulls"] = [merged_pr(merged=False), merged_pr(base="staging")]
        with self.assertRaisesRegex(rtc.Stop, "found 0"):
            rtc.run(push_env(), api, NO_SLEEP)

    def test_push_from_fork_fails(self):
        api = FakeAPI()
        api.responses["/commits/" + MERGE + "/pulls"] = [[merged_pr(repo="someone/fork")]]
        with self.assertRaisesRegex(rtc.Stop, "this repository"):
            rtc.run(push_env(), api, NO_SLEEP)

    def test_main_is_resolved_as_a_branch_sha(self):
        api = FakeAPI()
        rtc.run(pr_env(), api)
        self.assertIn("/git/ref/heads/main", api.calls)
        self.assertNotIn("/compare/main..." + HEAD, api.calls)

    def test_other_ref_fails(self):
        with self.assertRaisesRegex(rtc.Stop, "Only main"):
            rtc.run(push_env(GITHUB_REF="refs/heads/staging"), FakeAPI(), NO_SLEEP)


class FailClosed(unittest.TestCase):
    def run_main(self, env, api):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = rtc.main(env, api, NO_SLEEP)
        return code, out.getvalue()

    def test_ok_prints_ok(self):
        code, out = self.run_main(pr_env(), FakeAPI())
        self.assertEqual((code, out.startswith("RELEASE_TREE_OK")), (0, True))

    def test_not_found_on_non_tag_path_is_blocked(self):
        api = FakeAPI()
        del api.responses["/git/commits/" + HEAD]
        code, out = self.run_main(pr_env(), api)
        self.assertEqual(code, 1)
        self.assertIn("RELEASE_TREE_BLOCKED: a commit or ref was not found", out)

    def test_unexpected_response_shape_is_blocked(self):
        api = FakeAPI()
        api.responses["/git/commits/" + HEAD] = {"unexpected": True}
        code, out = self.run_main(pr_env(), api)
        self.assertEqual(code, 1)
        self.assertIn("RELEASE_TREE_BLOCKED: unexpected KeyError", out)

    def test_missing_token_is_blocked(self):
        code, out = self.run_main(pr_env(), None)
        self.assertEqual(code, 1)
        self.assertIn("unexpected KeyError", out)

    def test_tag_to_unsupported_object_is_blocked(self):
        api = FakeAPI()
        api.responses["/git/ref/tags/stg-accepted/meg-230"] = {"object": {"type": "tree", "sha": TREE}}
        code, out = self.run_main(pr_env(), api)
        self.assertEqual(code, 1)
        self.assertIn("unsupported object", out)

    def test_tag_nested_too_deeply_is_blocked(self):
        api = FakeAPI()
        api.responses["/git/ref/tags/stg-accepted/meg-230"] = {"object": {"type": "tag", "sha": TAG_OBJECT}}
        api.responses["/git/tags/" + TAG_OBJECT] = {"object": {"type": "tag", "sha": TAG_OBJECT}}
        code, out = self.run_main(pr_env(), api)
        self.assertEqual(code, 1)
        self.assertIn("nested too deeply", out)

    def test_compare_not_found_is_blocked(self):
        api = FakeAPI()
        del api.responses["/compare/" + MAIN + "..." + HEAD]
        code, out = self.run_main(pr_env(), api)
        self.assertEqual(code, 1)
        self.assertIn("not found", out)

    def test_malformed_pulls_response_is_blocked(self):
        api = FakeAPI()
        api.responses["/commits/" + MERGE + "/pulls"] = {"message": "not a list"}
        code, out = self.run_main(push_env(), api)
        self.assertEqual(code, 1)
        self.assertIn("RELEASE_TREE_BLOCKED: unexpected", out)

    def test_unsupported_event_is_blocked(self):
        code, out = self.run_main(pr_env(GITHUB_EVENT_NAME="pull_request"), FakeAPI())
        self.assertEqual(code, 1)
        self.assertIn("Unsupported event", out)


class HTTPMapping(unittest.TestCase):
    def get_with(self, error):
        with patch.object(rtc, "urlopen", side_effect=error):
            return rtc.API("token", REPO).get("/git/commits/" + HEAD)

    def test_404_is_not_found(self):
        with self.assertRaises(rtc.NotFound):
            self.get_with(HTTPError("u", 404, "nf", {}, None))

    def test_500_is_stop_without_body(self):
        with self.assertRaisesRegex(rtc.Stop, r"^GitHub API request failed \(HTTP 500\)\.$"):
            self.get_with(HTTPError("u", 500, "err", {}, io.BytesIO(b"secret body")))

    def test_network_error_is_stop(self):
        with self.assertRaisesRegex(rtc.Stop, "unavailable"):
            self.get_with(URLError("down"))


class Names(unittest.TestCase):
    def test_tag_name(self):
        self.assertEqual(rtc.tag_name("meg-230-release"), "stg-accepted/meg-230")


if __name__ == "__main__":
    unittest.main()
