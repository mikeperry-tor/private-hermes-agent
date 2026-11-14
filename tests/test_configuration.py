"""Verify operator config preservation and Compose credential separation."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from deployment import compose_base  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('init_config', ROOT / 'scripts/init-config.py')
init_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(init_config)


class OperatorConfigurationTests(unittest.TestCase):
    def test_computer_use_selects_one_executor_and_scoped_syscall_policy(self):
        models = {}
        for enabled in ('false', 'true'):
            result = subprocess.run([*compose_base(), '-f', 'compose.yaml', 'config', '--format', 'json'],
                                    cwd=ROOT, env=dict(os.environ, COMPUTER_USE_ENABLED=enabled),
                                    text=True, capture_output=True, check=True)
            services = json.loads(result.stdout)['services']
            executor = services['executor']
            self.assertFalse({'executor-false', 'executor-true'} & services.keys())
            self.assertEqual(executor['build']['target'], 'executor-' + enabled)
            self.assertEqual(services['hermes']['environment']['COMPUTER_USE_ENABLED'], enabled)
            self.assertTrue(executor['read_only'])
            self.assertEqual(set(executor['cap_add']), {'CHOWN', 'SETUID', 'SETGID', 'SYS_CHROOT'})
            self.assertIn('no-new-privileges:true', executor['security_opt'])
            self.assertEqual(any(x.startswith('seccomp=') for x in executor['security_opt']), enabled == 'true')
            models[enabled] = executor
        for key in ('volumes', 'network_mode', 'cap_add', 'cap_drop', 'tmpfs', 'image'):
            self.assertEqual(models['false'][key], models['true'][key], key)
        result = subprocess.run([*compose_base(), '-f', 'compose.yaml', 'config', '--quiet'],
                                cwd=ROOT, env=dict(os.environ, COMPUTER_USE_ENABLED='invalid'),
                                capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_terminal_mode_maps_only_to_hermes_on_both_models(self):
        for overlay in ([], ['-f', 'compose.podman.yaml']):
            for mode in ('code', 'agent', ''):
                env = dict(os.environ, WEBAPP_TERMINAL_ENVIRONMENT=mode)
                result = subprocess.run([*compose_base(), '-f', 'compose.yaml', *overlay,
                                         'config', '--format', 'json'], cwd=ROOT, env=env,
                                        text=True, capture_output=True, check=True)
                model = json.loads(result.stdout)
                self.assertEqual(model['x-deployment']['terminal_environment'], mode)
                recipients = {name: service['environment']['WEBAPP_TERMINAL_ENVIRONMENT']
                              for name, service in model['services'].items()
                              if 'WEBAPP_TERMINAL_ENVIRONMENT' in service.get('environment', {})}
                self.assertEqual(recipients, {'hermes': mode})
        result = subprocess.run([*compose_base(), '--env-file', '/dev/null', '-f', 'compose.yaml',
                                 'config', '--format', 'json'], cwd=ROOT,
                                env={k: v for k, v in os.environ.items() if k != 'WEBAPP_TERMINAL_ENVIRONMENT'},
                                text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)['services']['hermes']['environment']['WEBAPP_TERMINAL_ENVIRONMENT'], 'code')

    def seed(self, root):
        (root / '.env.example').write_text('VENICE_API_KEY=\n')
        defaults = root / 'components/network'
        defaults.mkdir(parents=True)
        (defaults / 'mcp-allowlist.json').write_text('[]\n')

    def test_existing_settings_survive_initialization_and_repeated_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.seed(root)
            original = '# Preserve quoted settings\nVENICE_API_KEY="private value"\nOTHER_SETTING=yes\n'
            (root / '.env').write_text(original)
            (root / '.env').chmod(0o640)
            policy = root / 'config/network/mcp-allowlist.json'
            policy.parent.mkdir(parents=True)
            custom = '[{"ip":"10.203.84.10","port":8000}]\n'
            policy.write_text(custom)
            init_config.initialize(root)
            first = (root / '.env').read_text()
            auth = (root / 'config/webapp/auth.json').read_bytes()
            password = (root / 'config/webapp/password').read_bytes()
            self.assertEqual(first, original)
            init_config.initialize(root)
            self.assertEqual((root / '.env').read_text(), first)
            self.assertEqual((root / 'config/webapp/auth.json').read_bytes(), auth)
            self.assertEqual((root / 'config/webapp/password').read_bytes(), password)
            self.assertEqual(policy.read_text(), custom)
            self.assertEqual((root / '.env').stat().st_mode & 0o777, 0o640)

    def test_fresh_initialization_copies_defaults_and_protects_env(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.seed(root)
            init_config.initialize(root)
            self.assertEqual((root / '.env').read_text(), (root / '.env.example').read_text())
            self.assertEqual((root / '.env').stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / 'config/network/mcp-allowlist.json').read_text(), '[]\n')
            for name in ('auth.json', 'password'):
                self.assertEqual((root / 'config/webapp' / name).stat().st_mode & 0o777, 0o600)
            # Verify the saved password actually matches the native hash.
            import base64, hashlib
            credentials = json.loads((root / 'config/webapp/auth.json').read_text())
            password = (root / 'config/webapp/password').read_text().strip()
            _, n, r, p, salt, digest = credentials['password_hash'].split('$')
            calculated = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt),
                                         n=int(n), r=int(r), p=int(p), dklen=32)
            self.assertEqual(calculated, base64.b64decode(digest))

    def test_wallet_initialization_ignores_invalid_webapp_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.seed(root)
            auth = root / 'config/webapp/auth.json'
            auth.parent.mkdir(parents=True)
            auth.write_text('invalid webapp auth')
            init_config.initialize(root, wallet_only=True)
            self.assertEqual(auth.read_text(), 'invalid webapp auth')
            self.assertFalse((auth.parent / 'password').exists())
            self.assertFalse((auth.parent / 'proxy.cfg').exists())

    def test_compose_passes_credentials_only_to_their_intended_services(self):
        provider_keys = ('VENICE_API_KEY', 'NEARAI_API_KEY', 'CHUTES_API_KEY',
                         'TINFOIL_API_KEY', 'NANOGPT_API_KEY', 'PHALA_API_KEY')
        secrets = {key: 'test-only-' + key for key in (*provider_keys, 'BASE_RPC_URL', 'TS_AUTHKEY')}
        environment = dict(os.environ, **secrets, TEEP_HOST_PORT='18337',
                           HERMES_DEFAULT_MODEL='neardirect:qualification/custom-model',
                           TEEP_SERVE_ARGS="--log-level 'debug'")
        result = subprocess.run([*compose_base(), '-f', 'compose.yaml', '-f', 'compose.funnel.yaml', '--profile', '*', 'config', '--format', 'json'],
                                cwd=ROOT, env=environment, text=True,
                                capture_output=True, check=True)
        services = json.loads(result.stdout)['services']
        self.assertEqual(services['teep']['command'], ['serve', '--log-level', 'debug'])
        self.assertEqual(services['teep']['environment']['TEEP_LISTEN_ADDR'], '0.0.0.0:8337')
        self.assertEqual(services['setup']['environment']['HERMES_DEFAULT_MODEL'],
                         environment['HERMES_DEFAULT_MODEL'])
        for name, service in services.items():
            if name != 'setup':
                self.assertNotIn('HERMES_DEFAULT_MODEL', service.get('environment', {}), name)
        publication = services['teep']['ports']
        self.assertEqual(len(publication), 1)
        self.assertEqual(publication[0]['host_ip'], '127.0.0.1')
        self.assertEqual(publication[0]['target'], 8337)
        self.assertEqual(publication[0]['published'], '18337')
        self.assertNotIn('TEEP_HOST_PORT', services['teep']['environment'])
        for name, service in services.items():
            supplied = service.get('environment', {})
            expected = set(provider_keys) if name == 'teep' else {'TS_AUTHKEY'} if name == 'tailscale' else set()
            self.assertEqual(set(secrets) & set(supplied), expected, name)
            for key in expected:
                self.assertEqual(supplied[key], secrets[key])
            self.assertNotIn('env_file', service)
        auth_recipients = [name for name, service in services.items()
                           if any(mount.get('target') == '/run/webapp'
                                  for mount in service.get('volumes', []))]
        self.assertEqual(auth_recipients, ['setup'])
        self.assertTrue({'storage-init', 'bootstrap', 'configure', 'x402_treazury-config'}.isdisjoint(services))
        self.assertEqual(services['setup']['build'], services['hermes']['build'])
        self.assertEqual(services['setup']['network_mode'], 'none')
        self.assertTrue(services['setup']['read_only'])
        self.assertNotIn('/opt/data', services['setup']['environment']['PATH'])
        self.assertNotIn('webapp-setup', services)
        self.assertIn('webapp-proxy', services)
        self.assertEqual(services['x402_treazury-setup']['restart'], 'no')
        self.assertEqual(services['x402_treazury-setup']['stop_grace_period'], '-1s')
        self.assertEqual(services['hermes']['image'], services['setup']['image'])
        self.assertEqual(services['hermes']['image'], 'private-hermes-agent:local')
        self.assertEqual(services['hermes']['environment']['WEBAPP_EXTERNAL_CONTENT'], 'tor_proxied')
        self.assertNotIn('WEBAPP_EXTERNAL_CONTENT', services['executor']['environment'])


if __name__ == '__main__':
    unittest.main()
