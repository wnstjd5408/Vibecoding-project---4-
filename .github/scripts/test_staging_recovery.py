import copy
import unittest
from unittest.mock import Mock

import staging_cd as cd
import staging_recovery as recovery
from test_staging_cd import ENV, SHA, deployment


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.env = {**ENV, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                    'GITHUB_SHA': 'b' * 40, 'RECOVERY_SHA': SHA,
                    'RECOVERY_DEPLOYMENT_ID': 'dpl_test', 'RECOVERY_CHECK_ALIAS': 'true',
                    'RECOVERY_STAGING_ALIAS': 'test-git-staging-team.vercel.app'}
        self.details = deployment()
        self.details['meta'] = {'stagingCd': 'v1', 'ciRunId': '123'}
        self.run = {'head_sha': SHA, 'head_branch': 'staging', 'event': 'push',
                    'path': '.github/workflows/product-ci.yml', 'status': 'completed',
                    'conclusion': 'success'}
        self.mapping = {'projectId': ENV['VERCEL_PROJECT_ID'], 'deploymentId': 'dpl_test'}
        self.api = Mock()
        self.api.vercel.side_effect = lambda path: self.mapping if '/aliases/' in path else self.details
        self.api.github.side_effect = lambda path: self.run if '/actions/runs/' in path else {'object': {'sha': self.env['GITHUB_SHA']}}
        self.token, self.probe = Mock(return_value='secret'), Mock()

    def verify(self, **kwargs):
        return recovery.verify_recovery(self.env, self.api, self.token, self.probe, **kwargs)

    def test_historical_sha_and_alias_verified_without_writes(self):
        result = self.verify()
        self.assertIn('RECOVERY_VERIFIED', result)
        self.assertNotIn('secret', result)
        self.assertEqual(self.probe.call_count, 2)
        for call in self.api.vercel.call_args_list:
            self.assertEqual(len(call.args), 1)
            self.assertFalse(call.kwargs)

    def test_candidate_only_does_not_touch_alias(self):
        self.env['RECOVERY_CHECK_ALIAS'] = 'false'
        self.verify()
        self.assertEqual(self.probe.call_count, 1)
        self.assertFalse(any('/aliases/' in c.args[0] for c in self.api.vercel.call_args_list))

    def test_rejects_wrong_environment_sha_url_before_oidc(self):
        original = copy.deepcopy(self.details)
        for change in ({'target': 'production'}, {'projectId': 'prj_wrong'},
                       {'readyState': 'ERROR'}, {'url': 'evil.example'}, {'id': 'dpl_wrong'},
                       {'gitSource': {'type': 'github', 'ref': 'main', 'sha': SHA}}, {'meta': {}}):
            self.details = {**original, **change}
            with self.subTest(change=change), self.assertRaises(cd.Stop):
                self.verify()
        self.token.assert_not_called()

    def test_rejects_failed_or_wrong_origin_ci(self):
        original = self.run.copy()
        for change in ({'conclusion': 'failure'}, {'status': 'in_progress'},
                       {'head_sha': 'c' * 40}, {'event': 'pull_request'},
                       {'path': '.github/workflows/other.yml'}, {'head_branch': 'main'}):
            self.run = {**original, **change}
            with self.subTest(change=change), self.assertRaises(cd.Stop):
                self.verify()
        self.token.assert_not_called()

    def test_wrong_alias_blocks_health(self):
        self.mapping['deploymentId'] = 'dpl_other'
        with self.assertRaisesRegex(cd.Stop, 'alias'):
            self.verify()
        self.probe.assert_not_called()

    def test_health_failure_is_bounded_and_redacted(self):
        self.probe.side_effect = cd.Stop('sensitive body')
        delays = []
        with self.assertRaisesRegex(cd.Stop, 'SMOKE_FAILED') as caught:
            self.verify(sleep=delays.append)
        self.assertNotIn('sensitive', str(caught.exception))
        self.assertEqual(self.probe.call_count, 3)
        self.assertEqual(delays, [5, 5])

    def test_main_or_push_cannot_run(self):
        for change in ({'GITHUB_REF': 'refs/heads/main'}, {'GITHUB_EVENT_NAME': 'push'}):
            original = self.env.copy()
            self.env.update(change)
            with self.assertRaises(cd.Stop):
                self.verify()
            self.env = original
        self.api.vercel.assert_not_called()

    def test_alias_change_after_health_fails(self):
        self.probe.side_effect = lambda *_: self.mapping.update(deploymentId='dpl_other')
        with self.assertRaisesRegex(cd.Stop, 'alias'):
            self.verify()
