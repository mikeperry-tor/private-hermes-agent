"""Engine selection, the Podman overlays and checks that depend on the engine."""
import json
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
            with self.subTest(answers=answers):
                self.assertEqual(detect(answers), expected)

    def test_podman_files_are_last_and_funnel_file_only_with_funnel(self):
        with patch.object(deployment, 'engine', return_value='docker'):
            self.assertEqual(deployment.compose_files(True), ['-f', 'compose.yaml', '-f', 'compose.funnel.yaml'])
        with patch.object(deployment, 'engine', return_value='podman'):
            self.assertEqual(deployment.compose_files(False), ['-f', 'compose.yaml', '-f', 'compose.podman.yaml'])
            self.assertEqual(deployment.compose_files(True, extra=('tests/compose.yaml',)),
                             ['-f', 'compose.yaml', '-f', 'compose.funnel.yaml', '-f', 'tests/compose.yaml',
                              '-f', 'compose.podman.yaml', '-f', 'compose.podman.funnel.yaml'])
            self.assertIn('compose.podman.yaml', deployment.maintenance_compose(all_ingress=True))


class ComposeModelTests(unittest.TestCase):
    def test_docker_model_keeps_isolated_gateway_mode(self):
        config = model('compose.yaml', 'compose.funnel.yaml')
        for name, network in config['networks'].items():
            if network.get('internal'):
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
