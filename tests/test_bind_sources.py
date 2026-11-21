"""Required bind checks are scoped to the actual container creation."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import deployment


def mount(source, target='/input', required=True):
    return {'type': 'bind', 'source': str(source), 'target': target,
            'bind': {'create_host_path': not required}}


class BindSourceTests(unittest.TestCase):
    def check(self, services, arguments, command=None):
        with patch.object(deployment, '_output', return_value=json.dumps({'services': services})) as render:
            deployment.check_bind_sources(command or ['compose'], arguments)
            return render

    def test_existing_source_and_no_deps_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / 'absent'
            services = {'job': {'volumes': [mount(folder)]}, 'dependency': {'volumes': [mount(missing)]}}
            self.check(services, ['run', '--no-deps', 'job', 'echo', '-v', 'not-an-option'])
            with self.assertRaisesRegex(RuntimeError, 'dependency'):
                self.check(services, ['run', 'job'])
            self.assertFalse(missing.exists())

    def test_required_only_and_dangling_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'missing'
            self.check({'job': {'volumes': [mount(path, required=False)]}}, ['create', 'job'])
            link = Path(folder) / 'dangling'
            link.symlink_to(path)
            with self.assertRaisesRegex(RuntimeError, 'job'):
                self.check({'job': {'volumes': [mount(link)]}}, ['create', 'job'])

    def test_run_mount_override_replaces_target_only(self):
        with tempfile.TemporaryDirectory() as folder:
            services = {'job': {'volumes': [mount(Path(folder) / 'absent')]}}
            for override in (f'{folder}:/input:ro', 'saved:/input', '/input'):
                self.check(services, ['run', '-Tv', override, '--no-deps', 'job'])
            self.check(services, ['run', f'-Tv={folder}:/input:ro', '--no-deps', 'job'])
            with self.assertRaisesRegex(RuntimeError, 'missing'):
                self.check(services, ['run', '-v', f'{folder}/missing:/input', 'job'])
            services['dep'] = services['job']
            with self.assertRaisesRegex(RuntimeError, 'dep'):
                self.check(services, ['run', '-v', f'{folder}:/input', 'job'])

    def test_relative_run_bind_uses_compose_invocation_directory(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(deployment, 'ROOT', Path(folder)):
            (Path(folder) / 'present').mkdir()
            previous = Path.cwd()
            try:
                os.chdir('/')
                command = ['compose', '-f', '/other/compose.yaml', '--project-directory', '/wrong',
                           '--project-directory', '/also-wrong']
                self.check({'job': {}}, ['run', '-v./present:/input', 'job'], command)
                with self.assertRaisesRegex(RuntimeError, 'missing'):
                    self.check({'job': {}}, ['run', '--volume=./missing:/input', 'job'], command)
            finally:
                os.chdir(previous)

    def test_native_selection_and_option_operands(self):
        render = self.check({'job': {}}, ['up', '--wait-timeout', '42', '--scale=job=2', '-d', 'job'])
        self.assertEqual(render.call_args.args, ('compose', 'config', '--format', 'json', '--', 'job'))
        render = self.check({'--dry-run': {}}, ['run', '--', '--dry-run'])
        self.assertEqual(render.call_args.args[-2:], ('--', '--dry-run'))
        render = self.check({'job': {}}, ['scale', 'job=2'])
        self.assertEqual(render.call_args.args[-1], 'job')
        for arguments in (['watch'], ['up', '--watch'], ['future-create'], ['up', '--unknown', 'job'],
                          ['up', '--no-deps', '--always-recreate-deps', 'job']):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.check({}, arguments)

    def test_zero_scale_does_not_require_a_source(self):
        services = {'job': {'volumes': [mount('/missing-qualification-source')]}}
        self.check(services, ['scale', 'job=0'])
        self.check(services, ['up', '--scale', 'job=0', 'job'])
        services['job']['deploy'] = {'replicas': 0}
        self.check(services, ['create', 'job'])
        # Explicit positive scale overrides the saved zero and needs its bind.
        with self.assertRaisesRegex(RuntimeError, 'Required bind'):
            self.check(services, ['up', '--scale=job=1', 'job'])

    def test_no_deps_run_reuses_the_selected_model_for_network_preparation(self):
        services = {
            'job': {'network_mode': 'none', 'depends_on': {'dependency': {}}},
            'dependency': {'networks': {'bridge': {}}, 'volumes': [mount('/absent-qualification-input')]},
        }
        networks = {'bridge': {}}
        command = ['compose']
        launch = deployment.parse_launch(['run', '--no-deps', 'job'])
        with patch.object(deployment, '_output',
                          return_value=json.dumps({'services': services, 'networks': networks})) as render:
            model, networked = deployment.inspect_launch(command, launch)
            render.assert_called_once_with('compose', 'config', '--format', 'json', '--', 'job')
        self.assertTrue(networked)
        self.assertEqual(model['services'], {'job': services['job']})
        self.assertEqual(model['networks'], networks)

    def test_dry_run_validates_command_without_requiring_sources(self):
        with patch.object(deployment, '_output') as render:
            deployment.check_bind_sources(['compose'], ['up', 'job'], dry_run=True)
            render.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'Unsupported Compose creation'):
                deployment.check_bind_sources(['compose'], ['watch'], dry_run=True)

    def test_noncreating_operations_do_not_render_or_check_sources(self):
        for action in ('config', 'ps', 'exec', 'logs', 'build', 'down', 'stop', 'start', 'restart'):
            self.check({}, [action]).assert_not_called()
