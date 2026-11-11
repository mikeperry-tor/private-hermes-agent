"""Engine selection, the Podman overlays and checks that depend on the engine."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import deployment
import preflight
import stack

spec = importlib.util.spec_from_file_location('proxy_start', ROOT / 'components/webapp/proxy-start.py')
proxy_start = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy_start)


def model(*files):
    arguments = [argument for name in files for argument in ('-f', name)]
    result = subprocess.run(['docker', 'compose', *arguments, '--profile', '*', '--env-file', '/dev/null',
                             'config', '--format', 'json'], cwd=ROOT, text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def detect(answers):
    def output(*args):
        answer = answers[args[1]]
        if isinstance(answer, Exception):
            raise answer
        return answer
    deployment.engine.cache_clear()
    try:
        with patch.object(deployment, '_output', side_effect=output):
            return deployment.engine()
    finally:
        deployment.engine.cache_clear()


class EngineSelectionTests(unittest.TestCase):
    def test_only_a_positive_podman_identification_selects_podman(self):
        docker_client = 'Docker version 28.4.0, build 1234567\n'
        cases = (
            ({'--version': 'podman version 5.4.2\n'}, 'podman'),
            ({'--version': docker_client, 'version': json.dumps([{'Name': 'Podman Engine'}])}, 'podman'),
            ({'--version': docker_client, 'version': json.dumps([{'Name': 'Engine'}, {'Name': 'containerd'}])}, 'docker'),
            ({'--version': docker_client, 'version': 'null'}, 'docker'),
            ({'--version': docker_client, 'version': 'not json'}, 'docker'),
            ({'--version': docker_client, 'version': subprocess.CalledProcessError(1, 'docker')}, 'docker'),
            ({'--version': OSError('no docker command')}, 'docker'),
        )
        for answers, expected in cases:
            with self.subTest(answers=answers), patch.dict(os.environ, clear=False) as environment:
                environment.pop('DOCKER_HOST', None)
                self.assertEqual(detect(answers), expected)

    def test_podman_client_identifies_the_docker_host_endpoint(self):
        # podman compose passes DOCKER_HOST to Compose, so a Podman client alone is not enough.
        answers = {'--version': 'podman version 5.4.2\n'}
        for components, expected in ((['Podman Engine', 'Conmon'], 'podman'), (['Engine', 'containerd'], 'docker'),
                                     (ValueError('tcp:// endpoint'), 'docker'), (OSError('no socket'), 'docker')):
            with self.subTest(components=components), \
                    patch.dict(os.environ, DOCKER_HOST='unix:///run/user/1/docker.sock'), \
                    patch.object(deployment, '_endpoint_components',
                                 side_effect=components if isinstance(components, Exception) else None,
                                 return_value=None if isinstance(components, Exception) else components):
                self.assertEqual(detect(answers), expected)

    def test_podman_files_are_last_and_funnel_file_only_with_funnel(self):
        with patch.object(deployment, 'engine', return_value='docker'):
            self.assertEqual(deployment.compose_files(True), ['-f', 'compose.yaml', '-f', 'compose.funnel.yaml'])
        with patch.object(deployment, 'engine', return_value='podman'):
            self.assertEqual(deployment.compose_files(False), ['-f', 'compose.yaml', '-f', 'compose.podman.yaml'])
            self.assertEqual(deployment.compose_files(True, extra=('tests/compose.yaml',)),
                             ['-f', 'compose.yaml', '-f', 'compose.funnel.yaml', '-f', 'tests/compose.yaml',
                              '-f', 'compose.podman.yaml', '-f', 'compose.podman.funnel.yaml'])
            # maintenance_compose sets placeholder settings in os.environ.
            with patch.dict(os.environ):
                self.assertIn('compose.podman.yaml', deployment.maintenance_compose(all_ingress=True))


class ComposeModelTests(unittest.TestCase):
    def test_docker_model_keeps_isolated_gateway_mode(self):
        config = model('compose.yaml', 'compose.funnel.yaml')
        internal = {name for name, network in config['networks'].items() if network.get('internal')}
        self.assertEqual(internal, {'agent-route', 'executor-route', 'execution-control', 'inference',
                                    'mcp-access', 'webapp-backend', 'funnel-link'})
        for name, network in config['networks'].items():
            if name in internal:
                with self.subTest(network=name):
                    options = network.get('driver_opts') or {}
                    self.assertEqual(options.get('com.docker.network.bridge.gateway_mode_ipv4'), 'isolated')
                    self.assertEqual(options.get('com.docker.network.bridge.gateway_mode_ipv6'), 'isolated')
        self.assertEqual(config['networks']['webapp-publish']['driver_opts'],
                         {'com.docker.network.bridge.enable_ip_masquerade': 'false'})

    def test_podman_model_isolates_every_network_without_docker_options(self):
        for files in (('compose.yaml', 'compose.podman.yaml'),
                      ('compose.yaml', 'compose.funnel.yaml', 'compose.podman.yaml', 'compose.podman.funnel.yaml')):
            with self.subTest(files=files):
                config = model(*files)
                for name, network in config['networks'].items():
                    options = network.get('driver_opts') or {}
                    self.assertEqual(options.get('isolate'), 'strict', name)
                    self.assertFalse([key for key in options if key.startswith('com.docker.')], name)
                self.assertEqual(config['networks']['webapp-publish']['driver_opts']['no_default_route'], 'true')
                for name, service in config['services'].items():
                    self.assertNotIn('start_interval', service.get('healthcheck') or {}, name)
                    for network in (service.get('networks') or {}).values():
                        self.assertNotIn('gw_priority', network or {}, name)
                self.assertEqual(config['services']['webapp-proxy']['environment']['PRIVATE_HERMES_PORT_FORWARDER'],
                                 'loopback')
                # The internal networks keep their address plan and stay internal.
                self.assertTrue(config['networks']['inference']['internal'])
                self.assertEqual(config['networks']['inference']['ipam']['config'], [{'subnet': '10.203.83.0/24'}])


class NetworkCreationTests(unittest.TestCase):
    CONFIG = {'name': 'private-hermes', 'networks': {
        'inference': {'name': 'private-hermes_inference', 'internal': True,
                      'driver_opts': {'isolate': 'strict'}, 'ipam': {'config': [{'subnet': '10.203.83.0/24'}]}},
        'webapp-publish': {'name': 'private-hermes_webapp-publish',
                           'driver_opts': {'isolate': 'strict', 'no_default_route': 'true'}},
        'outside': {'name': 'shared', 'external': True}}}

    def run_ensure(self, inspected):
        calls = []
        def run(arguments, **kwargs):
            calls.append(arguments)
            if arguments[:3] == ['podman', 'network', 'inspect']:
                found = inspected.get(arguments[3])
                return subprocess.CompletedProcess(arguments, 0 if found else 125, json.dumps([found]) if found else '', '')
            return subprocess.CompletedProcess(arguments, 0, '', '')
        with patch.object(deployment, 'engine', return_value='podman'), \
                patch.object(deployment, '_output', return_value=json.dumps(self.CONFIG)), \
                patch.object(deployment.subprocess, 'run', side_effect=run):
            deployment.ensure_networks(['docker', 'compose', '-p', 'private-hermes'])
        return [call for call in calls if call[:3] == ['podman', 'network', 'create']]

    def test_missing_networks_are_created_with_declared_options_and_compose_labels(self):
        created = self.run_ensure({})
        self.assertEqual(created, [
            ['podman', 'network', 'create', '--label', 'com.docker.compose.project=private-hermes',
             '--label', 'com.docker.compose.network=inference', '--internal', '--subnet', '10.203.83.0/24',
             '--opt', 'isolate=strict', 'private-hermes_inference'],
            ['podman', 'network', 'create', '--label', 'com.docker.compose.project=private-hermes',
             '--label', 'com.docker.compose.network=webapp-publish',
             '--opt', 'isolate=strict', '--opt', 'no_default_route=true', 'private-hermes_webapp-publish']])

    def test_matching_networks_are_kept_and_weaker_ones_stop_startup(self):
        good = {'private-hermes_inference': {'options': {'isolate': 'strict'}, 'internal': True,
                                             'subnets': [{'subnet': '10.203.83.0/24'}]},
                'private-hermes_webapp-publish': {'options': {'isolate': 'strict', 'no_default_route': 'true'},
                                                  'internal': False, 'subnets': [{'subnet': '10.89.2.0/24'}]}}
        self.assertEqual(self.run_ensure(good), [])
        # Compose through the Docker-compatible API creates isolate=true only.
        for name, change in (('private-hermes_inference', {'options': {'isolate': 'true'}}),
                             ('private-hermes_inference', {'internal': False}),
                             ('private-hermes_inference', {'subnets': [{'subnet': '10.203.99.0/24'}]}),
                             ('private-hermes_webapp-publish', {'options': {'isolate': 'strict'}})):
            with self.subTest(name=name, change=change), self.assertRaisesRegex(RuntimeError, 'make down'):
                self.run_ensure({**good, name: {**good[name], **change}})

    def test_down_removes_only_this_projects_leftover_networks(self):
        inspected = {'private-hermes_inference': {'labels': {'com.docker.compose.project': 'private-hermes'}},
                     'private-hermes_webapp-publish': {'labels': {'com.docker.compose.project': 'other'}}}
        calls = []
        def run(arguments, **kwargs):
            calls.append(arguments)
            if arguments[:3] == ['podman', 'network', 'inspect']:
                found = inspected.get(arguments[3])
                return subprocess.CompletedProcess(arguments, 0 if found else 125, json.dumps([found]) if found else '', '')
            return subprocess.CompletedProcess(arguments, 0, '', '')
        with patch.object(deployment, 'engine', return_value='podman'), \
                patch.object(deployment, '_output', return_value=json.dumps(self.CONFIG)), \
                patch.object(deployment.subprocess, 'run', side_effect=run):
            deployment.remove_networks(['docker', 'compose'])
        self.assertEqual([call for call in calls if call[:3] == ['podman', 'network', 'rm']],
                         [['podman', 'network', 'rm', 'private-hermes_inference']])

    def test_compose_passthrough_creates_networks_before_starting_services(self):
        for command, creates in ((['up', '-d'], True), (['run', '--rm', 'teep', 'serve', '--help'], True),
                                 (['ps'], False)):
            with self.subTest(command=command), patch.object(sys, 'argv', ['stack.py', 'compose', *command]), \
                    patch.object(stack, 'settings', return_value=deployment.Settings.read(dict(
                        external_content='tor_proxied', funnel_enabled='false', webapp_bind='127.0.0.1',
                        webapp_port='9120', webapp_username='admin', funnel_host='', funnel_port='443',
                        tailscale_hostname='private-hermes'))), \
                    patch.object(stack, 'ensure_networks') as ensure, patch.object(stack, 'run'):
                stack.main_unlocked()
                self.assertEqual(ensure.called, creates)

    def test_docker_engine_creates_no_network(self):
        with patch.object(deployment, 'engine', return_value='docker'), \
                patch.object(deployment, '_output', side_effect=AssertionError('no Compose call')):
            deployment.ensure_networks(['docker', 'compose'])


class ProxyFirewallTests(unittest.TestCase):
    def test_interface_mode_accepts_only_the_publication_interface(self):
        rules = proxy_start.firewall('interface', 'eth1', '10.89.2.2', 9120, False).splitlines()
        self.assertIn('-A INPUT -i eth1 -d 10.89.2.2/32 -p tcp --dport 9120 -m conntrack --ctstate NEW -j ACCEPT', rules)
        self.assertFalse([rule for rule in rules if ' lo ' in rule])

    def test_loopback_mode_accepts_only_loopback_and_no_edge_interface(self):
        rules = proxy_start.firewall('loopback', 'eth1', '10.89.2.2', 9120, False).splitlines()
        self.assertIn('-A INPUT -i lo -p tcp --dport 9120 -m conntrack --ctstate NEW -j ACCEPT', rules)
        self.assertIn('-A OUTPUT -o lo -p tcp --dport 9120 -m conntrack --ctstate NEW -j ACCEPT', rules)
        self.assertFalse([rule for rule in rules if 'eth1' in rule or '10.89.2.2' in rule])
        new_inputs = [rule for rule in rules if rule.startswith('-A INPUT') and 'NEW' in rule]
        self.assertEqual(new_inputs, ['-A INPUT -i lo -p tcp --dport 9120 -m conntrack --ctstate NEW -j ACCEPT'])

    def test_both_modes_keep_policy_backend_and_funnel_rules(self):
        for mode in ('interface', 'loopback'):
            with self.subTest(mode=mode):
                rules = proxy_start.firewall(mode, 'eth1', '10.89.2.2', 9120, True).splitlines()
                self.assertEqual(rules[:4], ['*filter', ':INPUT DROP [0:0]', ':OUTPUT DROP [0:0]', ':FORWARD DROP [0:0]'])
                self.assertIn('-A INPUT -s 10.203.87.2/32 -d 10.203.87.3/32 -p tcp --dport 8443 '
                              '-m conntrack --ctstate NEW -j ACCEPT', rules)
                self.assertIn('-A OUTPUT -d 10.203.85.2/32 -p tcp --dport 9120 -m conntrack --ctstate NEW -j ACCEPT', rules)


class PreflightFloorTests(unittest.TestCase):
    def check(self, kind, answers, environment=None):
        def output(*args):
            key = ' '.join(args)
            for prefix, answer in answers.items():
                if key.startswith(prefix):
                    if isinstance(answer, Exception):
                        raise answer
                    return answer
            raise AssertionError(key)
        with patch.object(preflight, 'engine', return_value=kind), patch.object(preflight, 'output', side_effect=output), \
                patch.dict(os.environ, environment or {}, clear=False):
            if not environment:
                os.environ.pop('DOCKER_HOST', None)
            preflight.check_engine()

    def podman(self, version='5.4.0', rootless=True, socket='/run/user/1001/podman/podman.sock'):
        return {'podman info': json.dumps({'version': {'Version': version}, 'host': {
                    'security': {'rootless': rootless}, 'remoteSocket': {'path': socket}}}),
                'docker compose version': '2.36.0'}

    def test_docker_floors(self):
        self.check('docker', {'docker version': '28.0.0', 'docker compose version': '2.36.0'})
        for answers in ({'docker version': '27.9.9', 'docker compose version': '2.36.0'},
                        {'docker version': '28.0.0', 'docker compose version': '2.35.9'},
                        {'docker version': 'unknown', 'docker compose version': '2.36.0'}):
            with self.subTest(answers=answers), self.assertRaises(SystemExit):
                self.check('docker', answers)

    def test_podman_floors_rootless_and_endpoint(self):
        self.check('podman', self.podman())
        self.check('podman', self.podman(), {'DOCKER_HOST': 'unix:///run/user/1001/podman/podman.sock'})
        for answers, environment in ((self.podman(version='5.3.9'), None),
                                     (self.podman(rootless=False), None),
                                     ({**self.podman(), 'docker compose version': '2.26.1'}, None),
                                     ({'podman info': OSError('no podman')}, None),
                                     (self.podman(), {'DOCKER_HOST': 'unix:///run/podman/podman.sock'})):
            with self.subTest(answers=answers, environment=environment), self.assertRaises(SystemExit):
                self.check('podman', answers, environment)


class EngineDependentCheckTests(unittest.TestCase):
    def test_startup_requires_an_inference_provider_key(self):
        def config(**environment):
            return json.dumps({'services': {'teep': {'environment': {
                'TEEP_LISTEN_ADDR': '0.0.0.0:8337', 'NEARAI_API_KEY': '', 'VENICE_API_KEY': '', **environment}}}})
        with patch.object(stack, 'capture', return_value=config()), self.assertRaises(RuntimeError):
            stack.require_inference_key(['docker', 'compose'])
        with patch.object(stack, 'capture', return_value=config(NEARAI_API_KEY='set')):
            stack.require_inference_key(['docker', 'compose'])

    def test_preflight_reads_docker_and_podman_network_subnets(self):
        docker = {'Name': 'other', 'Labels': {}, 'IPAM': {'Config': [{'Subnet': '10.203.83.0/24'}]}}
        podman = {'name': 'other', 'subnets': [{'subnet': '10.203.84.0/24', 'gateway': '10.203.84.1'}]}
        self.assertEqual([str(net) for net in preflight.subnets(docker)], ['10.203.83.0/24'])
        self.assertEqual([str(net) for net in preflight.subnets(podman)], ['10.203.84.0/24'])
        self.assertEqual(preflight.subnets({'Name': 'empty', 'IPAM': {'Config': None}}), [])


if __name__ == '__main__':
    unittest.main()
