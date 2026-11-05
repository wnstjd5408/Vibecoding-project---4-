import unittest

import release_tree_check as rtc

REPO = "owner/repo"
HEAD = "a" * 40
TAG_COMMIT = "b" * 40
TAG_OBJECT = "c" * 40
MERGE = "d" * 40
TREE = "e" * 40
OTHER_TREE = "f" * 40


class FakeAPI:
    def __init__(self):
        self.responses = {
            "/compare/main..." + HEAD: {"behind_by": 0},
            "/git/ref/tags/stg-accepted/meg-230": {"object": {"type": "commit", "sha": TAG_COMMIT}},
            "/git/commits/" + TAG_COMMIT: {"tree": {"sha": TREE}},
            "/git/commits/" + HEAD: {"tree": {"sha": TREE}},
            "/git/commits/" + MERGE: {"tree": {"sha": TREE}},
            "/commits/" + MERGE + "/pulls": [
                {"merged_at": "2026-11-05T00:00:00Z", "merge_commit_sha": MERGE,
                 "base": {"ref": "main"}, "head": {"ref": "meg-230-release"}},
            ],
        }
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        if path not in self.responses:
            raise rtc.NotFound(path)
        value = self.responses[path]
        if isinstance(value, Exception):
            raise value
        return value


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
        for branch in ("meg-219-integration-ci", "staging", "meg-230-release-2", ""):
            with self.subTest(branch=branch), self.assertRaisesRegex(rtc.Stop, "meg-<n>-release"):
                rtc.run(pr_env(PR_HEAD_REF=branch), api)
        self.assertEqual(api.calls, [])

    def test_candidate_behind_main_fails(self):
        api = FakeAPI()
        api.responses["/compare/main..." + HEAD] = {"behind_by": 2}
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

    def test_api_error_fails_closed(self):
        api = FakeAPI()
        api.responses["/git/commits/" + HEAD] = rtc.Stop("GitHub API request failed (HTTP 500).")
        with self.assertRaisesRegex(rtc.Stop, "HTTP 500"):
            rtc.run(pr_env(), api)


class PushCheck(unittest.TestCase):
    def test_merged_candidate_passes(self):
        self.assertIn("matches main", rtc.run(push_env(), FakeAPI()))

    def test_tree_mismatch_fails(self):
        api = FakeAPI()
        api.responses["/git/commits/" + MERGE] = {"tree": {"sha": OTHER_TREE}}
        with self.assertRaisesRegex(rtc.Stop, "Do not assign the production domain"):
            rtc.run(push_env(), api)

    def test_direct_push_without_pr_fails(self):
        api = FakeAPI()
        api.responses["/commits/" + MERGE + "/pulls"] = []
        with self.assertRaisesRegex(rtc.Stop, "found 0"):
            rtc.run(push_env(), api)

    def test_non_release_pr_fails(self):
        api = FakeAPI()
        api.responses["/commits/" + MERGE + "/pulls"][0]["head"]["ref"] = "meg-218-release-tree-check"
        with self.assertRaisesRegex(rtc.Stop, "meg-<n>-release"):
            rtc.run(push_env(), api)

    def test_unmerged_or_other_base_prs_are_ignored(self):
        api = FakeAPI()
        api.responses["/commits/" + MERGE + "/pulls"] = [
            {"merged_at": None, "merge_commit_sha": MERGE, "base": {"ref": "main"},
             "head": {"ref": "meg-230-release"}},
            {"merged_at": "x", "merge_commit_sha": MERGE, "base": {"ref": "staging"},
             "head": {"ref": "meg-230-release"}},
        ]
        with self.assertRaisesRegex(rtc.Stop, "found 0"):
            rtc.run(push_env(), api)

    def test_other_ref_fails(self):
        with self.assertRaisesRegex(rtc.Stop, "Only main"):
            rtc.run(push_env(GITHUB_REF="refs/heads/staging"), FakeAPI())


class Events(unittest.TestCase):
    def test_unsupported_event_fails(self):
        with self.assertRaisesRegex(rtc.Stop, "Unsupported event"):
            rtc.run(pr_env(GITHUB_EVENT_NAME="pull_request"), FakeAPI())

    def test_tag_name(self):
        self.assertEqual(rtc.tag_name("meg-230-release"), "stg-accepted/meg-230")


if __name__ == "__main__":
    unittest.main()
