"""Maintenance remains available without weakening application launch checks."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'components/provisioning'))
import deployment
import stack
import private_files
from x402_treazury import Controller, operation_lock

BAD = dict(WEBAPP_TERMINAL_ENVIRONMENT='invalid', WEBAPP_EXTERNAL_CONTENT='invalid', TEEP_HOST_PORT='invalid', TEEP_SERVE_ARGS='"',
           TAILSCALE_FUNNEL_ENABLED='invalid', WEBAPP_BIND='invalid', WEBAPP_PORT='invalid',
           COMPUTER_USE_ENABLED='invalid')


class MaintenanceScopeTests(unittest.TestCase):
    def test_managed_down_includes_profiled_namespace_users_and_preserves_volumes(self):
        with patch.object(sys, 'argv', ['stack.py', 'down']), \
                patch.object(stack, 'maintenance_compose', return_value=['compose']), \
                patch.object(stack, 'stop_funnel') as funnel, patch.object(stack, 'run') as run, \
                patch.object(stack, 'remove_networks') as networks:
            stack.main_unlocked()
        command = ['compose', '--profile', '*']
        funnel.assert_called_once_with(command)
        run.assert_called_once_with(command + ['down', '--timeout', '-1'])
        networks.assert_called_once_with(command)


    def test_executor_build_preserves_desktop_selection_despite_bad_ingress_settings(self):
        with patch.dict(os.environ, dict(BAD, COMPUTER_USE_ENABLED='true')):
            command = deployment.maintenance_compose(all_ingress=True, executor_build=True)
            result = subprocess.run([*command, '--env-file', '/dev/null', 'config', '--format', 'json'],
                                    cwd=ROOT, check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout)['services']['executor']['build']['target'], 'executor-true')

    def test_maintenance_model_parses_bad_unrelated_settings_and_includes_funnel(self):
        with patch.dict(os.environ, BAD):
            command = deployment.maintenance_compose(all_ingress=True)
            subprocess.run([*command, '--env-file', '/dev/null', 'config', '--quiet'], cwd=ROOT, check=True)
        self.assertIn('compose.funnel.yaml', command)

    def test_logs_and_explicit_offline_jobs_skip_settings_but_launch_does_not(self):
        commands = (['build', 'hermes'], ['run', '--rm', '--no-deps', 'setup-storage'],
                    ['run', '--rm', '--no-deps', 'setup-storage', 'check-filesystem', '/persistent-data'],
                    ['run', '--rm', '--no-deps', 'mcp-config', 'token'], ['logs', 'hermes'], ['exec', '-T', 'hermes', 'true'],
                    ['run', '--rm', '--no-deps', 'hermes-config', 'set', 'terminal.backend', 'ssh'],
                    ['run', '--rm', '-T', '--no-deps', '--entrypoint', '/usr/local/bin/x402_treazury',
                     'x402_treazury-admin', 'wallet', 'preview'],
                    ['run', '--rm', '--no-deps', '--volume', '/private/backup:/backup',
                     '--entrypoint', '/usr/local/bin/x402_treazury', 'x402_treazury-inspect', 'wallet', 'backup'])
        for command in commands:
            with patch.dict(os.environ, BAD), patch.object(sys, 'argv', ['stack.py', 'compose', *command]), \
                    patch.object(stack, 'settings', side_effect=AssertionError('unrelated validation')), \
                    patch.object(stack, 'run') as run, patch.object(stack, 'check_bind_sources'):
                stack.main()
            self.assertEqual(run.call_args.args[0][-len(command):], command)
        for command in (['up'], ['run', '--rm', '--no-deps', 'hermes', 'gateway', 'run'],
                        ['run', 'setup-storage', 'command', '--no-deps'],
                        ['run', '--no-deps', '--name', 'hermes-config', 'hermes', 'gateway', 'run']):
            with patch.object(sys, 'argv', ['stack.py', 'compose', *command]), \
                    patch.object(stack, 'settings', side_effect=ValueError('invalid launch policy')), \
                    patch.object(stack, 'run') as run, self.assertRaisesRegex(ValueError, 'invalid launch policy'):
                stack.main()
            run.assert_not_called()

    def test_artifact_build_needs_no_initialization_or_deployment_policy(self):
        with patch.dict(os.environ, BAD), patch.object(sys, 'argv', ['stack.py', 'build']), \
                patch.object(stack, 'settings', side_effect=AssertionError('unrelated policy gate')), \
                patch.object(stack, 'initialize_setup', side_effect=AssertionError('state initialization')), \
                patch.object(stack, 'initialize_research_config', side_effect=AssertionError('policy publication')), \
                patch.object(stack, 'run') as run:
            stack.main()
        self.assertEqual(run.call_args.args[0][-3:], ['--profile', '*', 'build'])

    def test_raw_model_inspection_preserves_actual_settings_without_policy_gate(self):
        with patch.dict(os.environ, BAD), patch.object(sys, 'argv', ['stack.py', 'compose', 'config']), \
                patch.object(stack, 'settings', side_effect=AssertionError('unrelated policy gate')), \
                patch.object(stack, 'run') as run:
            stack.main()
            self.assertEqual(os.environ['TEEP_HOST_PORT'], 'invalid')
        self.assertEqual(run.call_args.args[0][-1], 'config')

    def test_saved_wallet_commands_do_not_prepare_unrelated_state(self):
        controller = Controller(['test-compose'])
        controller.inspect = lambda: {'wallet_absent': False, 'wallet_valid': True}
        controller.admin = Mock()
        with patch('x402_treazury.subprocess.run') as run, \
                patch('x402_treazury.initialize_research_config') as seed, redirect_stdout(io.StringIO()):
            controller.initialize()
        controller.admin.assert_called_once_with('status')
        run.assert_not_called()
        seed.assert_not_called()
        for action in ('inspect', 'status', 'connected', 'disconnected', 'activation-failed'):
            with patch.object(controller, 'call', return_value=None) as call:
                Controller.admin(controller, action)
            self.assertEqual(call.call_args.args[-2:], ('x402_treazury-inspect', action))

    def test_bad_component_config_does_not_block_shared_operation_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'config').write_text('not a directory')
            with operation_lock(root):
                self.assertEqual((root / '.operation.lock').stat().st_mode & 0o777, 0o600)

    def test_credential_rotation_needs_no_deployment_settings(self):
        spec = importlib.util.spec_from_file_location('credential_cli', ROOT / 'scripts/webapp-credentials.py')
        with tempfile.TemporaryDirectory() as folder:
            module = importlib.util.module_from_spec(spec)
            with patch.dict(os.environ, BAD), patch.object(deployment, 'ROOT', Path(folder)), \
                    patch.object(sys, 'argv', ['webapp-credentials.py', '--rotate']), \
                    patch.object(deployment, 'settings', side_effect=AssertionError('unrelated validation')), \
                    redirect_stdout(io.StringIO()):
                spec.loader.exec_module(module)
            self.assertTrue((Path(folder) / 'config/webapp/auth.json').is_file())


class DefaultPublicationTests(unittest.TestCase):
    def test_failed_publication_leaves_no_final_file_and_retry_is_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config'
            for operation in ('fsync', 'link'):
                with patch.object(private_files.os, operation, side_effect=OSError('injected interruption')), \
                        self.assertRaises(OSError):
                    private_files.publish_default(path, b'complete default', 0o600)
                self.assertFalse(path.exists())
                self.assertEqual(list(path.parent.iterdir()), [])
            self.assertTrue(private_files.publish_default(path, b'complete default', 0o600))
            self.assertEqual(path.read_bytes(), b'complete default')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_concurrent_operator_file_and_its_permissions_win(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config'
            def winner(*args):
                path.write_text('operator choice')
                path.chmod(0o640)
                raise FileExistsError()
            with patch.object(private_files.os, 'link', side_effect=winner):
                self.assertFalse(private_files.publish_default(path, b'default', 0o600))
            self.assertEqual(path.read_text(), 'operator choice')
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_failed_source_read_does_not_publish_empty_host_defaults(self):
        spec = importlib.util.spec_from_file_location('defaults_init', ROOT / 'scripts/init-config.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(FileNotFoundError):
                module.initialize(root)
            self.assertFalse((root / '.env').exists())
            (root / '.env.example').write_text('SETTING=value\n')
            with self.assertRaises(FileNotFoundError):
                module.initialize(root)
            self.assertEqual((root / '.env').read_text(), 'SETTING=value\n')
            self.assertFalse((root / 'config/network/mcp-allowlist.json').exists())
