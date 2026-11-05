import contextlib
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import staging_cd as cd


SHA = "a" * 40
OTHER = "b" * 40
ENV = {
    "GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/staging",
    "PRODUCT_CI_RESULT": "success", "GITHUB_SHA": SHA,
    "GITHUB_REPOSITORY": "owner/repo", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
    "VERCEL_PROJECT_ID": "prj_test", "VERCEL_TEAM_ID": "team_test",
    "GH_TOKEN": "fake-github", "VERCEL_TOKEN": "fake-vercel",
}
CONFIG = {"git": {"deploymentEnabled": {"staging": False}}}


def deployment(sha=SHA, status="READY"):
    return {"id": "dpl_test", "projectId": "prj_test", "target": None,
            "url": "test.vercel.app", "readyState": status,
            "gitSource": {"type": "github", "ref": "staging", "sha": sha},
            "meta": {"stagingCd": "v1", "githubCommitSha": sha}}


class FakeAPI:
    def __init__(self):
        self.heads = [SHA]
        self.project = {"id": "prj_test", "name": "test", "autoExposeSystemEnvs": True,
                        "link": {"type": "github", "org": "owner", "repo": "repo", "productionBranch": "main"}}
        self.pages = [{"deployments": [], "pagination": {"next": None}}]
        self.details = [deployment()]
        self.posts = []
        self.post_error = None

    def github(self, path):
        assert path == "/repos/owner/repo/git/ref/heads/staging"
        return {"object": {"sha": self.heads.pop(0) if len(self.heads) > 1 else self.heads[0]}}

    def vercel(self, path, method="GET", body=None, query=None):
        if method == "POST":
            self.posts.append(copy.deepcopy(body))
            if self.post_error:
                raise self.post_error
            return deployment(status="BUILDING")
        if path == "/v9/projects/prj_test":
            return self.project
        if path == "/v7/deployments":
            assert query["branch"] == "staging"
            return self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]
        assert path == "/v13/deployments/dpl_test"
        return self.details.pop(0) if len(self.details) > 1 else self.details[0]


class StagingCDTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.env = ENV.copy()
        self.output = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def run_deploy(self, **kwargs):
        return cd.deploy(self.env, CONFIG, self.api, sleep=lambda _: None, **kwargs)

    def test_only_successful_staging_push_accepts_credentials(self):
        for key, values in {
            "GITHUB_EVENT_NAME": ["pull_request", "pull_request_target", "workflow_dispatch"],
            "GITHUB_REF": ["refs/heads/main", "refs/pull/1/merge", "refs/tags/staging"],
            "PRODUCT_CI_RESULT": ["failure", "cancelled", "skipped", "", "in_progress"],
            "GITHUB_SHA": ["staging", "a" * 39], "VERCEL_TOKEN": [""],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(cd.Stop):
                    cd.deploy({**ENV, key: value}, CONFIG, self.api)
        self.assertEqual(self.api.posts, [])

    def test_auto_deploy_must_be_disabled_without_overlapping_wildcard(self):
        for mapping in (True, {}, {"staging": True}, {"staging": False, "*": True}):
            with self.subTest(mapping=mapping), self.assertRaises(cd.Stop):
                cd.validate_context(ENV, {"git": {"deploymentEnabled": mapping}})

    def test_success_pins_sha_and_branch_without_production_target(self):
        self.api.details = [deployment(status="BUILDING"), deployment()]
        self.run_deploy()
        self.assertEqual(len(self.api.posts), 1)
        body = self.api.posts[0]
        self.assertEqual(body["gitSource"], {"type": "github", "org": "owner", "repo": "repo",
                                            "ref": "staging", "sha": SHA})
        self.assertNotIn("target", body)
        self.assertNotIn("withLatestCommit", body)
        self.assertIn("READY", self.output.getvalue())
        self.assertNotIn("fake-vercel", self.output.getvalue())

    def test_stale_before_or_immediately_before_post_creates_nothing(self):
        for heads in ([OTHER], [SHA, OTHER]):
            self.api.heads = heads.copy()
            self.run_deploy()
            self.assertEqual(self.api.posts, [])

    def test_ready_after_new_push_is_not_accepted_as_current(self):
        self.api.heads = [SHA, SHA, OTHER]
        with self.assertRaisesRegex(cd.Stop, "staging advanced"):
            self.run_deploy()

    def test_existing_cd_deployment_is_reused_even_on_rerun(self):
        self.env["GITHUB_RUN_ATTEMPT"] = "2"
        self.api.pages[0]["deployments"] = [deployment()]
        self.api.details = [deployment(status="BUILDING"), deployment()]
        self.run_deploy()
        self.assertEqual(self.api.posts, [])

    def test_rerun_without_known_deployment_cannot_post(self):
        self.env["GITHUB_RUN_ATTEMPT"] = "2"
        with self.assertRaisesRegex(cd.Stop, "No deployment found"):
            self.run_deploy()
        self.assertEqual(self.api.posts, [])

    def test_ambiguous_post_is_never_retried(self):
        self.api.post_error = cd.Stop("POST response unavailable")
        with self.assertRaises(cd.Stop):
            self.run_deploy()
        self.assertEqual(len(self.api.posts), 1)

    def test_other_active_deployment_blocks_new_request(self):
        for status in ("BUILDING", "QUEUED", "INITIALIZING", None):
            self.api.pages[0]["deployments"] = [deployment(OTHER, status)]
            with self.subTest(status=status), self.assertRaises(cd.Stop):
                self.run_deploy()
        self.assertEqual(self.api.posts, [])

    def test_duplicate_or_non_cd_existing_deployments_fail_closed(self):
        self.api.pages[0]["deployments"] = [deployment(), deployment()]
        with self.assertRaisesRegex(cd.Stop, "Multiple"):
            self.run_deploy()
        self.api.pages[0]["deployments"] = [deployment()]
        self.api.details[0]["meta"] = {}
        with self.assertRaisesRegex(cd.Stop, "not from this CD"):
            self.run_deploy()
        self.assertEqual(self.api.posts, [])

    def test_pagination_checks_older_active_deployment(self):
        self.api.pages = [{"deployments": [], "pagination": {"next": 123}},
                          {"deployments": [deployment(OTHER, "BUILDING")]}]
        with self.assertRaises(cd.Stop):
            self.run_deploy()
        self.assertEqual(self.api.posts, [])

    def test_wrong_project_link_or_system_env_exposure_blocks_request(self):
        for field, value in (("id", "prj_wrong"), ("autoExposeSystemEnvs", False), ("link", {})):
            self.api = FakeAPI()
            self.api.project[field] = value
            with self.subTest(field=field), self.assertRaises(cd.Stop):
                self.run_deploy()
            self.assertEqual(self.api.posts, [])

    def test_wrong_target_sha_branch_or_project_never_reports_success(self):
        for field, value in (("target", "production"), ("target", "staging"),
                             ("projectId", "prj_wrong"), ("customEnvironment", {"slug": "other"}),
                             ("gitSource", {"type": "github", "ref": "main", "sha": SHA}),
                             ("gitSource", {"type": "github", "ref": "staging", "sha": OTHER})):
            item = deployment()
            item[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(cd.Stop):
                cd.verify(item, ENV)

    def test_failure_states_do_not_create_replacement(self):
        for status in ("ERROR", "CANCELED", "BLOCKED", "UNKNOWN"):
            self.api = FakeAPI()
            self.api.details = [deployment(status=status)]
            with self.subTest(status=status), self.assertRaises(cd.Stop):
                self.run_deploy()
            self.assertEqual(len(self.api.posts), 1)

    def test_poll_timeout_does_not_create_replacement(self):
        self.api.details = [deployment(status="BUILDING")]
        ticks = iter([0, 1081])
        with self.assertRaisesRegex(cd.Stop, "timed out"):
            self.run_deploy(monotonic=lambda: next(ticks))
        self.assertEqual(len(self.api.posts), 1)

    def test_transport_errors_hide_response_and_do_not_retry(self):
        for error in (HTTPError("https://api.vercel.com", 403, "SECRET", {}, io.BytesIO(b"SECRET")),
                      URLError("SECRET"), TimeoutError("SECRET")):
            with patch.object(cd, "build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(cd.Stop) as caught:
                    cd.request("https://api.vercel.com", "SECRET", "/v13/deployments", "POST", {})
                self.assertNotIn("SECRET", str(caught.exception))
                self.assertEqual(opener.return_value.open.call_count, 1)

    def test_redirects_do_not_forward_credentials(self):
        self.assertIsNone(cd.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.test"))

    def test_checked_in_configuration_disables_only_staging_git_deploys(self):
        root = Path(__file__).resolve().parents[2]
        self.assertEqual(json.loads((root / "vercel.json").read_text())["git"], CONFIG["git"])


if __name__ == "__main__":
    unittest.main()
