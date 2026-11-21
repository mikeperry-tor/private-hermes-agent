"""Treasury one-shot work obeys the same launch boundary as stack startup."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import deployment
import x402_treazury as treasury


class TreasuryLaunchTests(unittest.TestCase):
    MODEL = json.dumps({'name': 'fixture', 'services': {
        'setup': {'network_mode': 'none'},
        'x402_treazury-inspect': {'network_mode': 'none'},
        'x402_treazury-admin': {'network_mode': 'none', 'depends_on': {'setup': {}}},
        'x402_treazury-setup': {'network_mode': 'service:agent-net'},
    }})

    def test_financial_one_shot_checks_both_engines_before_launch(self):
        for selected in ('docker', 'podman'):
            with self.subTest(engine=selected), patch.dict(os.environ), \
                    patch.object(deployment, 'engine', return_value=selected), \
                    patch.object(deployment, '_output', return_value=self.MODEL), \
                    patch.object(treasury, 'prepare_launch', side_effect=deployment.EngineError('launch refused')) as prepare, \
                    patch.object(treasury.subprocess, 'run',
                                 return_value=subprocess.CompletedProcess([], 0, stdout=self.MODEL)) as run:
                command = deployment.maintenance_compose()
                with self.assertRaisesRegex(deployment.EngineError, 'launch refused'):
                    treasury.Controller(command).wallet_command('prepare')
                launch_model = prepare.call_args.args[1]
                prepare.assert_called_once_with(command, launch_model)
                self.assertEqual(set(launch_model['services']), {'x402_treazury-setup'})
                # Only read-only model inspection preceded the refused launch;
                # no onboarding container, log follower or financial work started.
                self.assertEqual(len(run.call_args_list), 1)
                self.assertEqual(run.call_args.args[0][-3:], ['config', '--format', 'json'])

    def test_saved_state_and_offline_policy_jobs_do_not_require_launch_readiness(self):
        for selected in ('docker', 'podman'):
            with self.subTest(engine=selected), patch.dict(os.environ), \
                    patch.object(deployment, 'engine', return_value=selected), \
                    patch.object(deployment, '_output', return_value=self.MODEL), \
                    patch.object(treasury, 'prepare_launch', side_effect=AssertionError('offline job checked startup')), \
                    patch.object(treasury.subprocess, 'run') as run:
                controller = treasury.Controller(deployment.maintenance_compose())
                for action in ('status', 'inspect', 'validate'):
                    controller.admin(action)
                self.assertEqual(run.call_count, 3)
