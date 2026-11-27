"""Unit tests for multi-instance addressing, Compose rendering, and preflight checks."""
import asyncio
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'components/network'))
sys.path.insert(0, str(ROOT / 'components/provisioning'))
sys.path.insert(0, str(ROOT / 'components/webapp'))
sys.path.insert(0, str(ROOT / 'scripts'))

from addressing import (Addresses, DEFAULT_NETWORK_PREFIX, DEFAULT_PROJECT_NAME,
                        network_prefix, reserved_subnets,
                        validate_network_prefix, validate_project_name)
from auth import hash_password
import deployment
from deployment import compose_base
from integrations import grants
import preflight
from settings import Settings, proxy_config
import stack
from test_webapp import values as webapp_values
import x402_treazury


def _fake_yaml_load(data):
    return json.loads(data.decode() if isinstance(data, bytes) else data)


def _fake_yaml_dump(obj, stream=None, **_kwargs):
    text = json.dumps(obj, indent=2)
    if stream is not None:
        stream.write(text)
        return None
    return text


_bootstrap_spec = importlib.util.spec_from_file_location('bootstrap_mi', ROOT / 'components/provisioning/bootstrap.py')
bootstrap = importlib.util.module_from_spec(_bootstrap_spec)
with patch.dict(sys.modules, {'hermes_yaml': types.SimpleNamespace(
        safe_load=_fake_yaml_load, safe_dump=_fake_yaml_dump, YAMLError=ValueError)}):
    _bootstrap_spec.loader.exec_module(bootstrap)

_proxy_spec = importlib.util.spec_from_file_location('proxy_start_mi', ROOT / 'components/webapp/proxy-start.py')
proxy_start = importlib.util.module_from_spec(_proxy_spec)
_proxy_spec.loader.exec_module(proxy_start)

_funnel_spec = importlib.util.spec_from_file_location('funnel_mi', ROOT / 'components/tailscale/funnel.py')
funnel = importlib.util.module_from_spec(_funnel_spec)
_funnel_spec.loader.exec_module(funnel)

_network_spec = importlib.util.spec_from_file_location('network_mi', ROOT / 'components/network/network.py')
network_mod = importlib.util.module_from_spec(_network_spec)
_network_spec.loader.exec_module(network_mod)


class _FakePlainTextResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    async def __call__(self, _scope, _receive, send):
        await send({'type': 'http.response.start', 'status': self.status_code, 'headers': []})
        await send({'type': 'http.response.body', 'body': self.body.encode('utf-8')})


_browser_policy_spec = importlib.util.spec_from_file_location(
    'browser_policy_mi', ROOT / 'components/hermes/browser_policy.py',
)
browser_policy = importlib.util.module_from_spec(_browser_policy_spec)
with patch.dict(sys.modules, {
    'hermes_cli': types.ModuleType('hermes_cli'),
    'hermes_cli.private_external_content': types.SimpleNamespace(deployment_mode=lambda: 'tor_proxied'),
}):
    _browser_policy_spec.loader.exec_module(browser_policy)


class AddressingValidationTests(unittest.TestCase):
    def test_valid_network_prefixes(self):
        for prefix in ('10.0', '10.1', '10.203', '10.205', '10.255', '172.16', '172.24', '172.31', '192.168'):
            with self.subTest(prefix=prefix):
                self.assertEqual(validate_network_prefix(prefix), prefix)

    def test_invalid_network_prefixes_rejected(self):
        invalid = (
            '', ' ', '10.204', '10.256', '10.-1', '10.01', '010.203', '10.203.',
            ' 10.203', '10.203 ', '10.203.80', '172.15', '172.32', '172.016',
            '192.167', '192.169', '100.64', '8.8', '10.203/16', None, 10,
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_network_prefix(value)

    def test_valid_project_names(self):
        for name in ('private-hermes', 'a', 'agent-2', 'agent_2', 'a1-b2_c3', 'a' * 63):
            with self.subTest(name=name):
                self.assertEqual(validate_project_name(name), name)

    def test_invalid_project_names_rejected(self):
        invalid = (
            '', 'Private-Hermes', '-agent', 'agent-', '_agent', 'agent_',
            'agent__2', 'agent--2', 'agent_-2', 'agent-_2', 'agent 2',
            'agent/2', 'agent.2', 'a' * 64, None, 123,
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_project_name(value)

    def test_network_prefix_env_default_and_override(self):
        self.assertEqual(network_prefix({}), DEFAULT_NETWORK_PREFIX)
        self.assertEqual(network_prefix({'NETWORK_PREFIX': ''}), DEFAULT_NETWORK_PREFIX)
        self.assertEqual(network_prefix({'NETWORK_PREFIX': '10.205'}), '10.205')
        with self.assertRaises(ValueError):
            network_prefix({'NETWORK_PREFIX': '10.204'})

    def test_addresses_and_reserved_subnets(self):
        addrs = Addresses('172.22')
        self.assertEqual(addrs.tor_agent_route, '172.22.80.3')
        self.assertEqual(addrs.tor_executor_route, '172.22.81.3')
        self.assertEqual(addrs.tor_onion_ingress, '172.22.86.2')
        self.assertEqual(addrs.tor_uplink, '172.22.88.2')
        self.assertEqual(addrs.agent_webapp_backend, '172.22.85.2')
        self.assertEqual(addrs.executor_execution_control, '172.22.82.3')
        self.assertEqual(addrs.teep_inference, '172.22.83.3')
        self.assertEqual(addrs.proxy_webapp_backend, '172.22.85.3')
        self.assertEqual(addrs.proxy_onion_ingress, '172.22.86.3')
        self.assertEqual(addrs.proxy_funnel_link, '172.22.87.3')
        self.assertEqual(addrs.tailscale_funnel_link, '172.22.87.2')
        self.assertEqual(addrs.mcp_access_subnet, '172.22.84.0/24')
        reserved = reserved_subnets('172.22')
        self.assertIn(ipaddress.IPv4Network('172.22.80.0/24'), reserved)
        self.assertIn(ipaddress.IPv4Network('172.22.91.0/24'), reserved)
        self.assertIn(ipaddress.IPv4Network('10.204.80.0/30'), reserved)
        self.assertIn(ipaddress.IPv4Network('10.204.81.0/30'), reserved)
        self.assertNotIn(ipaddress.IPv4Network('10.203.80.0/24'), reserved)


class ComponentPrefixTests(unittest.TestCase):
    def test_integrations_grants_blocks_instance_prefix_and_connected_networks(self):
        env = {'NETWORK_PREFIX': '10.205', 'HERMES_INTEGRATIONS_LAN_ENDPOINTS': '10.205.85.2:9120'}
        with self.assertRaises(ValueError):
            grants(env)
        env_other = {'NETWORK_PREFIX': '10.205', 'HERMES_INTEGRATIONS_LAN_ENDPOINTS': '10.206.85.2:9120'}
        self.assertEqual(grants(env_other), ([], [('10.206.85.2', 9120)]))
        with self.assertRaises(ValueError):
            grants(env_other, connected=('10.206.85.0/24',))

    def test_settings_and_proxy_config_use_network_prefix(self):
        cfg = Settings.read(webapp_values(
            project_name='agent-two', network_prefix='10.205',
            funnel_enabled='true', funnel_host='agent-two.example.ts.net',
            onion_enabled='true',
        ))
        self.assertEqual(cfg.project_name, 'agent-two')
        self.assertEqual(cfg.network_prefix, '10.205')
        rendered = proxy_config(cfg, onion_host='a' * 56 + '.onion')
        self.assertIn('# NETWORK_PREFIX=10.205\n', rendered)
        self.assertIn('server agent 10.205.85.2:9120', rendered)
        self.assertIn('bind 10.205.87.3:8443', rendered)
        self.assertIn('unless { src 10.205.87.2 }', rendered)
        self.assertIn('bind 10.205.86.3:8080', rendered)
        self.assertIn('unless { src 10.205.86.2 }', rendered)
        self.assertNotIn('10.203.', rendered)

    def test_settings_rejects_invalid_project_name_or_network_prefix(self):
        with self.assertRaises(ValueError):
            Settings.read(webapp_values(project_name='Bad_Name_'))
        with self.assertRaises(ValueError):
            Settings.read(webapp_values(network_prefix='10.204'))

    def test_proxy_firewall_and_funnel_config_use_network_prefix(self):
        rules = proxy_start.firewall('interface', 'eth0', '10.205.90.2', 9121, True, True, prefix='10.205')
        self.assertIn('-s 10.205.87.2/32 -d 10.205.87.3/32 -p tcp --dport 8443', rules)
        self.assertIn('-s 10.205.86.2/32 -d 10.205.86.3/32 -p tcp --dport 8080', rules)
        self.assertIn('-d 10.205.85.2/32 -p tcp --dport 9120', rules)
        self.assertNotIn('10.203.', rules)
        serve = funnel.serve_config('agent-two.example.ts.net', 443, prefix='10.205')
        self.assertEqual(
            serve['Web']['agent-two.example.ts.net:443']['Handlers']['/']['Proxy'],
            'http://10.205.87.3:8443',
        )


class ComposeMultiInstanceModelTests(unittest.TestCase):
    def render_model(self, files, **env_overrides):
        env = {k: v for k, v in os.environ.items() if k not in ('COMPOSE_PROJECT_NAME', 'NETWORK_PREFIX')}
        env.update(env_overrides)
        args = [arg for name in files for arg in ('-f', name)]
        result = subprocess.run(
            [*compose_base(), '--env-file', '/dev/null', *args, '--profile', '*', 'config', '--format', 'json'],
            cwd=ROOT, env=env, text=True, capture_output=True, check=True,
        )
        return json.loads(result.stdout)

    def test_all_four_compose_models_render_distinct_project_images_and_prefix(self):
        overlays = (
            ('compose.yaml',),
            ('compose.yaml', 'compose.funnel.yaml'),
            ('compose.yaml', 'compose.podman.yaml'),
            ('compose.yaml', 'compose.funnel.yaml', 'compose.podman.yaml', 'compose.podman.funnel.yaml'),
        )
        for files in overlays:
            with self.subTest(files=files):
                model = self.render_model(files, COMPOSE_PROJECT_NAME='agent-two', NETWORK_PREFIX='10.205')
                self.assertEqual(model['name'], 'agent-two')
                self.assertEqual(model['x-deployment']['project_name'], 'agent-two')
                self.assertEqual(model['x-deployment']['network_prefix'], '10.205')
                services = model['services']
                for name, service in services.items():
                    self.assertTrue(service['image'].startswith('agent-two-'), f'{name}: {service["image"]}')
                    self.assertTrue(service['image'].endswith(':local'), f'{name}: {service["image"]}')
                self.assertEqual(services['tor']['networks']['agent-route']['ipv4_address'], '10.205.80.3')
                self.assertEqual(services['agent-net']['networks']['webapp-backend']['ipv4_address'], '10.205.85.2')
                self.assertEqual(services['executor-net']['networks']['execution-control']['ipv4_address'], '10.205.82.3')
                self.assertEqual(services['teep']['networks']['inference']['ipv4_address'], '10.205.83.3')
                self.assertEqual(services['webapp-proxy']['networks']['onion-ingress']['ipv4_address'], '10.205.86.3')
                self.assertEqual(services['hermes']['environment']['TERMINAL_SSH_HOST'], '10.205.82.3')
                self.assertNotIn('PRIVATE_HERMES_WEBAPP_BACKEND_IP', services['hermes']['environment'])
                self.assertEqual(services['hermes']['environment']['NETWORK_PREFIX'], '10.205')
                self.assertEqual(services['executor']['environment']['PRIVATE_HERMES_EXECUTOR_SSH_HOST'], '10.205.82.3')
                for net_name, net in model['networks'].items():
                    for entry in (net.get('ipam') or {}).get('config') or []:
                        self.assertTrue(entry['subnet'].startswith('10.205.'), f'{net_name}: {entry}')
                if 'compose.funnel.yaml' in files:
                    self.assertEqual(services['tailscale']['networks']['funnel-link']['ipv4_address'], '10.205.87.2')
                    self.assertEqual(services['webapp-proxy']['networks']['funnel-link']['ipv4_address'], '10.205.87.3')

        desktop_model = self.render_model(
            ('compose.yaml',), COMPOSE_PROJECT_NAME='agent-two', NETWORK_PREFIX='10.205',
            COMPUTER_USE_ENABLED='true',
        )
        self.assertEqual(desktop_model['services']['executor']['image'], 'agent-two-executor-true:local')
        self.assertEqual(
            desktop_model['services']['executor']['environment']['PRIVATE_HERMES_EXECUTOR_SSH_HOST'],
            '10.205.82.3',
        )

    def test_preflight_conflict_diagnostic_guides_to_network_prefix(self):
        config = {
            'networks': {
                'agent-route': {'ipam': {'config': [{'subnet': '10.203.80.0/24'}]}},
            }
        }
        existing = [{
            'Name': 'private-hermes_agent-route',
            'Labels': {'com.docker.compose.project': 'private-hermes', 'com.docker.compose.network': 'agent-route'},
            'IPAM': {'Config': [{'Subnet': '10.203.80.0/24'}]},
        }]
        with self.assertRaises(SystemExit) as error:
            preflight.check_address_conflicts('agent-two', config, existing)
        message = str(error.exception)
        self.assertIn('NETWORK_PREFIX', message)
        self.assertIn('10.203.80.0/24', message)


class RuntimeConfigAndProvisioningTests(unittest.TestCase):
    def test_render_writes_resolv_conf_and_proxy_with_expected_modes(self):
        cfg = Settings.read(webapp_values(project_name='agent-two', network_prefix='10.205'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(deployment, 'ROOT', root), patch.object(deployment, 'engine', return_value='docker'):
                deployment.render(cfg)
            hermes_resolv = root / 'config/network/hermes-resolv.conf'
            executor_resolv = root / 'config/network/executor-resolv.conf'
            proxy_cfg = root / 'config/webapp/proxy.cfg'
            self.assertEqual(hermes_resolv.read_text(), 'nameserver 10.205.80.3\noptions timeout:5 attempts:2\n')
            self.assertEqual(executor_resolv.read_text(), 'nameserver 10.205.81.3\noptions timeout:5 attempts:2\n')
            self.assertIn('# NETWORK_PREFIX=10.205\n', proxy_cfg.read_text())
            self.assertEqual((root / 'config/network').stat().st_mode & 0o777, 0o755)
            self.assertEqual(hermes_resolv.stat().st_mode & 0o777, 0o644)
            self.assertEqual(executor_resolv.stat().st_mode & 0o777, 0o644)
            self.assertEqual(proxy_cfg.stat().st_mode & 0o777, 0o644)

    def test_maintenance_compose_fallback_vs_strict_network_prefix(self):
        with patch.dict(os.environ, {'COMPOSE_PROJECT_NAME': 'agent-two', 'NETWORK_PREFIX': '10.204'}):
            command = deployment.maintenance_compose(allow_invalid_network=True)
            self.assertEqual(os.environ['COMPOSE_PROJECT_NAME'], 'agent-two')
            self.assertEqual(os.environ['NETWORK_PREFIX'], '10.204')
            self.assertIn(f'NETWORK_PREFIX={DEFAULT_NETWORK_PREFIX}', command)
        with patch.dict(os.environ, {'COMPOSE_PROJECT_NAME': 'agent-two', 'NETWORK_PREFIX': '10.204'}):
            with self.assertRaises(ValueError):
                deployment.maintenance_compose(allow_invalid_network=False)

    def test_x402_prepare_restores_env_and_rejects_invalid_prefix_without_running_stack(self):
        with patch.dict(os.environ, {'COMPOSE_PROJECT_NAME': 'agent-two', 'NETWORK_PREFIX': '10.204'}), \
                patch.object(sys, 'argv', ['x402_treazury.py', 'prepare']), \
                patch.object(x402_treazury, '_running_stack_prefix', return_value=None):
            with self.assertRaises(ValueError):
                x402_treazury.main()
            self.assertEqual(os.environ['NETWORK_PREFIX'], '10.204')

        with patch.dict(os.environ, {'COMPOSE_PROJECT_NAME': 'agent-two', 'NETWORK_PREFIX': '10.204'}), \
                patch.object(sys, 'argv', ['x402_treazury.py', 'prepare']), \
                patch.object(x402_treazury, '_running_stack_prefix', return_value='10.205'), \
                patch.object(x402_treazury, 'operation_lock'), \
                patch.object(x402_treazury, 'Controller') as controller_cls:
            x402_treazury.main()
            self.assertEqual(os.environ['NETWORK_PREFIX'], '10.204')
            self.assertIn('NETWORK_PREFIX=10.205', controller_cls.call_args.args[0])
            controller_cls.return_value.prepare.assert_called_once()

    def test_x402_running_stack_prefix_checks_agent_net_and_pre_upgrade_containers(self):
        # Single compose ps call returns running containers across agent-net, hermes, and tor,
        # and agent-net takes priority regardless of compose ps ordering.
        def fake_run_agent_net(args, **_kwargs):
            if 'ps' in args and '-a' not in args:
                self.assertEqual(args[-3:], ['agent-net', 'hermes', 'tor'])
                return subprocess.CompletedProcess(args, 0, stdout='cid-tor\ncid-agent-net\n', stderr='')
            if 'inspect' in args:
                self.assertEqual(args[-2:], ['cid-tor', 'cid-agent-net'])
                stdout = (
                    'tor ' + json.dumps(['NETWORK_PREFIX=10.206']) + '\n'
                    'agent-net ' + json.dumps(['NETWORK_PREFIX=10.205']) + '\n'
                )
                return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr='')
            return subprocess.CompletedProcess(args, 0, stdout='', stderr='')

        with patch.object(x402_treazury, 'maintenance_compose', return_value=['docker', 'compose']) as maint, \
                patch.object(x402_treazury, 'engine_command', return_value=['docker']), \
                patch.object(x402_treazury.subprocess, 'run', side_effect=fake_run_agent_net):
            self.assertEqual(x402_treazury._running_stack_prefix(), '10.205')
        maint.assert_called_once_with(validate_project=True)

        # Pre-upgrade running hermes without NETWORK_PREFIX in Config.Env defaults to 10.203.
        def fake_run_pre_upgrade(args, **_kwargs):
            if 'ps' in args and '-a' not in args:
                return subprocess.CompletedProcess(args, 0, stdout='cid-hermes\n', stderr='')
            if 'inspect' in args:
                return subprocess.CompletedProcess(
                    args, 0, stdout='hermes ' + json.dumps(['PATH=/usr/bin']) + '\n', stderr='',
                )
            return subprocess.CompletedProcess(args, 0, stdout='', stderr='')

        with patch.object(x402_treazury, 'maintenance_compose', return_value=['docker', 'compose']), \
                patch.object(x402_treazury, 'engine_command', return_value=['docker']), \
                patch.object(x402_treazury.subprocess, 'run', side_effect=fake_run_pre_upgrade):
            self.assertEqual(x402_treazury._running_stack_prefix(), DEFAULT_NETWORK_PREFIX)

    def test_x402_cold_start_init_uses_configured_prefix_without_double_project_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('COMPOSE_PROJECT_NAME=agent-two\nNETWORK_PREFIX=10.205\n', encoding='utf-8')
            with patch.object(deployment, 'ROOT', root), \
                    patch.object(deployment, 'compose_base', return_value=['docker', 'compose']), \
                    patch.object(deployment, 'compose_files', return_value=['-f', 'compose.yaml']), \
                    patch.object(deployment, 'validate_project_name', wraps=deployment.validate_project_name) as validate_project, \
                    patch.dict(os.environ), \
                    patch.object(sys, 'argv', ['x402_treazury.py', 'init']), \
                    patch.object(x402_treazury, '_running_stack_prefix', return_value=None) as prefix_mock, \
                    patch.object(x402_treazury, 'operation_lock'), \
                    patch.object(x402_treazury, 'Controller') as controller_cls:
                os.environ.pop('COMPOSE_PROJECT_NAME', None)
                os.environ.pop('NETWORK_PREFIX', None)
                x402_treazury.main()
            self.assertEqual(validate_project.call_count, 1)
            self.assertEqual(prefix_mock.call_count, 1)
            probe_command = prefix_mock.call_args.args[0]
            self.assertEqual(probe_command[0], 'env')
            self.assertIn(f'NETWORK_PREFIX={DEFAULT_NETWORK_PREFIX}', probe_command)
            controller_command = controller_cls.call_args.args[0]
            self.assertNotIn(f'NETWORK_PREFIX={DEFAULT_NETWORK_PREFIX}', controller_command)
            controller_cls.return_value.initialize.assert_called_once()

    def test_command_env_prefix_handles_assignments_options_and_plain_commands(self):
        self.assertEqual(
            deployment.command_env_prefix(['env', '--unset=DOCKER_HOST', 'A=1', 'B=2', 'docker', 'compose', 'up']),
            ['env', '--unset=DOCKER_HOST', 'A=1', 'B=2'],
        )
        self.assertEqual(
            deployment.command_env_prefix(['env', 'A=1', '--', 'docker', 'compose']),
            ['env', 'A=1', '--'],
        )
        self.assertEqual(deployment.command_env_prefix(['env', 'docker', 'compose']), [])
        self.assertEqual(deployment.command_env_prefix(['docker', 'compose', 'up']), [])

    def test_build_and_networked_x402_reject_invalid_project_name_while_offline_allows_it(self):
        for bad_project in ('agent--2', 'agent___2', 'agent-', 'BadName'):
            with self.subTest(project=bad_project):
                with patch.dict(os.environ, {'COMPOSE_PROJECT_NAME': bad_project, 'NETWORK_PREFIX': '10.205'}), \
                        patch.object(sys, 'argv', ['stack.py', 'build']), \
                        patch.object(stack, 'run') as run_mock:
                    with self.assertRaisesRegex(ValueError, 'COMPOSE_PROJECT_NAME'):
                        stack.main_unlocked()
                    run_mock.assert_not_called()

                for action in ('init', 'prepare'):
                    with patch.dict(os.environ, {'COMPOSE_PROJECT_NAME': bad_project, 'NETWORK_PREFIX': '10.205'}), \
                            patch.object(sys, 'argv', ['x402_treazury.py', action]), \
                            patch.object(x402_treazury, '_running_stack_prefix', return_value=None), \
                            patch.object(x402_treazury, 'Controller') as controller_cls:
                        with self.assertRaisesRegex(ValueError, 'COMPOSE_PROJECT_NAME'):
                            x402_treazury.main()
                        controller_cls.assert_not_called()

                # Offline status and down remain available.
                with patch.dict(os.environ, {'COMPOSE_PROJECT_NAME': bad_project, 'NETWORK_PREFIX': 'bad'}), \
                        patch.object(sys, 'argv', ['x402_treazury.py', 'status']), \
                        patch.object(x402_treazury, 'Controller') as controller_cls:
                    x402_treazury.main()
                    controller_cls.return_value.admin.assert_called_once_with('status')

    def test_x402_init_and_prepare_keep_podman_overrides_stripped(self):
        def reset_engine():
            deployment.engine.cache_clear()
            deployment.check_engine.cache_clear()
            deployment._AMBIENT_OVERRIDES.clear()

        self.addCleanup(reset_engine)
        for action in ('init', 'prepare'):
            with self.subTest(action=action):
                reset_engine()
                env = {
                    'CONTAINER_ENGINE': 'podman',
                    'DOCKER_HOST': 'tcp://10.9.9.9:2375',
                    'CONTAINER_CONNECTION': 'other',
                    'COMPOSE_PROJECT_NAME': 'agent-two',
                    'NETWORK_PREFIX': '10.205',
                }
                with patch.dict(os.environ, env), \
                        patch.object(sys, 'argv', ['x402_treazury.py', action]), \
                        patch.object(x402_treazury, '_running_stack_prefix', return_value='10.205'), \
                        patch.object(x402_treazury, 'operation_lock'), \
                        patch.object(x402_treazury, 'Controller') as controller_cls:
                    x402_treazury.main()
                    self.assertNotIn('DOCKER_HOST', os.environ)
                    self.assertNotIn('CONTAINER_CONNECTION', os.environ)
                    self.assertIn('DOCKER_HOST', deployment._AMBIENT_OVERRIDES)
                    self.assertIn('CONTAINER_CONNECTION', deployment._AMBIENT_OVERRIDES)
                    expected_method = 'initialize' if action == 'init' else 'prepare'
                    getattr(controller_cls.return_value, expected_method).assert_called_once()

    def test_browser_policy_backend_ip_handles_unset_empty_and_custom_values(self):
        async def app(_scope, _receive, send):
            await send({'type': 'http.response.start', 'status': 200, 'headers': [(b'content-type', b'application/json')]})
            await send({'type': 'http.response.body', 'body': b'{}'})

        def call(server_ip, prefix_value, headers=()):
            sent = []

            async def send(message):
                sent.append(message)

            scope = {
                'type': 'http',
                'scheme': 'http',
                'path': '/api/config',
                'server': (server_ip, 9120),
                'headers': [(b'host', b'127.0.0.1:9120'), *headers],
            }
            fake_starlette = types.ModuleType('starlette')
            fake_responses = types.SimpleNamespace(PlainTextResponse=_FakePlainTextResponse)
            with patch.dict(os.environ), patch.dict(sys.modules, {
                'starlette': fake_starlette,
                'starlette.responses': fake_responses,
            }):
                if prefix_value is None:
                    os.environ.pop('NETWORK_PREFIX', None)
                else:
                    os.environ['NETWORK_PREFIX'] = prefix_value
                middleware = browser_policy.PrivateContentMiddleware(app)
                asyncio.run(middleware(scope, None, send))
            return sent[0]['status']

        # Unset and empty string both default to 10.203.85.2 and require the ingress mode header.
        self.assertEqual(call('10.203.85.2', None), 503)
        self.assertEqual(call('10.203.85.2', ''), 503)
        self.assertEqual(call('10.203.85.2', '', [(b'x-private-hermes-content-mode', b'tor_proxied')]), 200)
        # Custom NETWORK_PREFIX enforces ingress header on <prefix>.85.2, not the default IP.
        self.assertEqual(call('10.205.85.2', '10.205'), 503)
        self.assertEqual(call('10.205.85.2', '10.205', [(b'x-private-hermes-content-mode', b'tor_proxied')]), 200)
        self.assertEqual(call('10.203.85.2', '10.205'), 200)
        # Invalid NETWORK_PREFIX fails visibly instead of silently falling back.
        with self.assertRaises(ValueError):
            call('10.204.85.2', '10.204')

    def test_configured_env_value_and_local_image_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            dotenv = Path(directory) / '.env'
            with patch.dict(os.environ):
                os.environ.pop('COMPOSE_PROJECT_NAME', None)
                self.assertEqual(deployment.local_image('agent', path=dotenv), 'private-hermes-agent:local')
                dotenv.write_text('COMPOSE_PROJECT_NAME=agent-two\n', encoding='utf-8')
                self.assertEqual(deployment.local_image('agent', path=dotenv), 'agent-two-agent:local')
                self.assertEqual(deployment.local_image('executor-true', path=dotenv), 'agent-two-executor-true:local')
                os.environ['COMPOSE_PROJECT_NAME'] = 'from-env'
                self.assertEqual(deployment.local_image('agent', path=dotenv), 'from-env-agent:local')
                os.environ['COMPOSE_PROJECT_NAME'] = ''
                self.assertEqual(deployment.local_image('agent', path=dotenv), 'private-hermes-agent:local')
                os.environ.pop('COMPOSE_PROJECT_NAME', None)
                dotenv.write_text('COMPOSE_PROJECT_NAME=\n', encoding='utf-8')
                self.assertEqual(deployment.local_image('agent', path=dotenv), 'private-hermes-agent:local')

    def test_start_chat_propagates_running_hermes_network_prefix(self):
        applied_env = [
            'WEBAPP_TERMINAL_ENVIRONMENT=code',
            'WEBAPP_EXTERNAL_CONTENT=tor_proxied',
            'COMPUTER_USE_ENABLED=false',
            'PRIVATE_HERMES_EXECUTOR_ROOTS=["/workspace"]',
            'NETWORK_PREFIX=10.205',
        ]
        with patch.object(deployment, 'compose_base', return_value=['docker', 'compose']), \
                patch.object(deployment, 'compose_files', return_value=['-f', 'compose.yaml']), \
                patch.object(stack, 'check_engine'), \
                patch.object(stack, 'running_service', side_effect=['hermes-cid', 'exec-cid']), \
                patch.object(stack, 'attached_project_mounts', return_value={}), \
                patch.object(stack, 'capture', return_value=json.dumps(applied_env)), \
                patch.object(stack, 'inspect_launch', return_value=(None, False)), \
                patch.object(stack, 'run') as run_mock:
            stack.start_chat(['--resume'])
        executed = run_mock.call_args.args[0]
        self.assertIn('NETWORK_PREFIX=10.205', executed)
        self.assertNotIn('NETWORK_PREFIX=10.203', executed)
        self.assertIn('WEBAPP_PORT=9120', executed)
        self.assertEqual(executed[-3:], ['hermes', 'chat', '--resume'])

    def test_bootstrap_updates_managed_teep_url_and_preserves_custom_url(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_root = root / 'data'
            (data_root / 'ssh/agent').mkdir(parents=True)
            (data_root / 'ssh/executor').mkdir(parents=True)
            home = root / 'home'
            home.mkdir()
            auth_path = root / 'auth.json'
            auth_path.write_text(json.dumps({
                'password_hash': hash_password('test-pass-1234'),
                'secret': 'a' * 64,
            }))
            defaults = root / 'config.example.json'
            defaults.write_text(json.dumps({
                'providers': {'teep': {'name': 'Teep', 'base_url': 'http://10.203.83.3:8337/v1', 'models': {}}},
                'terminal': {'backend': 'ssh', 'ssh_host': '10.203.82.3', 'ssh_port': 2222},
            }))

            def fake_key(path):
                if not path.exists():
                    path.write_bytes(b'fake-private-key')
                path.with_name(path.name + '.pub').write_bytes(b'ssh-ed25519 AAAATESTKEY test@host\n')

            with patch.object(bootstrap, 'key', side_effect=fake_key), \
                    patch.object(bootstrap.os, 'chown'), \
                    patch.object(os, 'fchown'):
                with patch.dict(os.environ, {'NETWORK_PREFIX': '10.205', 'TEEP_ENABLED': 'true', 'TEEP_INSTALL_MODEL': ''}):
                    bootstrap.initialize(data_root, home, defaults, auth_path, 'admin')
                known = (data_root / 'ssh/agent/known_hosts').read_text()
                self.assertTrue(known.startswith('[10.205.82.3]:2222 '))
                config_text = (home / 'config.yaml').read_text()
                self.assertIn('http://10.205.83.3:8337/v1', config_text)
                self.assertIn('10.205.82.3', config_text)
                self.assertIn('10.205.85.3', config_text)

                # Changing NETWORK_PREFIX updates managed Teep URL, ssh_host, and trusted_proxies.
                with patch.dict(os.environ, {'NETWORK_PREFIX': '10.206', 'TEEP_ENABLED': 'true', 'TEEP_INSTALL_MODEL': ''}):
                    bootstrap.initialize(data_root, home, defaults, auth_path, 'admin')
                updated_text = (home / 'config.yaml').read_text()
                self.assertIn('http://10.206.83.3:8337/v1', updated_text)
                self.assertIn('10.206.82.3', updated_text)
                self.assertIn('10.206.85.3', updated_text)
                self.assertTrue((data_root / 'ssh/agent/known_hosts').read_text().startswith('[10.206.82.3]:2222 '))

                # Operator-customized base_url and ssh_host (including non-RFC1918 and GRE 10.204) are preserved.
                custom_text = updated_text.replace('http://10.206.83.3:8337/v1', 'http://203.0.83.3:8337/v1')
                custom_text = custom_text.replace('10.206.82.3', '203.0.82.3')
                (home / 'config.yaml').write_text(custom_text)
                with patch.dict(os.environ, {'NETWORK_PREFIX': '10.207', 'TEEP_ENABLED': 'true', 'TEEP_INSTALL_MODEL': ''}):
                    bootstrap.initialize(data_root, home, defaults, auth_path, 'admin')
                preserved_text = (home / 'config.yaml').read_text()
                self.assertIn('http://203.0.83.3:8337/v1', preserved_text)
                self.assertIn('203.0.82.3', preserved_text)
                self.assertIn('10.207.85.3', preserved_text)
                self.assertFalse(bootstrap._is_managed_address('http://10.204.83.3:8337/v1', bootstrap._MANAGED_TEEP_URL))
                self.assertFalse(bootstrap._is_managed_address('10.204.82.3', bootstrap._MANAGED_SSH_HOST))

    def test_configured_env_value_honors_compose_env_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('NETWORK_PREFIX=bad\nCOMPOSE_PROJECT_NAME=from-root\n', encoding='utf-8')
            first = root / 'first.env'
            second = root / 'second.env'
            first.write_text('NETWORK_PREFIX=10.205\nCOMPOSE_PROJECT_NAME=from-first\nCONTAINER_ENGINE=podman\n', encoding='utf-8')
            second.write_text('NETWORK_PREFIX=10.206\n', encoding='utf-8')
            with patch.object(deployment, 'ROOT', root), patch.dict(os.environ):
                os.environ.pop('NETWORK_PREFIX', None)
                os.environ.pop('COMPOSE_PROJECT_NAME', None)
                os.environ.pop('CONTAINER_ENGINE', None)
                os.environ['COMPOSE_ENV_FILES'] = f'{first},second.env'
                self.assertEqual(deployment.configured_env_value('NETWORK_PREFIX'), '10.206')
                self.assertEqual(deployment.configured_env_value('COMPOSE_PROJECT_NAME'), 'from-first')
                self.assertEqual(deployment.read_selector(), 'podman')
                deployment.maintenance_compose(allow_invalid_network=False, validate_project=True)
                os.environ['COMPOSE_ENV_FILES'] = ''
                self.assertEqual(deployment.configured_env_value('NETWORK_PREFIX'), 'bad')

    def test_proxy_start_enforces_network_prefix_header_and_selects_edge_ip(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = Path(directory) / 'haproxy.cfg'
            cfg.write_text(
                '# WEBAPP_EXTERNAL_CONTENT=tor_proxied\n'
                '# PORT_FORWARDER=interface\n'
                '# TOR_ONION_ENABLED=false\n'
                '# NETWORK_PREFIX=10.203\n'
                'global\n',
                encoding='utf-8',
            )
            env = {
                'WEBAPP_EXTERNAL_CONTENT': 'tor_proxied',
                'TOR_ONION_ENABLED': 'false',
                'TAILSCALE_FUNNEL_ENABLED': 'false',
                'WEBAPP_PORT': '9121',
                'NETWORK_PREFIX': '10.205',
            }
            with patch.dict(os.environ, env, clear=False), \
                    patch.object(proxy_start, 'run'), \
                    patch.object(proxy_start, 'Path', return_value=cfg):
                with self.assertRaisesRegex(ValueError, 'Network prefix mismatch'):
                    proxy_start.main()

            cfg.write_text(
                '# WEBAPP_EXTERNAL_CONTENT=tor_proxied\n'
                '# PORT_FORWARDER=interface\n'
                '# TOR_ONION_ENABLED=false\n'
                '# NETWORK_PREFIX=10.205\n'
                'global\n',
                encoding='utf-8',
            )
            ip_json = json.dumps([
                {'ifname': 'lo', 'addr_info': [{'scope': 'host', 'local': '127.0.0.1'}]},
                {'ifname': 'eth0', 'addr_info': [{'scope': 'global', 'local': '10.205.85.3'}]},
                {'ifname': 'eth1', 'addr_info': [{'scope': 'global', 'local': '10.205.86.3'}]},
                {'ifname': 'eth2', 'addr_info': [{'scope': 'global', 'local': '10.205.90.4'}]},
            ])

            def fake_run(*args, **_kwargs):
                if args[:4] == ('ip', '-j', '-4', 'addr'):
                    return subprocess.CompletedProcess(args, 0, stdout=ip_json, stderr='')
                return subprocess.CompletedProcess(args, 0, stdout='', stderr='')

            with patch.dict(os.environ, env, clear=False), \
                    patch.object(proxy_start, 'run', side_effect=fake_run), \
                    patch.object(proxy_start, 'Path', return_value=cfg), \
                    patch.object(proxy_start, 'firewall', return_value='') as firewall_mock, \
                    patch.object(proxy_start.os, 'execvp') as execvp_mock:
                proxy_start.main()
                self.assertEqual(os.environ['PRIVATE_HERMES_EDGE_IP'], '10.205.90.4')
            firewall_mock.assert_called_once_with('interface', 'eth2', '10.205.90.4', 9121, False, False, '10.205')
            execvp_mock.assert_called_once()

            # Funnel and onion enabled: all three internal IPs (.85.3, .86.3, .87.3) are excluded from edge selection.
            cfg.write_text(
                '# WEBAPP_EXTERNAL_CONTENT=tor_proxied\n'
                '# PORT_FORWARDER=interface\n'
                '# TOR_ONION_ENABLED=true\n'
                '# NETWORK_PREFIX=10.205\n'
                'global\n',
                encoding='utf-8',
            )
            funnel_ip_json = json.dumps([
                {'ifname': 'lo', 'addr_info': [{'scope': 'host', 'local': '127.0.0.1'}]},
                {'ifname': 'eth0', 'addr_info': [{'scope': 'global', 'local': '10.205.85.3'}]},
                {'ifname': 'eth1', 'addr_info': [{'scope': 'global', 'local': '10.205.86.3'}]},
                {'ifname': 'eth2', 'addr_info': [{'scope': 'global', 'local': '10.205.87.3'}]},
                {'ifname': 'eth3', 'addr_info': [{'scope': 'global', 'local': '10.205.90.4'}]},
            ])

            def fake_run_funnel(*args, **_kwargs):
                if args[:4] == ('ip', '-j', '-4', 'addr'):
                    return subprocess.CompletedProcess(args, 0, stdout=funnel_ip_json, stderr='')
                return subprocess.CompletedProcess(args, 0, stdout='', stderr='')

            funnel_env = {**env, 'TOR_ONION_ENABLED': 'true', 'TAILSCALE_FUNNEL_ENABLED': 'true'}
            with patch.dict(os.environ, funnel_env, clear=False), \
                    patch.object(proxy_start, 'run', side_effect=fake_run_funnel), \
                    patch.object(proxy_start, 'Path', return_value=cfg), \
                    patch.object(proxy_start, 'firewall', return_value='') as funnel_fw_mock, \
                    patch.object(proxy_start.os, 'execvp') as funnel_execvp_mock:
                proxy_start.main()
                self.assertEqual(os.environ['PRIVATE_HERMES_EDGE_IP'], '10.205.90.4')
            funnel_fw_mock.assert_called_once_with('interface', 'eth3', '10.205.90.4', 9121, True, True, '10.205')
            funnel_execvp_mock.assert_called_once()

    def test_preflight_address_plan_changed_mentions_compose_project_name(self):
        config = {
            'networks': {
                'agent-route': {'ipam': {'config': [{'subnet': '10.205.80.0/24'}]}},
            }
        }
        existing = [{
            'Name': 'private-hermes_agent-route',
            'Labels': {'com.docker.compose.project': 'private-hermes', 'com.docker.compose.network': 'agent-route'},
            'IPAM': {'Config': [{'Subnet': '10.203.80.0/24'}]},
        }]
        with self.assertRaises(SystemExit) as ctx:
            preflight.check_address_conflicts('private-hermes', config, existing)
        message = str(ctx.exception)
        self.assertIn('Address plan changed', message)
        self.assertIn('COMPOSE_PROJECT_NAME', message)

    def test_in_place_upgrade_from_pre_multi_instance_files_regenerates_proxy_and_resolvers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proxy_path = root / 'config/webapp/proxy.cfg'
            proxy_path.parent.mkdir(parents=True)
            # Pre-multi-instance proxy.cfg lacked the line-4 # NETWORK_PREFIX= header.
            proxy_path.write_text(
                '# WEBAPP_EXTERNAL_CONTENT=tor_proxied\n'
                '# PORT_FORWARDER=interface\n'
                '# TOR_ONION_ENABLED=false\n'
                'global\n',
                encoding='utf-8',
            )
            config = Settings(
                onion=False, funnel=False, bind='127.0.0.1', port=9120, username='admin',
                funnel_host='', funnel_port=443, node='private-hermes',
                external_content='tor_proxied', teep=True,
                project_name='private-hermes', network_prefix='10.203',
            )
            with patch.object(deployment, 'ROOT', root), patch.object(deployment, 'engine', return_value='docker'):
                deployment.render(config)
            lines = proxy_path.read_text().splitlines()
            self.assertEqual(lines[3], '# NETWORK_PREFIX=10.203')
            self.assertEqual((root / 'config/network/hermes-resolv.conf').read_text(),
                             'nameserver 10.203.80.3\noptions timeout:5 attempts:2\n')
            self.assertEqual((root / 'config/network/executor-resolv.conf').read_text(),
                             'nameserver 10.203.81.3\noptions timeout:5 attempts:2\n')

    def test_proxy_start_rejects_pre_upgrade_proxy_cfg_without_network_prefix_header(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = Path(directory) / 'haproxy.cfg'
            cfg.write_text(
                '# WEBAPP_EXTERNAL_CONTENT=tor_proxied\n'
                '# PORT_FORWARDER=interface\n'
                '# TOR_ONION_ENABLED=false\n'
                'global\n',
                encoding='utf-8',
            )
            env = {
                'WEBAPP_EXTERNAL_CONTENT': 'tor_proxied',
                'TOR_ONION_ENABLED': 'false',
                'TAILSCALE_FUNNEL_ENABLED': 'false',
                'WEBAPP_PORT': '9120',
                'NETWORK_PREFIX': '10.203',
            }
            with patch.dict(os.environ, env, clear=False), \
                    patch.object(proxy_start, 'run'), \
                    patch.object(proxy_start, 'Path', return_value=cfg):
                with self.assertRaisesRegex(ValueError, 'Network prefix mismatch'):
                    proxy_start.main()

    def test_configured_env_value_rejects_malformed_dotenv_syntax(self):
        with tempfile.TemporaryDirectory() as directory:
            dotenv = Path(directory) / '.env'
            dotenv.write_text('COMPOSE_PROJECT_NAME="unclosed\n', encoding='utf-8')
            with patch.dict(os.environ):
                os.environ.pop('COMPOSE_PROJECT_NAME', None)
                with self.assertRaisesRegex(ValueError, 'not a valid assignment'):
                    deployment.configured_env_value('COMPOSE_PROJECT_NAME', DEFAULT_PROJECT_NAME, path=dotenv)

    def test_x402_running_stack_prefix_falls_back_to_stopped_containers(self):
        def fake_run_stopped(args, **_kwargs):
            if 'ps' in args and '-a' not in args:
                return subprocess.CompletedProcess(args, 0, stdout='', stderr='')
            if 'ps' in args and '-a' in args:
                return subprocess.CompletedProcess(args, 0, stdout='cid-tor-stopped\n', stderr='')
            if 'inspect' in args:
                return subprocess.CompletedProcess(
                    args, 0, stdout='tor ' + json.dumps(['NETWORK_PREFIX=10.205']) + '\n', stderr='',
                )
            return subprocess.CompletedProcess(args, 0, stdout='', stderr='')

        with patch.object(x402_treazury, 'maintenance_compose', return_value=['docker', 'compose']), \
                patch.object(x402_treazury, 'engine_command', return_value=['docker']), \
                patch.object(x402_treazury.subprocess, 'run', side_effect=fake_run_stopped):
            self.assertEqual(x402_treazury._running_stack_prefix(), '10.205')

    def test_x402_initialize_runs_preflight_before_starting_tor_and_agent_net(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(deployment, 'compose_base', return_value=['docker', 'compose']), \
                    patch.object(deployment, 'compose_files', return_value=['-f', 'compose.yaml']):
                command = deployment.maintenance_compose(
                    allow_invalid_network=False, validate_project=False, env={'NETWORK_PREFIX': '10.205'},
                )
            controller = x402_treazury.Controller(command, root=root)
            calls = []

            def fake_run(args, **kwargs):
                calls.append((args, kwargs.get('env')))
                if any('preflight.py' in str(token) for token in args):
                    raise subprocess.CalledProcessError(1, args)
                return subprocess.CompletedProcess(args, 0, stdout='', stderr='')

            with patch.dict(os.environ, {'TEEP_HOST_PORT': 'invalid', 'WEBAPP_PORT': 'invalid',
                                         'COMPUTER_USE_ENABLED': 'invalid'}), \
                    patch.object(controller, 'inspect', return_value={'wallet_absent': True, 'wallet_valid': False}), \
                    patch.object(x402_treazury, 'initialize_research_config'), \
                    patch.object(controller, 'call') as call_mock, \
                    patch.object(controller, 'wallet_command') as wallet_mock, \
                    patch.object(x402_treazury.subprocess, 'run', side_effect=fake_run):
                with self.assertRaises(SystemExit) as ctx:
                    controller.initialize()
            self.assertEqual(ctx.exception.code, 1)
            call_mock.assert_not_called()
            wallet_mock.assert_not_called()
            preflight_args, preflight_env = calls[-1]
            self.assertIsNone(preflight_env)
            self.assertEqual(preflight_args[0], 'env')
            self.assertIn('NETWORK_PREFIX=10.205', preflight_args)
            self.assertIn('WEBAPP_PORT=9120', preflight_args)
            self.assertIn('COMPUTER_USE_ENABLED=false', preflight_args)
            self.assertIn('PRIVATE_HERMES_TEEP_PORT_OVERRIDE=8337', preflight_args)
            self.assertEqual(preflight_args[-4:], ['--skip-ports', '--services', 'tor', 'agent-net'])

    def test_compose_passthrough_build_validates_project_name(self):
        with patch.dict(os.environ, {'COMPOSE_PROJECT_NAME': 'Bad_Name_'}), \
                patch.object(sys, 'argv', ['stack.py', 'compose', 'build', 'hermes']), \
                patch.object(stack, 'run') as run_mock:
            with self.assertRaisesRegex(ValueError, 'COMPOSE_PROJECT_NAME'):
                stack.main_unlocked()
            run_mock.assert_not_called()

        with patch.dict(os.environ, {'COMPOSE_PROJECT_NAME': 'agent-two'}), \
                patch.object(sys, 'argv', ['stack.py', 'compose', '-p', 'Bad_Name_', 'build', 'hermes']), \
                patch.object(stack, 'run') as run_mock:
            with self.assertRaisesRegex(ValueError, 'COMPOSE_PROJECT_NAME'):
                stack.main_unlocked()
            run_mock.assert_not_called()

        with patch.dict(os.environ, {'COMPOSE_PROJECT_NAME': 'agent-two'}):
            with self.assertRaisesRegex(ValueError, 'COMPOSE_PROJECT_NAME'):
                deployment.maintenance_compose(validate_project=True, env={'COMPOSE_PROJECT_NAME': ''})

        with tempfile.TemporaryDirectory() as directory:
            custom_env = Path(directory) / 'custom.env'
            custom_env.write_text('COMPOSE_PROJECT_NAME=Bad_Name_\n', encoding='utf-8')
            with patch.dict(os.environ), \
                    patch.object(sys, 'argv', ['stack.py', 'compose', '--env-file', str(custom_env), 'build', 'hermes']), \
                    patch.object(stack, 'run') as run_mock:
                os.environ.pop('COMPOSE_PROJECT_NAME', None)
                with self.assertRaisesRegex(ValueError, 'COMPOSE_PROJECT_NAME'):
                    stack.main_unlocked()
                run_mock.assert_not_called()

        with tempfile.TemporaryDirectory() as directory:
            custom_dir = Path(directory)
            (custom_dir / '.env').write_text('COMPOSE_PROJECT_NAME=Bad_Name_\n', encoding='utf-8')
            with patch.dict(os.environ), \
                    patch.object(sys, 'argv', ['stack.py', 'compose', '--project-directory', str(custom_dir), 'build', 'hermes']), \
                    patch.object(stack, 'run') as run_mock:
                os.environ.pop('COMPOSE_PROJECT_NAME', None)
                with self.assertRaisesRegex(ValueError, 'COMPOSE_PROJECT_NAME'):
                    stack.main_unlocked()
                run_mock.assert_not_called()

        with patch.dict(os.environ, {'COMPOSE_PROJECT_NAME': 'Bad_Name_'}), \
                patch.object(sys, 'argv', ['stack.py', 'compose', '-p', 'agent-two', 'build', 'hermes']), \
                patch.object(stack, 'inspect_launch'), \
                patch.object(stack, 'run') as run_mock:
            stack.main_unlocked()
            run_mock.assert_called_once()
            executed = run_mock.call_args.args[0]
            self.assertIn('COMPOSE_PROJECT_NAME=agent-two', executed)

        with patch.dict(os.environ, {'COMPOSE_PROJECT_NAME': 'instance-a'}), \
                patch.object(sys, 'argv', ['stack.py', 'compose', '-p', 'agent-two', 'config']), \
                patch.object(stack, 'run') as run_mock:
            stack.main_unlocked()
            self.assertIn('COMPOSE_PROJECT_NAME=agent-two', run_mock.call_args.args[0])

        fake_cfg = Settings.read(webapp_values(project_name='agent-two', network_prefix='10.205'))
        with patch.dict(os.environ, {'COMPOSE_PROJECT_NAME': 'instance-a'}), \
                patch.object(sys, 'argv', ['stack.py', 'compose', '-p', 'agent-two', 'up', '-d']), \
                patch.object(stack, 'settings', return_value=(fake_cfg, ['env', 'COMPOSE_PROJECT_NAME=agent-two'])) as settings_mock, \
                patch.object(stack, 'inspect_launch', return_value=(None, False)), \
                patch.object(stack, 'run') as run_mock:
            stack.main_unlocked()
            self.assertEqual(settings_mock.call_args.kwargs['env'], {'COMPOSE_PROJECT_NAME': 'agent-two'})
            self.assertIn('COMPOSE_PROJECT_NAME=agent-two', run_mock.call_args.args[0])

    def test_preflight_rejects_unnormalized_declared_project_name(self):
        rendered = json.dumps({
            'name': 'private-hermes',
            'x-deployment': {'project_name': 'Private-Hermes', 'network_prefix': '10.203'},
            'services': {},
            'networks': {},
        })
        for argv in (['preflight.py', '--skip-ports'], ['preflight.py', 'private-hermes-test', '--skip-ports']):
            with self.subTest(argv=argv), \
                    patch.object(sys, 'argv', argv), \
                    patch.object(preflight, 'check_engine'), \
                    patch.object(preflight, 'compose_base', return_value=['docker', 'compose']), \
                    patch.object(preflight, 'compose_files', return_value=['-f', 'compose.yaml']), \
                    patch.object(preflight, 'output', return_value=rendered):
                with self.assertRaises(SystemExit) as ctx:
                    preflight.main()
                self.assertIn('COMPOSE_PROJECT_NAME', str(ctx.exception))

    def test_preflight_reports_compose_render_errors_without_traceback(self):
        error = subprocess.CalledProcessError(1, ['docker', 'compose', 'config'], stderr='invalid project name')
        with patch.object(sys, 'argv', ['preflight.py', '--skip-ports']), \
                patch.object(preflight, 'check_engine'), \
                patch.object(preflight, 'compose_base', return_value=['docker', 'compose']), \
                patch.object(preflight, 'compose_files', return_value=['-f', 'compose.yaml']), \
                patch.object(preflight, 'output', side_effect=error):
            with self.assertRaises(SystemExit) as ctx:
                preflight.main()
            self.assertIn('invalid project name', str(ctx.exception))

    def test_desktop_startup_script_uses_executor_ssh_host_override(self):
        script = (ROOT / 'components/executor/start-desktop.sh').read_text(encoding='utf-8')
        check = subprocess.run(['sh', '-n', str(ROOT / 'components/executor/start-desktop.sh')],
                               capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertIn('-o "ListenAddress=${PRIVATE_HERMES_EXECUTOR_SSH_HOST:-10.203.82.3}"', script)


class NetworkModulePrefixTests(unittest.TestCase):
    def test_mcp_grants_validates_against_instance_prefix(self):
        addrs = Addresses('10.205')
        with patch.object(Path, 'read_text', return_value=json.dumps([{'ip': '10.205.84.10', 'port': 8000}])):
            rules = network_mod.mcp_grants(addrs)
        self.assertEqual(rules, ['-A OUTPUT -d 10.205.84.10/32 -p tcp --dport 8000 -j ACCEPT'])
        with patch.object(Path, 'read_text', return_value=json.dumps([{'ip': '10.203.84.10', 'port': 8000}])):
            with self.assertRaisesRegex(ValueError, 'mcp-access'):
                network_mod.mcp_grants(addrs)

    def test_host_backend_and_local_forwarding_use_instance_uplink_address(self):
        addrs = Addresses('10.205')
        with patch.dict(os.environ, {'PRIVATE_HERMES_ENGINE_HOST_ADDRESS': '10.205.88.1'}), \
                patch.object(network_mod, 'uplink_route', return_value=True) as route_mock:
            self.assertIsNone(network_mod.host_backend(False, 'eth0', addrs))
            route_mock.assert_not_called()

        with patch.dict(os.environ, {'PRIVATE_HERMES_ENGINE_HOST_ADDRESS': '192.168.65.254'}), \
                patch.object(network_mod, 'uplink_route', return_value=True) as route_mock:
            self.assertEqual(network_mod.host_backend(False, 'eth0', addrs), '192.168.65.254')
            route_mock.assert_called_once_with('192.168.65.254', 'eth0', '10.205.88.2')

        _raw, nat, _fwd = network_mod.local_forwarding(
            '10.204.80.2', 'eth0', [('198.18.255.254', '192.168.65.254', 11434)], addrs.tor_uplink
        )
        self.assertTrue(any('--to-source 10.205.88.2' in rule for rule in nat), nat)

    def test_endpoint_agent_and_executor_use_custom_network_prefix(self):
        for role, expected_tunnel, expected_rule in (
            ('agent', ('tor-route', '10.205.80.2', '10.205.80.3', '10.204.80.2/30'),
             '-A OUTPUT -d 10.205.83.3/32 -p tcp --dport 8337 -j ACCEPT'),
            ('executor', ('tor-route', '10.205.81.2', '10.205.81.3', '10.204.81.2/30'),
             '-A INPUT -s 10.205.82.2/32 -d 10.205.82.3/32 -p tcp --dport 2222 -j ACCEPT'),
        ):
            with self.subTest(role=role):
                applied = {}

                def capture_apply(raw, nat, incoming, outgoing, early_output=(), forwarding=()):
                    applied['incoming'] = incoming
                    applied['outgoing'] = outgoing

                with patch.dict(os.environ, {'NETWORK_PREFIX': '10.205'}), \
                        patch.object(network_mod, 'tunnel') as tunnel_mock, \
                        patch.object(network_mod, 'connected', return_value=[]), \
                        patch.object(network_mod, 'mcp_grants', return_value=[]), \
                        patch.object(network_mod, 'apply', side_effect=capture_apply), \
                        patch.object(network_mod, 'run'), \
                        patch.object(Path, 'touch'), \
                        patch.object(network_mod, 'drop'):
                    network_mod.endpoint(role)
                tunnel_mock.assert_called_once_with(*expected_tunnel)
                all_rules = applied['incoming'] + applied['outgoing']
                self.assertIn(expected_rule, all_rules)
                self.assertFalse(any('10.203.' in rule for rule in all_rules), all_rules)

    def test_router_renders_custom_prefix_torrc_and_onion_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ip_forward = root / 'ip_forward'
            ip_forward.write_text('0\n')
            warnings_file = root / 'warnings'
            written_torrc = {}
            applied = {}

            def capture_apply(raw, nat, incoming, outgoing, early_output=(), forwarding=()):
                applied['outgoing'] = outgoing

            orig_read_text = Path.read_text
            orig_write_text = Path.write_text

            def fake_read_text(path, *args, **kwargs):
                if str(path) == '/etc/tor/torrc':
                    return 'SocksPort 0\nTransPort 10.204.80.1:9040\n'
                return orig_read_text(path, *args, **kwargs)

            def fake_write_text(path, data, *args, **kwargs):
                if str(path) == '/tmp/private-hermes-torrc':
                    written_torrc['text'] = data
                    return len(data)
                return orig_write_text(path, data, *args, **kwargs)

            with patch.dict(os.environ, {'NETWORK_PREFIX': '10.205', 'TOR_ONION_ENABLED': 'true'}), \
                    patch.object(network_mod, 'IP_FORWARD', ip_forward), \
                    patch.object(network_mod, 'LOCAL_GRANT_WARNINGS', warnings_file), \
                    patch.object(network_mod, 'require_secret'), \
                    patch.object(network_mod, 'read_address', return_value='a' * 56 + '.onion'), \
                    patch.object(network_mod, 'tunnel'), \
                    patch.object(network_mod, 'connected', return_value=[]), \
                    patch.object(network_mod, 'apply', side_effect=capture_apply), \
                    patch.object(network_mod.os, 'walk', return_value=[]), \
                    patch.object(network_mod.os, 'chown'), \
                    patch.object(Path, 'mkdir'), \
                    patch.object(Path, 'chmod'), \
                    patch.object(Path, 'read_text', fake_read_text), \
                    patch.object(Path, 'write_text', fake_write_text), \
                    patch.object(network_mod, 'drop'):
                network_mod.router()
            self.assertIn(
                '-A OUTPUT -s 10.205.86.2/32 -d 10.205.86.3/32 -p tcp --dport 8080 -m owner --uid-owner 101 -j ACCEPT',
                applied['outgoing'],
            )
            torrc = written_torrc['text']
            self.assertIn('DNSPort 10.205.80.3:9053\n', torrc)
            self.assertIn('DNSPort 10.205.81.3:9053\n', torrc)
            self.assertIn('HiddenServicePort 80 10.205.86.3:8080\n', torrc)
            self.assertNotIn('10.203.', torrc)


if __name__ == '__main__':
    unittest.main()
