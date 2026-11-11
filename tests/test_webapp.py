"""Ingress selection, exact hosts, credential format and Funnel publication gates."""
import importlib.util
import json
import subprocess
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'components/webapp'))
from settings import Settings, proxy_config
from auth import hash_password, validate

spec = importlib.util.spec_from_file_location('funnel', ROOT / 'components/tailscale/funnel.py')
funnel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(funnel)


def values(**changes):
    defaults = dict(external_content='tor_proxied', funnel_enabled='false', webapp_bind='127.0.0.1',
                    webapp_port='9120', webapp_username='admin', funnel_host='',
                    funnel_port='443', tailscale_hostname='private-hermes')
    return {**defaults, **changes}



class WebappTests(unittest.TestCase):
    def test_invalid_or_inconsistent_settings_refuse_activation(self):
        for change in ({'external_content': ''}, {'external_content': 'invalid'}, {'funnel_enabled': '1'},
                       {'webapp_bind': '0.0.0.0'}, {'webapp_port': '9120;evil'},
                       {'funnel_enabled': 'true'}, {'funnel_host': '*.example.ts.net'},
                       {'funnel_host': 'example.ts.net\nattack'}, {'funnel_port': '80'},
                       {'webapp_username': 'admin\nuser'},
                       {'funnel_enabled': 'true', 'funnel_host': 'node.example.ts.net', 'webapp_port': '8443'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                Settings.read(values(**change))

    def test_external_content_is_required_and_all_modes_parse(self):
        absent = values()
        del absent['external_content']
        with self.assertRaises(KeyError):
            Settings.read(absent)
        for mode in ('tor_proxied', 'ask', 'off', 'browser_native'):
            selected = Settings.read(values(external_content=mode))
            self.assertEqual(selected.external_content, mode)
            self.assertTrue(proxy_config(selected).startswith(f'# WEBAPP_EXTERNAL_CONTENT={mode}\n'))

    def test_proxy_keeps_authorities_separate_and_removes_all_forwarded_headers(self):
        text = proxy_config(Settings.read(values()))
        self.assertIn('127.0.0.1:9120', text)
        self.assertNotIn('bind 10.203.87.3:8443', text)
        self.assertIn('http-request del-header x-forwarded- -m beg', text)
        self.assertIn('http-request del-header Forwarded', text)
        self.assertNotIn('option forwardfor', text)
        text = proxy_config(Settings.read(values(funnel_enabled='true', funnel_host='test.example.ts.net')))
        self.assertIn('test.example.ts.net:443 test.example.ts.net', text)
        self.assertIn('X-Forwarded-Proto https', text)
        self.assertIn('server agent 10.203.85.2:9120', text)
        self.assertIn('http-response add-header Content-Security-Policy', text)
        self.assertIn("font-src 'self' data:; style-src 'self' 'unsafe-inline'", text)
        self.assertNotIn('http-response set-header Content-Security-Policy', text)

    def test_loopback_forwarder_listens_on_all_proxy_addresses(self):
        # Rootless Podman's port forwarder connects over loopback to a proxy address.
        docker = proxy_config(Settings.read(values()))
        self.assertEqual(docker.splitlines()[1], '# PORT_FORWARDER=interface')
        self.assertIn('bind ${PRIVATE_HERMES_EDGE_IP}:9120', docker)
        podman = proxy_config(Settings.read(values()), loopback_forwarder=True)
        self.assertEqual(podman.splitlines()[1], '# PORT_FORWARDER=loopback')
        self.assertIn('    bind :9120\n', podman)
        self.assertNotIn('PRIVATE_HERMES_EDGE_IP', podman)
        funnel = proxy_config(Settings.read(values(funnel_enabled='true', funnel_host='node.example.ts.net')),
                              loopback_forwarder=True)
        self.assertIn('bind 10.203.87.3:8443', funnel)
        self.assertIn('    bind :9120\n', funnel)

    def test_generated_native_hash_format_and_signing_secret_are_validated(self):
        credentials = {'password_hash': hash_password('disposable test password'), 'secret': 's' * 64}
        self.assertEqual(validate(credentials), credentials)
        with self.assertRaises(ValueError):
            validate({**credentials, 'secret': 'short'})

    def test_disabled_funnel_never_starts_containerboot(self):
        with patch.dict(funnel.os.environ, {'TAILSCALE_FUNNEL_ENABLED': 'false'}), patch.object(funnel.subprocess, 'Popen') as spawn:
            with self.assertRaises(SystemExit):
                funnel.main()
            spawn.assert_not_called()

    def test_funnel_checks_dns_before_publication_and_resets_on_shutdown(self):
        for actual, expected_error in [('wrong.example.ts.net', RuntimeError), ('test.example.ts.net', KeyboardInterrupt)]:
            child = Mock()
            child.poll.return_value = None
            commands = []
            def cli(*args, **kwargs):
                commands.append(args)
                return Mock(returncode=0, stdout=json.dumps({'BackendState': 'Running', 'Self': {'DNSName': actual + '.'}}))
            environment = {'TAILSCALE_FUNNEL_ENABLED': 'true', 'TAILSCALE_FUNNEL_HOST': 'test.example.ts.net',
                           'TAILSCALE_FUNNEL_PORT': '443', 'TS_AUTHKEY': 'test-only-key'}
            with patch.dict(funnel.os.environ, environment), patch.object(funnel.subprocess, 'Popen', return_value=child), patch.object(funnel, 'cli', side_effect=cli), patch.object(funnel, 'publish') as publish, patch.object(funnel.signal, 'signal'), patch.object(funnel.time, 'sleep', side_effect=KeyboardInterrupt):
                with self.assertRaises(expected_error):
                    funnel.main()
                writes = [call.args[0] for call in publish.call_args_list]
                self.assertEqual(writes[0], {})
                self.assertEqual(writes[-1], {})
                if actual.startswith('wrong'):
                    self.assertEqual(len(writes), 2)
                else:
                    self.assertEqual(writes[1], funnel.serve_config(actual, 443))
                self.assertIn(('funnel', 'reset'), commands)
                child.terminate.assert_called_once()


class ShutdownTests(unittest.TestCase):
    def test_shutdown_ignores_invalid_activation_settings_and_still_runs_down_after_reset_failure(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        import stack
        import os
        with patch.dict(os.environ, {'TAILSCALE_FUNNEL_ENABLED':'bad', 'TEEP_HOST_PORT':'invalid'}), patch.object(sys,'argv',['stack.py','down']), patch.object(stack,'settings',side_effect=AssertionError('Unrelated settings validation')), patch.object(stack,'stop_funnel',side_effect=RuntimeError('test reset failure')), patch.object(stack,'run') as run:
            with self.assertRaises(RuntimeError):
                # Shutdown behavior must not acquire the operator's real lock.
                stack.main_unlocked()
            self.assertIn('down', run.call_args.args[0])
            self.assertNotIn('--volumes', run.call_args.args[0])
            self.assertNotIn('-v', run.call_args.args[0])

    def test_startup_runs_setup_once_before_gateway_without_starting_funnel(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        import stack
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auth_path = root / 'config/webapp/auth.json'
            auth_path.parent.mkdir(parents=True)
            credentials = {'password_hash':hash_password('test-only-password'),'secret':'s'*64}
            auth_path.write_text(json.dumps(credentials))
            with patch.object(sys,'argv',['stack.py','up']), patch.object(stack,'ROOT',root), patch.object(stack,'settings',return_value=Settings.read(values())), patch.object(stack,'render') as render, patch.object(stack,'stop_funnel') as disable, patch.object(stack,'run') as run, patch.object(stack,'Controller'), patch.object(stack,'initialize_setup') as provision, patch.object(stack, 'initialize_research_config') as seed, patch.object(stack, 'require_inference_key'), patch.object(stack, 'ensure_networks'):
                events = []
                run.side_effect = lambda command: events.append(command)
                provision.side_effect = lambda command: events.append(['offline-setup'])
                stack.main()
                commands = [call.args[0] for call in run.call_args_list]
                provision.assert_called_once()
                build = next(c for c in commands if c[-1] == 'build')
                self.assertEqual(build[-3:], ['--profile', 'x402_treazury', 'build'])
                self.assertLess(events.index(build), events.index(['offline-setup']))
                gateway = next(i for i,c in enumerate(commands) if '--force-recreate' in c and c[-1]=='hermes')
                self.assertLess(events.index(['offline-setup']), events.index(commands[gateway]))
                self.assertTrue(any('--force-recreate' in c and 'webapp-proxy' in c for c in commands))
                self.assertFalse(any('up' in c and 'tailscale' in c for c in commands))
                self.assertNotIn(credentials['secret'],json.dumps(commands))
                disable.assert_called_once()
                run.reset_mock()
                provision.side_effect = RuntimeError('test setup failure')
                with self.assertRaisesRegex(RuntimeError, 'test setup failure'):
                    stack.main()
                self.assertFalse(any('up' in call.args[0] for call in run.call_args_list))
                provision.reset_mock()
                disable.reset_mock()
                render.reset_mock()
                seed.reset_mock()
                def fail_build(command):
                    if command[-1] == 'build':
                        raise subprocess.CalledProcessError(1, command)
                run.side_effect = fail_build
                with self.assertRaises(subprocess.CalledProcessError):
                    stack.main()
                provision.assert_not_called()
                disable.assert_not_called()
                render.assert_not_called()
                seed.assert_not_called()

    def test_funnel_startup_does_not_restart_setup_dependencies(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        import stack
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auth = root / 'config/webapp/auth.json'
            auth.parent.mkdir(parents=True)
            auth.write_text(json.dumps({'password_hash': hash_password('test-password'), 'secret': 's'*64}))
            selected = Settings.read(values(funnel_enabled='true', funnel_host='node.example.ts.net'))
            with patch.object(sys, 'argv', ['stack.py', 'up']), patch.object(stack, 'ROOT', root), \
                    patch.object(stack, 'settings', return_value=selected), patch.object(stack, 'render'), \
                    patch.object(stack, 'initialize_setup') as setup, patch.object(stack, 'Controller'), \
                    patch.object(stack, 'initialize_research_config'), \
                    patch.object(stack, 'require_inference_key'), \
                    patch.object(stack, 'ensure_networks'), \
                    patch.object(stack, 'run') as run:
                stack.main()
                setup.assert_called_once()
                builds = [call.args[0] for call in run.call_args_list if call.args[0][-1] == 'build']
                self.assertEqual(len(builds), 1)
                self.assertIn('compose.funnel.yaml', builds[0])
                startups = [call.args[0] for call in run.call_args_list if 'up' in call.args[0]]
                self.assertTrue(any(command[-1] == 'tailscale' for command in startups))
                self.assertTrue(all('--no-deps' in command for command in startups))
