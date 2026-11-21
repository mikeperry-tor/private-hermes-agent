"""Engine selection, engine commands, the Podman overlays and checks that depend on the engine."""
import importlib.util
import io
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
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


COMPOSE = None


def compose_command():
    # Model rendering needs only the Compose client, not a running engine.
    global COMPOSE
    if COMPOSE is None:
        with patch.dict(os.environ):
            COMPOSE = deployment.compose_base()
    return COMPOSE


def model(*files):
    arguments = [argument for name in files for argument in ('-f', name)]
    result = subprocess.run([*compose_command(), *arguments, '--profile', '*', '--env-file', '/dev/null',
                             'config', '--format', 'json'], cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class SelectorTests(unittest.TestCase):
    def select(self, text=None, exported=None):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ):
            os.environ.pop('CONTAINER_ENGINE', None)
            if exported is not None:
                os.environ['CONTAINER_ENGINE'] = exported
            path = Path(folder) / '.env'
            if text is not None:
                path.write_bytes(text.encode())
            return deployment.read_selector(path)

    def test_valid_forms(self):
        cases = (
            (None, 'docker'), ('', 'docker'), ('NEARAI_API_KEY=x\n', 'docker'),
            ('CONTAINER_ENGINE=podman\n', 'podman'), ('CONTAINER_ENGINE=docker\n', 'docker'),
            ('CONTAINER_ENGINE="podman"\n', 'podman'), ("CONTAINER_ENGINE='podman'\n", 'podman'),
            ('export CONTAINER_ENGINE=podman\n', 'podman'), ('  CONTAINER_ENGINE = podman  # local\n', 'podman'),
            ('CONTAINER_ENGINE=podman\r\nOTHER=1\r\n', 'podman'),
            ('CONTAINER_ENGINE=docker\nCONTAINER_ENGINE=podman\n', 'podman'),
            ('# CONTAINER_ENGINE=podman\n', 'docker'),
            ('NOTE="line one\nCONTAINER_ENGINE=podman\nline three"\n', 'docker'),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.select(text), expected)

    def test_exported_value_wins_and_needs_no_file(self):
        self.assertEqual(self.select('CONTAINER_ENGINE=docker\n', exported='podman'), 'podman')
        self.assertEqual(self.select('this is = not "valid\n', exported='docker'), 'docker')

    def test_invalid_values_are_errors_not_fallbacks(self):
        for text, exported in (('CONTAINER_ENGINE=\n', None), ('CONTAINER_ENGINE=Podman\n', None),
                               ('CONTAINER_ENGINE\n', None), ('CONTAINER_ENGINE=$(echo podman)\n', None),
                               ('CONTAINER_ENGINE=podman docker\n', None), (None, ''), (None, 'auto')):
            with self.subTest(text=text, exported=exported), self.assertRaises(deployment.EngineError) as caught:
                self.select(text, exported)
            self.assertNotIn('echo', str(caught.exception))

    def test_unreadable_and_malformed_files_name_the_path_and_line_only(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ):
            os.environ.pop('CONTAINER_ENGINE', None)
            with self.assertRaisesRegex(deployment.EngineError, 'Cannot read'):
                deployment.read_selector(Path(folder))
            path = Path(folder) / '.env'
            path.write_text('SECRET=hunter2\nOPEN="unterminated\n')
            with self.assertRaises(deployment.EngineError) as caught:
                deployment.read_selector(path)
            self.assertIn('line 2', str(caught.exception))
            self.assertNotIn('hunter2', str(caught.exception))
            self.assertNotIn('unterminated', str(caught.exception))

    def test_literal_forms_match_compose_parsing(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'compose.yaml').write_text('services:\n  x:\n    image: scratch\n'
                                                       '    environment:\n      SELECTED: ${CONTAINER_ENGINE}\n')
            for text in ('CONTAINER_ENGINE=podman\n', 'CONTAINER_ENGINE="podman"\n', "CONTAINER_ENGINE='podman'\n",
                         'export CONTAINER_ENGINE=podman\n', 'CONTAINER_ENGINE=podman # local\n',
                         'CONTAINER_ENGINE=docker\r\n', 'CONTAINER_ENGINE=docker\nCONTAINER_ENGINE=podman\n'):
                with self.subTest(text=text):
                    path = Path(folder) / 'engine.env'
                    path.write_bytes(text.encode())
                    environment = {k: v for k, v in os.environ.items() if k != 'CONTAINER_ENGINE'}
                    result = subprocess.run([*compose_command(), '--project-directory', folder, '-f',
                                             str(Path(folder) / 'compose.yaml'), '--env-file', str(path),
                                             'config', '--format', 'json'], text=True, capture_output=True,
                                            env=environment)
                    if result.returncode:
                        raise AssertionError(result.stderr)
                    composed = json.loads(result.stdout)['services']['x']['environment']['SELECTED']
                    with patch.dict(os.environ):
                        os.environ.pop('CONTAINER_ENGINE', None)
                        self.assertEqual(composed, deployment.read_selector(path))


class EngineCommandTests(unittest.TestCase):
    def test_renderer_build_and_checks_use_the_selected_engine(self):
        spec = importlib.util.spec_from_file_location('renderer_qualification', ROOT / 'tests/hermes_ui.py')
        renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
        for selected in ('docker', 'podman'):
            with self.subTest(engine=selected), patch.object(deployment, 'engine', return_value=selected), \
                    patch.object(renderer, 'run') as run, patch('sys.stdout', new=io.StringIO()):
                renderer.main()
                expected = deployment.engine_command()
            self.assertEqual(run.call_count, 3)
            for call in run.call_args_list:
                self.assertEqual(list(call.args[:len(expected)]), expected)
            for call in run.call_args_list[1:]:
                self.assertEqual(call.args[call.args.index('--network') + 1], 'none')

    def setUp(self):
        deployment.engine.cache_clear()
        deployment.check_engine.cache_clear()
        deployment._AMBIENT_OVERRIDES.clear()

    tearDown = setUp

    def test_commands_follow_the_selection(self):
        with patch.dict(os.environ, CONTAINER_ENGINE='docker'):
            self.assertEqual(deployment.compose_base(), ['docker', 'compose'])
        deployment.engine.cache_clear()
        with patch.dict(os.environ, CONTAINER_ENGINE='podman'):
            self.assertEqual(deployment.compose_base(), ['podman', '--remote=false', 'compose'])

    def test_podman_removes_endpoint_overrides_and_launch_refuses_them(self):
        with patch.dict(os.environ, CONTAINER_ENGINE='podman', DOCKER_HOST='tcp://10.9.9.9:2375',
                        CONTAINER_CONNECTION='other'):
            self.assertEqual(deployment.engine(), 'podman')
            self.assertNotIn('DOCKER_HOST', os.environ)
            self.assertNotIn('CONTAINER_CONNECTION', os.environ)
            with patch.object(deployment, '_output', side_effect=AssertionError('no engine query')), \
                    self.assertRaisesRegex(deployment.EngineError, 'Unset DOCKER_HOST, CONTAINER_CONNECTION'):
                deployment.check_engine()

    def test_docker_keeps_its_context_variables(self):
        with patch.dict(os.environ, CONTAINER_ENGINE='docker', DOCKER_CONTEXT='desktop-linux'):
            deployment.engine()
            self.assertEqual(os.environ['DOCKER_CONTEXT'], 'desktop-linux')

    def checked(self, selected, answers):
        def output(*args):
            key = ' '.join(args)
            for prefix, answer in answers.items():
                if key.startswith(prefix):
                    if isinstance(answer, Exception):
                        raise answer
                    return answer
            raise AssertionError(key)
        deployment.check_engine.cache_clear()
        with patch.object(deployment, 'engine', return_value=selected), \
                patch.object(deployment, '_output', side_effect=output):
            deployment.check_engine()

    def podman(self, version='5.4.0', rootless=True, socket=True, provider='Docker Compose version v2.36.0'):
        return {'podman --remote=false info': json.dumps({'version': {'Version': version}, 'host': {
                    'security': {'rootless': rootless}, 'remoteSocket': {'path': '/run/user/1/podman/podman.sock',
                                                                         'exists': socket}}}),
                'podman --remote=false compose version': provider}

    def docker(self, components=('Engine', 'containerd'), server='28.0.0', compose='2.36.0',
               client='Docker version 28.0.0, build 1'):
        return {'docker version --format {{json .Server.Components}}': json.dumps([{'Name': n} for n in components]),
                'docker version --format {{.Server.Version}}': server, 'docker --version': client,
                'docker compose version --short': compose}

    def test_docker_endpoint_must_be_docker_engine_at_the_floors(self):
        self.checked('docker', self.docker())
        for answers, reason in ((self.docker(components=('Podman Engine',)), 'reaches Podman'),
                                (self.docker(client='podman version 5.4.2'), 'reaches Podman'),
                                (self.docker(server='27.9.9'), 'Engine 28'),
                                (self.docker(compose='2.35.9'), 'Compose 2.36'),
                                ({'docker': OSError('no docker')}, 'Docker Engine is required')):
            with self.subTest(reason=reason), self.assertRaisesRegex(deployment.EngineError, reason):
                self.checked('docker', answers)

    def test_podman_must_be_local_rootless_with_socket_and_provider(self):
        self.checked('podman', self.podman())
        for answers, reason in ((self.podman(version='5.3.9'), '5.4'),
                                (self.podman(rootless=False), 'rootless'),
                                (self.podman(socket=False), 'podman.socket'),
                                (self.podman(provider='Docker Compose version v2.26.1'), '2.36'),
                                (self.podman(provider='podman-compose version 1.0.6'), '2.36'),
                                ({'podman --remote=false info': OSError('no podman')}, 'podman command')):
            with self.subTest(reason=reason), self.assertRaisesRegex(deployment.EngineError, reason):
                self.checked('podman', answers)

    def test_preflight_reports_engine_errors(self):
        with patch.object(deployment, 'check_engine', side_effect=deployment.EngineError('Podman 5.4 or later')), \
                self.assertRaisesRegex(SystemExit, 'Podman 5.4'):
            preflight.check_engine()

    def test_podman_files_are_last_and_funnel_file_only_with_funnel(self):
        with patch.object(deployment, 'engine', return_value='docker'):
            self.assertEqual(deployment.compose_files(True), ['-f', 'compose.yaml', '-f', 'compose.funnel.yaml'])
        with patch.object(deployment, 'engine', return_value='podman'):
            self.assertEqual(deployment.compose_files(False), ['-f', 'compose.yaml', '-f', 'compose.podman.yaml'])
            self.assertEqual(deployment.compose_files(True, extra=('tests/compose.yaml',)),
                             ['-f', 'compose.yaml', '-f', 'compose.funnel.yaml', '-f', 'tests/compose.yaml',
                              '-f', 'compose.podman.yaml', '-f', 'compose.podman.funnel.yaml'])
            with patch.dict(os.environ):
                self.assertIn('compose.podman.yaml', deployment.maintenance_compose(all_ingress=True))


class PassthroughTests(unittest.TestCase):
    def test_split_finds_the_subcommand_after_global_options(self):
        cases = (
            (['up', '-d'], ([], [], False, ['up', '-d'])),
            (['--profile', 'x402_treazury', 'up', '-d'], ([], ['--profile', 'x402_treazury'], False, ['up', '-d'])),
            (['-p', 'other', 'up'], ([], ['-p', 'other'], False, ['up'])),
            (['-pother', '--profile=a', '-f', 'x.yaml', '--file=y.yaml', 'up'],
             (['x.yaml', 'y.yaml'], ['-p', 'other', '--profile', 'a'], False, ['up'])),
            (['--env-file', 'e.env', '--project-directory', '.', 'create'],
             ([], ['--env-file', 'e.env', '--project-directory', '.'], False, ['create'])),
            (['--dry-run', 'up'], ([], ['--dry-run'], True, ['up'])),
            (['up', '--dry-run'], ([], [], True, ['up', '--dry-run'])),
            (['down', '--dry-run'], ([], [], True, ['down', '--dry-run'])),
            (['up', '--no-attach', '--dry-run', '-d', 'hermes'],
             ([], [], False, ['up', '--no-attach', '--dry-run', '-d', 'hermes'])),
            (['--dry-run', 'up', '--no-attach', '--dry-run=false', 'hermes'],
             ([], ['--dry-run'], True, ['up', '--no-attach', '--dry-run=false', 'hermes'])),
            (['run', '--dry-run', 'hermes'], ([], [], True, ['run', '--dry-run', 'hermes'])),
            (['run', 'hermes', 'echo', '--dry-run'], ([], [], False, ['run', 'hermes', 'echo', '--dry-run'])),
            (['--dry-run', 'run', '--dry-run=false', 'hermes'],
             ([], ['--dry-run'], False, ['run', '--dry-run=false', 'hermes'])),
            (['--dry-run=false', 'up', '--dry-run=true'],
             ([], ['--dry-run=false'], True, ['up', '--dry-run=true'])),
        )
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                self.assertEqual(deployment.split_passthrough(arguments)[:4], expected)

    def test_unsupported_or_incomplete_global_options_are_refused(self):
        for arguments in (['--ansi', 'never', 'up'], ['-c', 'ctx', 'up'], ['--profile'], ['--parallel=2', 'up']):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                deployment.split_passthrough(arguments)

    def run_passthrough(self, arguments, selected='podman', model=None, rejected=False):
        settings = deployment.Settings.read(dict(
            external_content='tor_proxied', onion_enabled='false', funnel_enabled='false', webapp_bind='127.0.0.1', webapp_port='9120',
            webapp_username='admin', funnel_host='', funnel_port='443', tailscale_hostname='private-hermes'))
        model = json.dumps(model or {'services': {'teep': {'networks': {'inference': None}},
                                                'setup': {'network_mode': 'none'},
                                                'dependent': {'network_mode': 'none', 'depends_on': {'teep': {}}},
                                                'offline-admin': {'network_mode': 'none', 'depends_on': {'setup': {}}},
                                                'transitive': {'network_mode': 'none', 'depends_on': {'dependent': {}}},
                                                'hermes': {'network_mode': 'service:agent-net'},
                                                'shared': {'network_mode': 'container:existing'},
                                                'x402_treazury-inspect': {'network_mode': 'none'}}})
        with patch.object(sys, 'argv', ['stack.py', 'compose', *arguments]), patch.dict(os.environ), \
                patch.object(deployment, 'engine', return_value=selected), \
                patch.object(deployment, '_output', return_value=model), \
                patch.object(stack, 'settings', return_value=(settings, [])), \
                patch.object(stack, 'prepare_launch') as prepare, patch.object(stack, 'remove_networks') as cleanup, \
                patch.object(stack, 'run') as run:
            if rejected:
                prepare.side_effect = deployment.EngineError('launch refused')
                with self.assertRaisesRegex(deployment.EngineError, 'launch refused'):
                    stack.main_unlocked()
                run.assert_not_called()
            else:
                stack.main_unlocked()
        return prepare, cleanup, run

    def test_every_networked_launch_is_prepared_with_the_same_project_and_files(self):
        for arguments, prepared in ((['up', '-d'], True), (['--profile', 'x402_treazury', 'up', '-d'], True),
                                    (['-p', 'another', 'up', '-d'], True), (['create'], True), (['start'], True),
                                    (['run', '--rm', 'teep', 'serve', '--help'], True),
                                    (['run', '--rm', '-e', 'A=1', '--entrypoint', 'sh', 'teep'], True),
                                    (['run', '--rm', '-T', '--entrypoint', 'python3', 'setup', '-c', 'x'], False),
                                    (['run', '--rm', 'hermes', 'chat'], True),
                                    (['run', '--rm', '--no-deps', 'hermes', 'chat'], True),
                                    (['run', '--rm', '--no-deps', 'shared'], True),
                                    (['run', '--rm', 'setup'], False),
                                    (['run', '--rm', 'dependent'], True),
                                    (['run', '--rm', '--no-deps', 'dependent'], True),
                                    (['run', '--rm', '--no-deps', 'transitive'], True),
                                    (['run', '--rm', '--no-deps', 'offline-admin'], False),
                                    (['run', '--rm', '--no-deps', 'setup'], False),
                                    (['scale', 'tor=1'], True),
                                    (['--dry-run', 'up'], False), (['ps'], False), (['config'], False),
                                    (['up', '--dry-run'], False), (['run', '--dry-run', 'hermes'], False),
                                    (['run', 'hermes', 'echo', '--dry-run'], True),
                                    (['logs', 'tor'], False)):
            with self.subTest(arguments=arguments):
                prepare, _, run = self.run_passthrough(arguments)
                self.assertEqual(prepare.called, prepared)
                launched = run.call_args.args[0]
                if prepared:
                    self.assertEqual(prepare.call_args.args[0], launched[:len(prepare.call_args.args[0])])
                if '-p' in arguments:
                    self.assertIn('another', launched)
        _, _, run = self.run_passthrough(['-f', 'extra.yaml', 'up'])
        launched = run.call_args.args[0]
        files = [value for flag, value in zip(launched, launched[1:]) if flag == '-f']
        self.assertEqual(files, ['compose.yaml', 'extra.yaml', 'compose.podman.yaml'])

    def test_passthrough_down_is_project_wide_without_removing_volumes(self):
        for selected in ('docker', 'podman'):
            prepare, cleanup, run = self.run_passthrough(
                ['-p', 'another', '--profile', 'x402_treazury', 'down'], selected=selected)
            command = run.call_args.args[0]
            self.assertEqual(command[-3:], ['--profile', '*', 'down'])
            self.assertNotIn('--volumes', command)
            prepare.assert_not_called()
            cleanup.assert_called_once_with(command[:-1])

    def test_shared_and_dependency_launches_check_both_engines_before_running(self):
        for selected in ('docker', 'podman'):
            for service in ('hermes', 'shared', 'dependent'):
                with self.subTest(engine=selected, service=service):
                    self.run_passthrough(['run', '--rm', service], selected=selected, rejected=True)
            self.run_passthrough(['run', '--rm', '--no-deps', 'hermes'], selected=selected, rejected=True)

    def test_dry_run_operand_cannot_bypass_engine_preparation(self):
        for selected in ('docker', 'podman'):
            self.run_passthrough(['up', '--no-attach', '--dry-run', '-d', 'teep'],
                                 selected=selected, rejected=True)
            with self.assertRaisesRegex(ValueError, 'Unsupported Compose creation'):
                self.run_passthrough(['--dry-run', 'watch'], selected=selected)

    def test_ambiguous_run_flags_cannot_select_an_offline_service(self):
        for selected in ('docker', 'podman'):
            self.run_passthrough(['run', '--no-deps', '-Te', 'x402_treazury-inspect', 'hermes'],
                                 selected=selected, rejected=True)
            with self.assertRaisesRegex(ValueError, 'Unsupported Compose run option'):
                self.run_passthrough(['run', '--no-deps', '--future-value-option', 'x402_treazury-inspect', 'hermes'],
                                     selected=selected)
            for option in ('-eNAME=value', '--env=NAME=value', '--entrypoint=python3'):
                prepare, _, _ = self.run_passthrough(['run', '--no-deps', option, 'x402_treazury-inspect'],
                                                     selected=selected)
                prepare.assert_not_called()

    def test_offline_maintenance_rejects_networking_overrides_on_both_engines(self):
        for selected in ('docker', 'podman'):
            for definition in ({'network_mode': 'service:agent-net'}, {'network_mode': 'container:existing'},
                               {'network_mode': 'bridge'}, {'network_mode': 'none', 'depends_on': {'teep': {}}}):
                with self.subTest(engine=selected, definition=definition), \
                        self.assertRaisesRegex(ValueError, 'Offline maintenance jobs require network_mode: none'):
                    self.run_passthrough(['run', '--rm', '--no-deps', 'x402_treazury-inspect'],
                                         selected=selected,
                                         model={'services': {'x402_treazury-inspect': definition}})
            prepared, _, run = self.run_passthrough(['run', '--rm', '--no-deps', 'x402_treazury-inspect'],
                                                   selected=selected)
            prepared.assert_not_called()
            run.assert_called_once()

    def test_unsupported_option_refuses_before_any_command(self):
        with patch.object(sys, 'argv', ['stack.py', 'compose', '--ansi', 'never', 'up']), patch.dict(os.environ), \
                patch.object(deployment, 'engine', return_value='podman'), \
                patch.object(stack, 'prepare_launch') as prepare, patch.object(stack, 'run') as run, \
                self.assertRaisesRegex(ValueError, 'Unsupported Compose global option --ansi'):
            stack.main_unlocked()
        prepare.assert_not_called()
        run.assert_not_called()

    def test_makefile_stops_on_an_invalid_selection(self):
        result = subprocess.run(['make', '-n', 'check'], cwd=ROOT, text=True, capture_output=True,
                                env={**os.environ, 'CONTAINER_ENGINE': 'bogus'})
        self.assertIn('CONTAINER_ENGINE in the environment must be docker or podman', result.stderr)
        self.assertIn('false -f compose.yaml', result.stdout)
        with patch.dict(os.environ, CONTAINER_ENGINE='podman'):
            printed = subprocess.run([sys.executable, 'scripts/deployment.py', 'compose-command'], cwd=ROOT,
                                     text=True, capture_output=True, check=True).stdout.split()
        self.assertEqual(printed[0], 'env')
        self.assertIn('--unset=DOCKER_HOST', printed)
        self.assertEqual(printed[-3:], ['podman', '--remote=false', 'compose'])

    def test_down_removes_leftover_networks_of_the_named_project(self):
        _, cleanup, run = self.run_passthrough(['-p', 'another', 'down', '--remove-orphans'])
        self.assertEqual(run.call_args.args[0][-2:], ['down', '--remove-orphans'])
        self.assertIn('another', cleanup.call_args.args[0])

    def test_dry_down_never_removes_real_networks_on_either_engine(self):
        for selected in ('docker', 'podman'):
            for arguments in (['--dry-run', 'down'], ['down', '--dry-run'], ['down', '--dry-run=true']):
                with self.subTest(engine=selected, arguments=arguments):
                    prepare, cleanup, _ = self.run_passthrough(arguments, selected=selected)
                    prepare.assert_not_called()
                    cleanup.assert_not_called()


class ComposeModelTests(unittest.TestCase):
    def test_native_webapp_fixture_preserves_production_hermes_privileges(self):
        environment = dict(TEST_DATA_DIR='/tmp/hermes-model-data',
                           WEBAPP_TEST_CONFIG='/tmp/hermes-model-auth',
                           WEBAPP_TEST_PROXY='/tmp/hermes-model-proxy',
                           WEBAPP_TEST_TLS='/tmp/hermes-model-tls')
        for enabled in ('false', 'true'):
            for selected in ('docker', 'podman'):
                with self.subTest(engine=selected, desktop=enabled), \
                        patch.dict(os.environ, **environment, COMPUTER_USE_ENABLED=enabled):
                    overlays = ['compose.podman.yaml', 'compose.podman.funnel.yaml'] if selected == 'podman' else []
                    production = model('compose.yaml', 'compose.funnel.yaml', *overlays)['services']['hermes']
                    fixture = model('compose.yaml', 'compose.funnel.yaml', 'tests/compose.yaml',
                                    'tests/webapp-compose.yaml', *overlays)['services']['hermes']
                    for key in ('cap_add', 'cap_drop', 'security_opt', 'command', 'user', 'init', 'entrypoint'):
                        self.assertEqual(fixture.get(key), production.get(key), key)

    def test_docker_model_keeps_isolated_gateway_mode(self):
        config = model('compose.yaml', 'compose.funnel.yaml')
        internal = {name for name, network in config['networks'].items() if network.get('internal')}
        self.assertEqual(internal, {'agent-route', 'executor-route', 'execution-control', 'inference',
                                    'mcp-access', 'webapp-backend', 'onion-ingress', 'funnel-link'})
        for name, network in config['networks'].items():
            if name in internal:
                with self.subTest(network=name):
                    options = network.get('driver_opts') or {}
                    self.assertEqual(options.get('com.docker.network.bridge.gateway_mode_ipv4'), 'isolated')
                    self.assertEqual(options.get('com.docker.network.bridge.gateway_mode_ipv6'), 'isolated')
        self.assertEqual(config['networks']['webapp-publish']['driver_opts'],
                         {'com.docker.network.bridge.enable_ip_masquerade': 'false'})

    def test_normal_podman_executor_preserves_boundaries_with_native_policy(self):
        for enabled in ('false', 'true'):
            for funnel in (False, True):
                with self.subTest(enabled=enabled, funnel=funnel), patch.dict(os.environ, COMPUTER_USE_ENABLED=enabled):
                    files = ['compose.yaml', *(['compose.funnel.yaml'] if funnel else [])]
                    original = model(*files)['services']['executor']
                    config = model(*files, 'compose.podman.yaml',
                                   *(['compose.podman.funnel.yaml'] if funnel else []))
                    expected = original.copy()
                    expected['security_opt'] = ['no-new-privileges:true']
                    expected['tmpfs'] = ['/tmp:mode=1777,notmpcopyup', '/run:mode=0755,notmpcopyup']
                    expected['healthcheck'] = {k: v for k, v in original['healthcheck'].items()
                                               if k != 'start_interval'}
                    self.assertEqual(config['services']['executor'], expected)
                    with patch.object(preflight, 'engine', return_value='podman'):
                        preflight.check_security_options(config)

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
    def test_build_preparation_uses_compose_flags_and_ignores_container_arguments(self):
        for arguments, expected in (
            (['up', '--build', 'tor'], True),
            (['create', '--build=false', 'tor'], False),
            (['run', '--build', 'tor'], True),
            (['run', '--build=false', 'tor', '--build'], False),
            (['run', '-e', '--build', 'tor'], False),
            (['run', 'tor', '--build'], False),
            (['restart', 'tor'], False),
        ):
            with self.subTest(arguments=arguments):
                self.assertIs(deployment.parse_launch(arguments).build, expected)

    def test_cold_requested_build_produces_the_probe_image_before_startup(self):
        tor = {'image': 'network-fixture', 'environment': {'HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS': '11434'}}
        command = ['docker', 'compose', '-p', 'fixture']
        events = []

        def invoke(arguments, **_kwargs):
            events.append(arguments)
            return subprocess.CompletedProcess(arguments, 1 if 'inspect' in arguments else 0)

        def probe(image, network):
            events.append(['probe', image, network])
            return ipaddress.IPv4Address('192.168.65.254')

        with patch.dict(os.environ), patch.object(deployment, 'engine', return_value='docker'), \
                patch.object(deployment, 'check_engine'), \
                patch.object(deployment, 'engine_host_address', side_effect=probe), \
                patch.object(subprocess, 'run', side_effect=invoke):
            deployment.prepare_launch(command, {'services': {'tor': tor}}, build_missing=True)
        self.assertEqual(events, [
            ['docker', 'image', 'inspect', 'network-fixture'], [*command, 'build', 'tor'],
            ['probe', 'network-fixture', 'none'],
        ])

    def test_podman_host_mapping_uses_the_project_bridge_and_empty_hosts_base(self):
        key = 'PRIVATE_HERMES_ENGINE_HOST_ADDRESS'
        procfs = 'PRIVATE_HERMES_TOR_PROCFS_OPTION'
        tor = {'image': 'network-fixture', 'environment': {'HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS': '11434'}}
        model = {'services': {'tor': tor}, 'networks': {'tor-uplink': {'name': 'fixture_tor-uplink'}}}
        command = ['podman', 'compose']
        with patch.dict(os.environ, {key: '192.168.50.4'}), \
                patch.object(deployment, 'engine', return_value='podman'), \
                patch.object(deployment, 'check_engine'), \
                patch.object(deployment, 'ensure_networks'), \
                patch.object(deployment, 'engine_host_address', return_value=None) as probe:
            deployment.prepare_launch(command, model)
            probe.assert_called_once_with('network-fixture', 'fixture_tor-uplink', '--hosts-file=none')
            self.assertEqual(os.environ[key], '')
            self.assertEqual(os.environ[procfs], '')
            probe.return_value = ipaddress.IPv4Address('169.254.1.2')
            deployment.prepare_launch(command, model)
            self.assertEqual(os.environ[key], '169.254.1.2')
            self.assertEqual(os.environ[procfs], 'unmask=/proc/sys')

    def test_docker_host_mapping_checks_only_when_tor_can_be_created(self):
        tor = {'image': 'network-fixture', 'environment': {'HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS': '11434'}}
        model = json.dumps({'services': {'tor': tor, 'hermes': {}, 'x402_treazury': {}}})
        command = ['docker', 'compose']
        with patch.dict(os.environ), patch.object(deployment, 'engine', return_value='docker'), \
                patch.object(deployment, 'check_engine'), patch.object(deployment, '_output', return_value=model), \
                patch.object(deployment, 'engine_host_address', return_value=None) as probe:
            for arguments in (['run', '--no-deps', 'hermes', 'chat'], ['up', '--no-deps', 'x402_treazury'],
                              ['restart', 'tor'], ['up', '--scale', 'tor=0']):
                deployment.prepare_launch(command, deployment.check_bind_sources(command, arguments))
            probe.assert_not_called()
            for arguments in (['up', '--no-deps', 'tor'], ['create', 'hermes'], ['run', '--no-deps', 'tor']):
                deployment.prepare_launch(command, deployment.check_bind_sources(command, arguments))
            self.assertEqual(probe.call_count, 3)

    def test_docker_host_mapping_is_optional_for_tor(self):
        key = 'PRIVATE_HERMES_ENGINE_HOST_ADDRESS'
        platform = 'PRIVATE_HERMES_NETWORK_PLATFORM'
        procfs = 'PRIVATE_HERMES_TOR_PROCFS_OPTION'
        tor = {'image': 'network-fixture', 'environment': {}}
        model = {'services': {'tor': tor}}
        with patch.dict(os.environ, {key: '192.168.65.254', platform: 'docker-desktop', procfs: 'systempaths=unconfined'}), \
                patch.object(deployment, 'engine', return_value='docker'), \
                patch.object(deployment, 'check_engine'), \
                patch.object(deployment, 'docker_desktop') as desktop, \
                patch.object(deployment, 'engine_host_address', return_value=None) as probe:
            deployment.prepare_launch(['docker', 'compose'], model)
            probe.assert_not_called()
            self.assertEqual(os.environ[key], '')
            self.assertEqual(os.environ[platform], 'docker')
            self.assertEqual(os.environ[procfs], '')

            tor['environment']['HERMES_INTEGRATIONS_ALLOWED_HOST_PORTS'] = '11434'
            deployment.prepare_launch(['docker', 'compose'], model)
            probe.assert_called_once_with('network-fixture', 'none')
            self.assertEqual(os.environ[key], '')
            self.assertEqual(os.environ[procfs], '')

            probe.return_value = ipaddress.IPv4Address('192.168.65.254')
            deployment.prepare_launch(['docker', 'compose'], model)
            self.assertEqual(os.environ[key], '192.168.65.254')
            self.assertEqual(os.environ[procfs], 'systempaths=unconfined')
            desktop.assert_not_called()

    def test_lan_only_never_probes_a_host_mapping(self):
        tor = {'environment': {'HERMES_INTEGRATIONS_LAN_ENDPOINTS': '192.168.50.4:8080'}}
        for selected, desktop, platform, procfs in (
            ('docker', False, 'docker', ''),
            ('docker', True, 'docker-desktop', 'systempaths=unconfined'),
            ('podman', False, 'podman', 'unmask=/proc/sys'),
        ):
            with self.subTest(platform=platform), \
                    patch.dict(os.environ, PRIVATE_HERMES_ENGINE_HOST_ADDRESS='192.168.65.254'), \
                    patch.object(deployment, 'engine', return_value=selected), \
                    patch.object(deployment, 'check_engine'), patch.object(deployment, 'ensure_networks'), \
                    patch.object(deployment, 'docker_desktop', return_value=desktop), \
                    patch.object(deployment, 'engine_image_available') as inspect, \
                    patch.object(deployment, 'engine_host_address') as probe:
                deployment.prepare_launch([], {'services': {'tor': tor}}, build_missing=True)
                self.assertEqual(os.environ['PRIVATE_HERMES_ENGINE_HOST_ADDRESS'], '')
                self.assertEqual(os.environ['PRIVATE_HERMES_NETWORK_PLATFORM'], platform)
                self.assertEqual(os.environ['PRIVATE_HERMES_TOR_PROCFS_OPTION'], procfs)
                probe.assert_not_called()
                inspect.assert_not_called()

    CONFIG = {'name': 'private-hermes', 'networks': {
        'inference': {'name': 'private-hermes_inference', 'internal': True,
                      'driver_opts': {'isolate': 'strict'}, 'ipam': {'config': [{'subnet': '10.203.83.0/24'}]}},
        'webapp-publish': {'name': 'private-hermes_webapp-publish',
                           'driver_opts': {'isolate': 'strict', 'no_default_route': 'true'}},
        'outside': {'name': 'shared', 'external': True}}}

    def run_ensure(self, inspected, config=CONFIG):
        calls = []
        def run(arguments, **kwargs):
            calls.append(arguments)
            if arguments[:4] == ['podman', '--remote=false', 'network', 'inspect']:
                found = inspected.get(arguments[4])
                return subprocess.CompletedProcess(arguments, 0 if found else 125, json.dumps([found]) if found else '', '')
            return subprocess.CompletedProcess(arguments, 0, '', '')
        with patch.object(deployment, 'engine', return_value='podman'), \
                patch.object(deployment.subprocess, 'run', side_effect=run):
            deployment.ensure_networks(config)
        return [call[2:] for call in calls if call[:4] == ['podman', '--remote=false', 'network', 'create']]

    def test_missing_networks_are_created_with_declared_options_and_compose_labels(self):
        created = self.run_ensure({})
        self.assertEqual(created, [
            ['network', 'create', '--label', 'com.docker.compose.project=private-hermes',
             '--label', 'com.docker.compose.network=inference', '--internal', '--subnet', '10.203.83.0/24',
             '--opt', 'isolate=strict', 'private-hermes_inference'],
            ['network', 'create', '--label', 'com.docker.compose.project=private-hermes',
             '--label', 'com.docker.compose.network=webapp-publish',
             '--opt', 'isolate=strict', '--opt', 'no_default_route=true', 'private-hermes_webapp-publish']])

    def test_local_only_launch_does_not_prepare_the_teep_uplink(self):
        command = [*compose_command(), '--env-file', '/dev/null', '-p', 'local-only-fixture',
                   '-f', 'compose.yaml', '-f', 'compose.podman.yaml']
        with patch.dict(os.environ, TEEP_ENABLED='false'), patch.object(Path, 'exists', return_value=True):
            launch = deployment.check_bind_sources(command, ['up', '--no-deps', 'agent-net', 'hermes', 'webapp-proxy'])
        created = {call[-1] for call in self.run_ensure({}, launch)}
        self.assertIn('local-only-fixture_inference', created)
        self.assertNotIn('local-only-fixture_teep-uplink', created)

    def test_matching_networks_are_kept_and_weaker_ones_stop_startup(self):
        def labels(key):
            return {'driver': 'bridge', 'labels': {'com.docker.compose.project': 'private-hermes',
                                                   'com.docker.compose.network': key}}
        good = {'private-hermes_inference': {'options': {'isolate': 'strict'}, 'internal': True,
                                             'subnets': [{'subnet': '10.203.83.0/24'}], **labels('inference')},
                'private-hermes_webapp-publish': {'options': {'isolate': 'strict', 'no_default_route': 'true'},
                                                  'internal': False, 'subnets': [{'subnet': '10.89.2.0/24'}],
                                                  **labels('webapp-publish')}}
        self.assertEqual(self.run_ensure(good), [])
        # Compose through the Docker-compatible API creates isolate=true only.
        for name, change in (('private-hermes_inference', {'options': {'isolate': 'true'}}),
                             ('private-hermes_inference', {'internal': False}),
                             ('private-hermes_inference', {'subnets': [{'subnet': '10.203.99.0/24'}]}),
                             ('private-hermes_webapp-publish', {'options': {'isolate': 'strict'}})):
            with self.subTest(name=name, change=change), self.assertRaisesRegex(RuntimeError, 'make down'):
                self.run_ensure({**good, name: {**good[name], **change}})
        # A network of another driver or project is not adopted.
        for change in ({'driver': 'macvlan'}, {'labels': {}},
                       {'labels': {'com.docker.compose.project': 'other', 'com.docker.compose.network': 'inference'}}):
            with self.subTest(change=change), self.assertRaisesRegex(RuntimeError, 'not a bridge network of this project'):
                self.run_ensure({**good, 'private-hermes_inference': {**good['private-hermes_inference'], **change}})

    def test_down_removes_only_this_projects_leftover_networks(self):
        inspected = {'private-hermes_inference': {'labels': {'com.docker.compose.project': 'private-hermes'}},
                     'private-hermes_webapp-publish': {'labels': {'com.docker.compose.project': 'other'}}}
        calls = []
        def run(arguments, **kwargs):
            calls.append(arguments)
            if arguments[:4] == ['podman', '--remote=false', 'network', 'inspect']:
                found = inspected.get(arguments[4])
                return subprocess.CompletedProcess(arguments, 0 if found else 125, json.dumps([found]) if found else '', '')
            return subprocess.CompletedProcess(arguments, 0, '', '')
        with patch.object(deployment, 'engine', return_value='podman'), \
                patch.object(deployment, '_output', return_value=json.dumps(self.CONFIG)), \
                patch.object(deployment.subprocess, 'run', side_effect=run):
            deployment.remove_networks(['docker', 'compose'])
        self.assertEqual([call for call in calls if call[2:4] == ['network', 'rm']],
                         [['podman', '--remote=false', 'network', 'rm', 'private-hermes_inference']])

    def test_a_network_without_strict_isolation_stops_startup(self):
        for options in ({}, {'isolate': 'true'}):
            config = {'name': 'private-hermes', 'networks': {'net': {'name': 'private-hermes_net', 'driver_opts': options}}}
            with self.subTest(options=options), patch.object(deployment, 'engine', return_value='podman'), \
                    patch.object(deployment.subprocess, 'run', side_effect=AssertionError('no network command')), \
                    self.assertRaisesRegex(RuntimeError, 'isolate: strict'):
                deployment.ensure_networks(config)

    def test_network_removal_reports_a_failed_model_query_without_raising(self):
        with patch.object(deployment, 'engine', return_value='podman'), \
                patch.object(deployment, '_output', side_effect=subprocess.CalledProcessError(1, 'podman')), \
                patch('sys.stderr', new_callable=io.StringIO) as stderr:
            deployment.remove_networks(['podman', 'compose'])
        self.assertIn('Could not list the project networks', stderr.getvalue())

    def test_docker_engine_creates_no_network(self):
        with patch.object(deployment, 'engine', return_value='docker'), \
                patch.object(deployment.subprocess, 'run', side_effect=AssertionError('no network command')):
            deployment.ensure_networks(self.CONFIG)


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


class PreflightSecurityOptionTests(unittest.TestCase):
    def config(self, *options):
        return {'services': {'executor': {'security_opt': ['no-new-privileges:true', *options]},
                             'teep': {}}}

    def test_podman_refuses_a_custom_seccomp_profile(self):
        with patch.object(preflight, 'engine', return_value='podman'):
            preflight.check_security_options(self.config())
            preflight.check_security_options(self.config('seccomp=unconfined'))
            with self.assertRaisesRegex(SystemExit, '(?s)executor.*seccomp-desktop.json.*inline JSON.*native Podman default'):
                preflight.check_security_options(self.config('seccomp=./components/executor/seccomp-desktop.json'))

    def test_docker_keeps_custom_seccomp_profiles(self):
        with patch.object(preflight, 'engine', return_value='docker'):
            preflight.check_security_options(self.config('seccomp=./components/executor/seccomp-desktop.json'))

    def test_docker_definition_selects_the_profile_only_when_enabled(self):
        def options(value):
            result = subprocess.run([*compose_command(), '-f', 'compose.yaml', '--env-file', '/dev/null', 'config',
                                     '--format', 'json'], cwd=ROOT, text=True, capture_output=True,
                                    env={**os.environ, 'COMPUTER_USE_ENABLED': value})
            if result.returncode:
                raise AssertionError(result.stderr)
            return json.loads(result.stdout)['services']['executor']['security_opt']
        self.assertFalse([o for o in options('false') if o.startswith('seccomp=')])
        self.assertTrue([o for o in options('true') if o.startswith('seccomp=')])


class EngineDependentCheckTests(unittest.TestCase):
    def test_startup_requires_an_inference_provider_key(self):
        def config(**environment):
            return json.dumps({'services': {'teep': {'environment': {
                'TEEP_LISTEN_ADDR': '0.0.0.0:8337', 'NEARAI_API_KEY': '', 'VENICE_API_KEY': '', **environment}}}})
        with patch.object(stack, 'capture', return_value=config()), self.assertRaises(RuntimeError):
            stack.require_inference_key(['docker', 'compose'])
        with patch.object(stack, 'capture', return_value=config(NEARAI_API_KEY='set')):
            stack.require_inference_key(['docker', 'compose'])

    def test_preflight_failure_exits_without_a_wrapper_traceback(self):
        with patch.object(stack, 'run',
                          side_effect=subprocess.CalledProcessError(1, ['preflight'])):
            with self.assertRaises(SystemExit) as raised:
                stack.run_preflight(['python3', 'scripts/preflight.py'])
        self.assertEqual(raised.exception.code, 1)

    def test_successful_preflight_returns_normally(self):
        with patch.object(stack, 'run') as run:
            stack.run_preflight(['python3', 'scripts/preflight.py'])
        run.assert_called_once_with(['python3', 'scripts/preflight.py'])

    def test_preflight_stops_on_a_foreign_network_with_an_overlapping_subnet(self):
        model = json.dumps({'services': {}, 'networks': {'inference': {'ipam': {'config': [{'subnet': '10.203.83.0/24'}]}}}})
        own = {'name': 'private-hermes_inference', 'labels': {'com.docker.compose.project': 'private-hermes'},
               'subnets': [{'subnet': '10.203.83.0/24'}]}
        foreign = {'name': 'other', 'labels': {}, 'subnets': [{'subnet': '10.203.83.0/25'}]}
        def output(*args):
            if 'config' in args:
                return model
            if args[-3:] == ('network', 'ls', '-q'):
                return 'a b'
            if 'network' in args and 'inspect' in args:
                return json.dumps(self.networks)
            if args[-2:] == ('ps', '-q'):
                return ''
            raise AssertionError(f'Unexpected command: {args}')
        for networks, conflict in (([own], False), ([own, foreign], True)):
            self.networks = networks
            with self.subTest(conflict=conflict), patch.object(preflight, 'output', side_effect=output), \
                    patch.object(preflight, 'check_engine'), patch.object(preflight, 'engine', return_value='podman'), \
                    patch.object(sys, 'argv', ['preflight.py']), patch('sys.stdout', new_callable=io.StringIO):
                if conflict:
                    with self.assertRaises(SystemExit) as raised:
                        preflight.main()
                    message = str(raised.exception)
                    self.assertIn('Address conflict', message)
                    self.assertIn('10.203.83.0/24', message)
                    self.assertIn('inference', message)
                    self.assertIn('other', message)
                else:
                    preflight.main()

    def test_preflight_skip_ports_skips_container_inspection_and_port_checks(self):
        model = json.dumps({
            'services': {'teep': {'ports': [{'host_ip': '127.0.0.1', 'published': '8337', 'protocol': 'tcp'}]}},
            'networks': {'inference': {'ipam': {'config': [{'subnet': '10.203.83.0/24'}]}}},
        })
        def output(*args):
            if 'config' in args:
                return model
            if args[-3:] == ('network', 'ls', '-q'):
                return ''
            raise AssertionError(f'Should not inspect containers with --skip-ports: {args}')
        with patch.object(preflight, 'output', side_effect=output), \
                patch.object(preflight, 'check_engine'), patch.object(preflight, 'engine', return_value='docker'), \
                patch.object(preflight, 'check_published_ports', side_effect=AssertionError('port check ran')), \
                patch.object(sys, 'argv', ['preflight.py', 'private-hermes-test', '--skip-ports']), \
                patch('sys.stdout', new_callable=io.StringIO):
            preflight.main()

    def test_preflight_scopes_ports_and_subnets_to_selected_services(self):
        existing = {'Name': 'foreign-network', 'IPAM': {'Config': [{'Subnet': '10.203.89.0/24'}]}}
        args = ['preflight.py', '--services', 'hermes', 'webapp-proxy']

        def output(*command):
            if 'config' in command:
                options = command[command.index('config'):]
                return subprocess.check_output([*compose_command(), '--env-file', '/dev/null', '-f', 'compose.yaml',
                                                *options], cwd=ROOT, text=True)
            if command[-3:] == ('network', 'ls', '-q'):
                return 'foreign-network'
            if command[-3:] == ('network', 'inspect', 'foreign-network'):
                return json.dumps([existing])
            self.assertEqual(command[-2:], ('ps', '-q'))
            return ''

        with patch.object(preflight, 'output', side_effect=output), patch.object(preflight, 'check_engine'), \
                patch.object(preflight, 'engine', return_value='docker'), patch.dict(os.environ, WEBAPP_PORT='19120'), \
                patch('sys.stdout', new_callable=io.StringIO), patch.object(preflight.socket, 'socket') as probe:
            with patch.object(sys, 'argv', args):
                preflight.main()
            probe.return_value.__enter__.return_value.bind.assert_called_once_with(('127.0.0.1', 19120))
            with patch.object(sys, 'argv', [*args, 'teep']), self.assertRaisesRegex(SystemExit, 'teep-uplink'):
                preflight.main()

    def test_preflight_tolerates_vanished_container_during_inspect(self):
        kept = {'Name': '/other', 'Config': {'Labels': {}}}
        def output(*args):
            if args[-2:] == ('gone', 'alive'):
                raise subprocess.CalledProcessError(1, args)
            if args[-1] == 'gone':
                raise subprocess.CalledProcessError(1, args)
            if args[-1] == 'alive':
                return json.dumps([kept])
            raise AssertionError(f'Unexpected command: {args}')
        with patch.object(preflight, 'output', side_effect=output), \
                patch.object(preflight, 'engine', return_value='docker'):
            self.assertEqual(preflight.inspect_resources((), ['gone', 'alive']), [kept])

    def test_preflight_points_to_the_address_plan_and_engine_pools(self):
        config = {'networks': {'tor-uplink': {'ipam': {'config': [{'subnet': '10.203.88.0/24'}]}}}}
        existing = [{'name': 'other', 'labels': {}, 'subnets': [{'subnet': '10.203.88.0/24'}]}]
        with patch.object(preflight, 'engine', return_value='docker'), self.assertRaises(SystemExit) as raised:
            preflight.check_address_conflicts('private-hermes', config, existing)
        message = str(raised.exception)
        self.assertIn('networks: block of compose.yaml', message)
        self.assertIn('default-address-pools', message)
        self.assertIn('Docker Desktop', message)
        with patch.object(preflight, 'engine', return_value='podman'), self.assertRaises(SystemExit) as raised:
            preflight.check_address_conflicts('private-hermes', config, existing)
        podman_message = str(raised.exception)
        self.assertIn('default_subnet_pools', podman_message)
        self.assertNotIn('Docker Desktop', podman_message)

    def test_preflight_detects_lingering_project_network_overlap_and_ignores_extra_address_family(self):
        config = {'networks': {'tor-uplink': {'ipam': {'config': [{'subnet': '10.203.88.0/24'}]}}}}
        dual_stack = [{'name': 'private-hermes_tor-uplink',
                       'labels': {'com.docker.compose.project': 'private-hermes',
                                  'com.docker.compose.network': 'tor-uplink'},
                       'subnets': [{'subnet': '10.203.88.0/24'}, {'subnet': 'fd00:1::/64'}]}]
        preflight.check_address_conflicts('private-hermes', config, dual_stack)
        lingering = [{'name': 'private-hermes_tailscale-uplink',
                      'labels': {'com.docker.compose.project': 'private-hermes',
                                 'com.docker.compose.network': 'tailscale-uplink'},
                      'subnets': [{'subnet': '10.203.88.0/24'}]}]
        with self.assertRaises(SystemExit) as raised:
            preflight.check_address_conflicts('private-hermes', config, lingering)
        self.assertIn('stale project networks', str(raised.exception))

    def test_preflight_reports_overlapping_declared_subnets(self):
        config = {'networks': {'tor-uplink': {'ipam': {'config': [{'subnet': '10.203.88.0/24'}]}},
                               'teep-uplink': {'ipam': {'config': [{'subnet': '10.203.88.0/25'}]}}}}
        with self.assertRaises(SystemExit) as raised:
            preflight.check_address_conflicts('private-hermes', config, [])
        message = str(raised.exception)
        self.assertIn('overlapping subnets', message)
        self.assertIn('networks: block of compose.yaml', message)

    def test_preflight_requires_make_down_when_a_project_network_subnet_changed(self):
        config = {'networks': {'tor-uplink': {'ipam': {'config': [{'subnet': '10.203.88.0/24'}]}}}}
        existing = [{'name': 'private-hermes_tor-uplink',
                     'labels': {'com.docker.compose.project': 'private-hermes',
                                'com.docker.compose.network': 'tor-uplink'},
                     'subnets': [{'subnet': '192.168.240.0/20'}]}]
        with self.assertRaises(SystemExit) as raised:
            preflight.check_address_conflicts('private-hermes', config, existing)
        message = str(raised.exception)
        self.assertIn('Run make down to remove the project networks.', message)
        self.assertIn('Run make up to recreate them.', message)

    def test_preflight_accepts_a_clean_pinned_plan(self):
        config = {'networks': {'tor-uplink': {'ipam': {'config': [{'subnet': '10.203.88.0/24'}]}}}}
        existing = [{'name': 'other', 'labels': {}, 'subnets': [{'subnet': '172.18.0.0/16'}]}]
        preflight.check_address_conflicts('private-hermes', config, existing)

    def test_preflight_accepts_a_matching_project_network(self):
        config = {'networks': {'inference': {'ipam': {'config': [{'subnet': '10.203.83.0/24'}]}}}}
        existing = [{'name': 'private-hermes_inference',
                     'labels': {'com.docker.compose.project': 'private-hermes',
                                'com.docker.compose.network': 'inference'},
                     'subnets': [{'subnet': '10.203.83.0/24'}]}]
        preflight.check_address_conflicts('private-hermes', config, existing)

    def test_preflight_reports_a_foreign_container_holding_a_published_port_even_when_probe_succeeds(self):
        # On macOS, binding 127.0.0.1 succeeds even when a foreign container holds 0.0.0.0:port.
        config = {'services': {'teep': {'ports': [
            {'mode': 'ingress', 'host_ip': '127.0.0.1', 'target': 8337,
             'published': '8337', 'protocol': 'tcp'}]}}}
        foreign = [{'Name': '/onyx-teep-1',
                    'Config': {'Labels': {'com.docker.compose.project': 'onyx'}},
                    'NetworkSettings': {'Ports': {'8337/tcp': [
                        {'HostIp': '0.0.0.0', 'HostPort': '8337'}]}}}]
        with patch.object(preflight.socket, 'socket') as factory, self.assertRaises(SystemExit) as raised:
            preflight.check_published_ports('private-hermes', config, foreign)
        factory.assert_not_called()
        message = str(raised.exception)
        self.assertIn('Host port conflict', message)
        self.assertIn('onyx-teep-1', message)
        self.assertIn('TEEP_HOST_PORT', message)
        self.assertIn('docs/configuration.md', message)

    def test_preflight_matches_own_and_foreign_bindings_by_ip_and_protocol(self):
        # Own container on 127.0.0.1:9120/tcp must not suppress a conflict on 127.0.0.2:9120/tcp or 9120/udp.
        own = [{'Name': '/private-hermes-webapp-proxy-1',
                'Config': {'Labels': {'com.docker.compose.project': 'private-hermes'}},
                'NetworkSettings': {'Ports': {'9120/tcp': [
                    {'HostIp': '127.0.0.1', 'HostPort': '9120'}]}}}]
        foreign_udp = [{'Name': '/other-udp',
                        'Config': {'Labels': {'com.docker.compose.project': 'other'}},
                        'NetworkSettings': {'Ports': {'9120/udp': [
                            {'HostIp': '127.0.0.1', 'HostPort': '9120'}]}}}]
        foreign_other_ip = [{'Name': '/other-ip',
                             'Config': {'Labels': {'com.docker.compose.project': 'other'}},
                             'NetworkSettings': {'Ports': {'9120/tcp': [
                                 {'HostIp': '127.0.0.2', 'HostPort': '9120'}]}}}]
        # Matching own binding is allowed.
        config_same = {'services': {'webapp-proxy': {'ports': [
            {'host_ip': '127.0.0.1', 'target': 9120, 'published': '9120', 'protocol': 'tcp'}]}}}
        preflight.check_published_ports('private-hermes', config_same, own)
        # Moving to 127.0.0.2 collides with foreign_other_ip even though own holds 127.0.0.1:9120.
        config_moved = {'services': {'webapp-proxy': {'ports': [
            {'host_ip': '127.0.0.2', 'target': 9120, 'published': '9120', 'protocol': 'tcp'}]}}}
        with self.assertRaises(SystemExit) as raised:
            preflight.check_published_ports('private-hermes', config_moved, [*own, *foreign_other_ip])
        self.assertIn('other-ip', str(raised.exception))
        # A foreign UDP container must not be blamed for a host TCP listener.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            config_tcp = {'services': {'teep': {'ports': [
                {'host_ip': '127.0.0.1', 'target': 8337, 'published': str(port), 'protocol': 'tcp'}]}}}
            udp_same_port = [{'Name': '/other-udp',
                              'Config': {'Labels': {'com.docker.compose.project': 'other'}},
                              'NetworkSettings': {'Ports': {f'{port}/udp': [
                                  {'HostIp': '127.0.0.1', 'HostPort': str(port)}]}}}]
            with self.assertRaises(SystemExit) as raised:
                preflight.check_published_ports('private-hermes', config_tcp, udp_same_port)
            self.assertNotIn('other-udp', str(raised.exception))

    def test_preflight_probes_for_a_non_container_listener(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            config = {'services': {'teep': {'ports': [
                {'host_ip': '127.0.0.1', 'target': 8337, 'published': str(port), 'protocol': 'tcp'}]}}}
            with self.assertRaises(SystemExit) as raised:
                preflight.check_published_ports('private-hermes', config, [])
            message = str(raised.exception)
            self.assertIn('Host port conflict', message)
            self.assertIn('TEEP_HOST_PORT', message)

    def test_preflight_accepts_an_available_published_port(self):
        config = {'services': {'teep': {'ports': [
            {'host_ip': '127.0.0.1', 'target': 8337, 'published': '8339', 'protocol': 'tcp'}]}}}
        with patch.object(preflight.socket, 'socket') as factory:
            preflight.check_published_ports('private-hermes', config, [])
        factory.return_value.__enter__.return_value.bind.assert_called_once_with(('127.0.0.1', 8339))

    def test_preflight_checks_every_published_port(self):
        free = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        free.bind(('127.0.0.1', 0))
        free_port = free.getsockname()[1]
        free.close()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(('127.0.0.1', 0))
            busy.listen()
            busy_port = busy.getsockname()[1]
            config = {'services': {
                'teep': {'ports': [{'host_ip': '127.0.0.1', 'published': str(free_port), 'protocol': 'tcp'}]},
                'webapp-proxy': {'ports': [{'host_ip': '127.0.0.1', 'published': str(busy_port),
                                            'protocol': 'tcp'}]}}}
            with self.assertRaises(SystemExit) as raised:
                preflight.check_published_ports('private-hermes', config, [])
        message = str(raised.exception)
        self.assertIn(f':{busy_port}/tcp', message)
        self.assertNotIn(f':{free_port}/tcp', message)

    def test_preflight_detects_duplicate_declared_host_ports(self):
        config = {'services': {
            'teep': {'ports': [{'host_ip': '::1', 'published': '9120', 'protocol': 'tcp'}]},
            'webapp-proxy': {'ports': [{'host_ip': '::1', 'published': '9120', 'protocol': 'tcp'}]}}}
        with self.assertRaises(SystemExit) as raised:
            preflight.check_published_ports('private-hermes', config, [])
        message = str(raised.exception)
        self.assertIn('Host port conflict', message)
        self.assertIn('[::1]:9120/tcp', message)
        self.assertIn('teep', message)
        self.assertIn('webapp-proxy', message)

    def test_preflight_detects_wildcard_host_port_overlap(self):
        config = {'services': {
            'teep': {'ports': [{'host_ip': '0.0.0.0', 'published': '9120', 'protocol': 'tcp'}]},
            'webapp-proxy': {'ports': [{'host_ip': '127.0.0.1', 'published': '9120', 'protocol': 'tcp'}]}}}
        with self.assertRaises(SystemExit):
            preflight.check_published_ports('private-hermes', config, [])

    def test_preflight_expands_published_port_ranges_and_ignores_port_zero(self):
        config = {'services': {'teep': {'ports': [
            {'host_ip': '127.0.0.1', 'published': '9000-9002', 'protocol': 'tcp'}]}}}
        self.assertEqual([port for _, _, port, _ in preflight.published_ports(config)], [9000, 9001, 9002])
        self.assertEqual(preflight.published_values(''), [])
        self.assertEqual(preflight.published_values('0'), [])
        self.assertEqual(preflight.published_values('65536'), [])
        self.assertEqual(preflight.published_values('0-10'), [])
        self.assertEqual(preflight.published_values('abc'), [])
        self.assertEqual(preflight.published_values('9002-9000'), [])
        ephemeral = {'services': {
            'teep': {'ports': [{'host_ip': '127.0.0.1', 'published': '0', 'protocol': 'tcp'}]},
            'webapp-proxy': {'ports': [{'host_ip': '127.0.0.1', 'published': '0', 'protocol': 'tcp'}]}}}
        preflight.check_published_ports('private-hermes', ephemeral, [])

    def test_preflight_compares_bind_addresses_and_families(self):
        self.assertTrue(preflight.bindings_overlap('0.0.0.0', '127.0.0.1'))
        self.assertTrue(preflight.bindings_overlap('::', '::1'))
        self.assertTrue(preflight.bindings_overlap('::', '127.0.0.1'))
        self.assertTrue(preflight.bindings_overlap('127.0.0.1', '127.0.0.1'))
        self.assertFalse(preflight.bindings_overlap('127.0.0.1', '127.0.0.2'))
        self.assertFalse(preflight.bindings_overlap('127.0.0.1', '::1'))

    def test_preflight_reads_docker_and_podman_port_bindings(self):
        docker = {'NetworkSettings': {'Ports': {'8337/tcp': [
            {'HostIp': '0.0.0.0', 'HostPort': '8337'},
            {'HostIp': '::', 'HostPort': '8337'}]}},
            'HostConfig': {'PortBindings': {'8337/tcp': [{'HostIp': '', 'HostPort': '0'}]}}}
        podman = {'HostConfig': {'PortBindings': {'8339/udp': [
            {'HostIp': '127.0.0.1', 'HostPort': '8339'}]}}}
        self.assertEqual(preflight.port_bindings(docker),
                         [('0.0.0.0', 8337, 'tcp'), ('::', 8337, 'tcp')])
        self.assertEqual(preflight.port_bindings(podman), [('127.0.0.1', 8339, 'udp')])
        self.assertEqual(preflight.display_address('', 8337), '0.0.0.0:8337')
        self.assertEqual(preflight.display_address('::', 8337), '[::]:8337')
        self.assertEqual(preflight.display_address('127.0.0.1', 8337), '127.0.0.1:8337')

    def test_preflight_allows_duplicate_port_on_different_protocols(self):
        config = {'services': {
            'teep': {'ports': [{'host_ip': '127.0.0.1', 'published': '9120', 'protocol': 'tcp'}]},
            'webapp-proxy': {'ports': [{'host_ip': '127.0.0.1', 'published': '9120', 'protocol': 'udp'}]}}}
        with patch.object(preflight.socket, 'socket'):
            preflight.check_published_ports('private-hermes', config, [])

    def test_preflight_rejects_an_unpinned_network(self):
        with patch.object(preflight, 'engine', return_value='docker'), self.assertRaises(SystemExit) as raised:
            preflight.check_pinned_networks({'networks': {'unpinned': {'driver_opts': {'x': 'y'}}}})
        message = str(raised.exception)
        self.assertIn('no pinned subnet', message)
        self.assertIn('compose.funnel.yaml', message)
        self.assertIn('default-address-pools', message)
        preflight.check_pinned_networks({'networks': {'external': {'external': True}}})
        preflight.check_pinned_networks({'networks': {
            'pinned': {'ipam': {'config': [{'subnet': '10.0.0.0/24'}]}}}})

    def test_preflight_ignores_unpublished_container_ports(self):
        config = {'services': {'teep': {'ports': [
            {'host_ip': '127.0.0.1', 'target': 8337, 'published': '', 'protocol': 'tcp'}]}}}
        preflight.check_published_ports('private-hermes', config, [])

    def test_preflight_reads_docker_and_podman_network_subnets(self):
        docker = {'Name': 'other', 'Labels': {}, 'IPAM': {'Config': [{'Subnet': '10.203.83.0/24'}]}}
        podman = {'name': 'other', 'subnets': [{'subnet': '10.203.84.0/24', 'gateway': '10.203.84.1'}]}
        self.assertEqual([str(net) for net in preflight.subnets(docker)], ['10.203.83.0/24'])
        self.assertEqual([str(net) for net in preflight.subnets(podman)], ['10.203.84.0/24'])
        self.assertEqual(preflight.subnets({'Name': 'empty', 'IPAM': {'Config': None}}), [])


if __name__ == '__main__':
    unittest.main()
