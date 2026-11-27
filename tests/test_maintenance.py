"""Maintenance remains available without weakening application launch checks."""
from contextlib import redirect_stderr, redirect_stdout
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
            os.environ.pop('COMPOSE_PROJECT_NAME', None)
            os.environ.pop('NETWORK_PREFIX', None)
            command = deployment.maintenance_compose(all_ingress=True, executor_build=True)
            result = subprocess.run([*command, '--env-file', '/dev/null', 'config', '--format', 'json'],
                                    cwd=ROOT, check=True, capture_output=True, text=True)
        executor = json.loads(result.stdout)['services']['executor']
        self.assertEqual(executor['build']['target'], 'executor-true')
        self.assertEqual(executor['image'], 'private-hermes-executor-true:local')

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
                    ['run', '--rm', '--no-deps', '--entrypoint', '/usr/local/bin/x402_treazury',
                     'x402_treazury-admin', 'config', 'show'],
                    ['run', '--rm', '--no-deps', '--volume', '/private/backup:/backup',
                     '--entrypoint', '/usr/local/bin/x402_treazury', 'x402_treazury-inspect', 'wallet', 'backup'])
        for command in commands:
            with patch.dict(os.environ, BAD), patch.object(sys, 'argv', ['stack.py', 'compose', *command]), \
                    patch.object(stack, 'settings', side_effect=AssertionError('unrelated validation')), \
                    patch.object(stack, 'run') as run, patch.object(stack, 'inspect_launch'):
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
                patch.object(stack, 'ensure_research_config_dir', side_effect=AssertionError('policy directory')), \
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
                patch('x402_treazury.ensure_research_config_dir') as seed, redirect_stdout(io.StringIO()):
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

    def test_x402_config_commands_stay_offline_despite_invalid_network_and_ingress_settings(self):
        import x402_treazury
        for action, target in (('config', 'initialize_research_config'),
                               ('config-diff', 'research_config_diff'),
                               ('config-merge', 'merge_research_config'),
                               ('config-reset', 'reset_research_config')):
            with self.subTest(action=action), patch.dict(os.environ, dict(BAD, NETWORK_PREFIX='invalid')), \
                    patch.object(sys, 'argv', ['x402_treazury.py', action]), \
                    patch.object(x402_treazury, 'operation_lock'), \
                    patch.object(x402_treazury, target, return_value=False) as fn, \
                    redirect_stdout(io.StringIO()):
                x402_treazury.main()
            fn.assert_called_once()

    def _run_credentials_cli(self, root, *argv, env=None):
        spec = importlib.util.spec_from_file_location('credential_cli', ROOT / 'scripts/webapp-credentials.py')
        module = importlib.util.module_from_spec(spec)
        stdout, stderr = io.StringIO(), io.StringIO()
        environment = {key: value for key, value in os.environ.items() if key != 'WEBAPP_USERNAME'}
        if env:
            environment.update(env)
        with patch.dict(os.environ, environment, clear=True), patch.object(deployment, 'ROOT', root), \
                patch.object(sys, 'argv', ['webapp-credentials.py', *argv]), \
                patch.object(deployment, 'settings', side_effect=AssertionError('unrelated validation')), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            spec.loader.exec_module(module)
            module.main()
        return stdout.getvalue(), stderr.getvalue()

    def test_credential_rotation_needs_no_deployment_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stdout, _ = self._run_credentials_cli(root, '--rotate', env=BAD)
            self.assertTrue((root / 'config/webapp/auth.json').is_file())
            password = (root / 'config/webapp/password').read_text().strip()
            self.assertIn('admin', stdout)
            self.assertIn('config/webapp/password', stdout)
            self.assertNotIn(password, stdout)

    def test_webapp_credentials_reports_username_and_password_path_for_existing_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.env').write_text('WEBAPP_BIND=invalid\nWEBAPP_USERNAME=alice\n', encoding='utf-8')
            generated, _ = self._run_credentials_cli(root)
            password = (root / 'config/webapp/password').read_text().strip()
            self.assertIn('alice', generated)
            self.assertIn('config/webapp/password', generated)
            self.assertNotIn(password, generated)

            existing, _ = self._run_credentials_cli(root)
            self.assertIn('credentials for alice are in config/webapp/password', existing)
            self.assertNotIn(password, existing)

            overridden, _ = self._run_credentials_cli(root, env={'WEBAPP_USERNAME': 'bob'})
            self.assertIn('credentials for bob are in config/webapp/password', overridden)
            self.assertNotIn(password, overridden)

            blank_env, _ = self._run_credentials_cli(root, env={'WEBAPP_USERNAME': ''})
            self.assertIn('credentials for admin are in config/webapp/password', blank_env)
            self.assertNotIn(password, blank_env)

    def test_webapp_credentials_handles_missing_password_and_invalid_username_without_blocking(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._run_credentials_cli(root)
            (root / 'config/webapp/password').unlink()
            stdout, stderr = self._run_credentials_cli(root)
            self.assertIn('admin', stdout)
            self.assertIn('config/webapp/password is missing or empty', stdout)
            self.assertIn('make webapp-rotate', stderr)

            (root / 'config/webapp/password').write_text('   \n', encoding='utf-8')
            empty_out, empty_err = self._run_credentials_cli(root)
            self.assertIn('config/webapp/password is missing or empty', empty_out)
            self.assertIn('make webapp-rotate', empty_err)

            self._run_credentials_cli(root, '--rotate')
            (root / '.env').write_text('WEBAPP_USERNAME=bad user!\n', encoding='utf-8')
            invalid_out, _ = self._run_credentials_cli(root)
            self.assertIn('config/webapp/password', invalid_out)
            self.assertIn('WEBAPP_USERNAME in .env is invalid', invalid_out)
            self.assertNotIn('bad user!', invalid_out)

            invalid_env, _ = self._run_credentials_cli(root, env={'WEBAPP_USERNAME': 'bad env!'})
            self.assertIn('WEBAPP_USERNAME in the environment is invalid', invalid_env)
            self.assertNotIn('bad env!', invalid_env)

            (root / '.env').write_text('WEBAPP_USERNAME=alice\nTEEP_SERVE_ARGS="unclosed\n', encoding='utf-8')
            malformed_out, _ = self._run_credentials_cli(root)
            self.assertIn('config/webapp/password', malformed_out)
            self.assertIn('could not be read from .env', malformed_out)
            self.assertNotIn('alice', malformed_out)

            custom = root / 'custom.env'
            custom.write_text('WEBAPP_USERNAME=carol\n', encoding='utf-8')
            custom_out, _ = self._run_credentials_cli(root, env={'COMPOSE_ENV_FILES': str(custom)})
            self.assertIn('credentials for carol are in config/webapp/password', custom_out)

            custom.write_text('WEBAPP_USERNAME=carol\nBAD="unclosed\n', encoding='utf-8')
            custom_bad_out, _ = self._run_credentials_cli(root, env={'COMPOSE_ENV_FILES': str(custom)})
            self.assertIn(str(custom), custom_bad_out)
            self.assertNotIn('could not be read from .env', custom_bad_out)

            dot_local = root / '.env.local'
            dot_local.write_text('WEBAPP_USERNAME=carol\nBAD="unclosed\n', encoding='utf-8')
            dot_local_out, _ = self._run_credentials_cli(root, env={'COMPOSE_ENV_FILES': '.env.local'})
            self.assertIn(str(dot_local), dot_local_out)
            self.assertNotIn('could not be read from .env', dot_local_out)


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
