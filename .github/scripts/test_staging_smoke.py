import contextlib
import copy
import io
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import staging_cd as cd
import staging_smoke as smoke
from test_staging_cd import ENV, SHA, FakeAPI, deployment


OK = 'HTTP/2 200\r\nContent-Type: application/json\r\nCache-Control: private, no-store\r\n\r\n{"status":"ok"}'


class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.env = {**ENV, "STAGING_DEPLOYMENT_ID": "dpl_test"}
        self.api = FakeAPI()
        self.out = io.StringIO()
        self.capture = contextlib.redirect_stdout(self.out)
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def run_smoke(self, **kwargs):
        return smoke.smoke(self.env, self.api, token_factory=lambda _: "fake.oidc.token", **kwargs)

    def test_exact_ready_deployment_only(self):
        calls = []
        self.run_smoke(request=lambda *args: calls.append(args))
        self.assertEqual(calls, [("https://test.vercel.app/api/health", "fake.oidc.token")])
        self.assertIn("SMOKE_PASSED", self.out.getvalue())
        self.assertNotIn("fake.oidc.token", self.out.getvalue())
        self.assertEqual(self.api.posts, [])

    def test_invalid_deployment_never_receives_token(self):
        changes = [{"target": "production"}, {"projectId": "prj_other"},
                   {"readyState": "BUILDING"}, {"id": "dpl_other"},
                   {"url": "evil.test/path"}, {"url": "test.vercel.app@evil.test"},
                   {"meta": {}}, {"customEnvironment": {"slug": "other"}},
                   {"gitSource": {"type": "github", "ref": "staging", "sha": "b" * 40}}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(cd.Stop):
                self.api.details = [{**deployment(), **change}]
                self.run_smoke(request=lambda *_: self.fail("must not request health"))

    def test_retries_three_times_and_redacts_failures(self):
        calls, sleeps = [], []
        def fail(*args):
            calls.append(args)
            raise cd.Stop("sensitive server response")
        with self.assertRaisesRegex(cd.Stop, "3 attempts"):
            self.run_smoke(request=fail, sleep=sleeps.append)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [5, 5])
        self.assertIn("SMOKE_FAILED", self.out.getvalue())
        self.assertNotIn("sensitive", self.out.getvalue())

    def test_transient_failure_then_success(self):
        calls = []
        def request(*_):
            calls.append(1)
            if len(calls) == 1:
                raise cd.Stop("temporary")
        self.run_smoke(request=request, sleep=lambda _: None)
        self.assertEqual(len(calls), 2)
        self.assertIn("SMOKE_PASSED", self.out.getvalue())

    def test_stale_after_health_is_failure(self):
        self.api.heads = [SHA, SHA, "b" * 40]
        with self.assertRaisesRegex(cd.Stop, "stale"):
            self.run_smoke(request=lambda *_: None)
        self.assertNotIn("SMOKE_PASSED", self.out.getvalue())

    def test_status_body_headers_contract(self):
        invalid = [OK.replace("200", "302"), OK.replace("200", "500"),
                   OK.replace("application/json", "text/html"),
                   OK.replace("private, no-store", "public, max-age=60"),
                   OK.replace("no-store", "no-store, s-maxage=60"),
                   OK.replace('{"status":"ok"}', '<html>login</html>'),
                   OK.replace('"ok"', '"failed"')]
        for response in [OK, *invalid]:
            with self.subTest(response=response), patch.object(smoke.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=response)) as run:
                if response == OK:
                    smoke.health_request("https://test.vercel.app/api/health", "fake.oidc.token")
                else:
                    with self.assertRaises(cd.Stop):
                        smoke.health_request("https://test.vercel.app/api/health", "fake.oidc.token")
                args, kwargs = run.call_args
                self.assertNotIn("fake.oidc.token", str(args))
                self.assertNotIn("--location", args[0])
                self.assertEqual(kwargs["timeout"], 12)
                self.assertIn("10", args[0])

    def test_transport_failure_is_sanitized(self):
        for error in [OSError("secret"), subprocess.TimeoutExpired("secret", 12)]:
            with patch.object(smoke.subprocess, "run", side_effect=error):
                with self.assertRaises(cd.Stop) as failure:
                    smoke.health_request("https://test.vercel.app/api/health", "fake.oidc.token")
                self.assertNotIn("secret", str(failure.exception))

    def test_oidc_rejects_untrusted_endpoint_and_malformed_token(self):
        for url in ["https://evil.test/token", "http://x.actions.githubusercontent.com", "https://x.actions.githubusercontent.com@evil.test"]:
            with self.subTest(url=url), self.assertRaises(cd.Stop):
                smoke.oidc_token({"ACTIONS_ID_TOKEN_REQUEST_URL": url})
        env = {"ACTIONS_ID_TOKEN_REQUEST_URL": "https://x.actions.githubusercontent.com/token?a=b",
               "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "fake-bearer"}
        with patch.object(cd, "request", return_value={"value": "bad\nheader"}), self.assertRaises(cd.Stop):
            smoke.oidc_token(env)
        with patch.object(cd, "request", return_value={"value": "a.b.c"}):
            self.assertEqual(smoke.oidc_token(env), "a.b.c")


if __name__ == "__main__":
    unittest.main()
