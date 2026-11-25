"""Configuration, source admission, and Compose model checks for project mounts."""
import json
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import deployment
import project_mounts as projects
import stack


class ProjectMountTests(unittest.TestCase):
    def test_pairs_and_dollars(self):
        self.assertEqual(projects.parse_mounts(''), {})
        self.assertEqual(projects.parse_mounts('/host a/$$NAME$$$$:/mnt/projects/$$x,/host/b:/mnt/projects/b'),
                         {Path('/mnt/projects/$x'): Path('/host a/$NAME$$'),
                          Path('/mnt/projects/b'): Path('/host/b')})
        for invalid in ('relative:/mnt/projects/x', '/host:/mnt/projects', '/host:/workspace/x',
                        '/host:/mnt/projects/../x', '/host:/mnt/projects//x', '/host:/mnt/projects/x\n',
                        '/host:/mnt/projects/x"y',
                        '/host:/mnt/projects/x:ro', '/host:/mnt/projects/x,',
                        '/one:/mnt/projects/x,/two:/mnt/projects/x/y',
                        '/one:/mnt/projects/x,/two:/mnt/projects/x'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                projects.parse_mounts(invalid)

    def test_sidecar_model_and_dollar_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'project $x'
            source.mkdir()
            target = '/mnt/projects/nested/$x \U0001f680'
            mounts = {Path(target): source}
            with projects.project_override(mounts, root) as extra:
                override = Path(extra[0])
                serialized = override.read_text(encoding='utf-8')
                self.assertIn(target.replace('$', '$$'), serialized)
                model = json.loads(serialized)
                self.assertEqual(override.parent.stat().st_mode & 0o777, 0o700)
                projects.check_project_model(model, mounts)
                project = model['services']['executor']['volumes'][0]
                legacy = {'services': {'executor': {
                    'restart': 'no', 'volumes': [{**project, 'bind': {'recursive': 'disabled'}}]}}}
                projects.check_project_model(legacy, mounts)
                with self.assertRaisesRegex(RuntimeError, 'automatic executor restart'):
                    projects.check_project_model({'services': {'executor': {'restart': 'unless-stopped'}}}, mounts)
                for key, value in (('type', 'volume'), ('read_only', True),
                                   ('bind', {'create_host_path': True, 'recursive': 'disabled'}),
                                   ('bind', {'recursive': 'enabled'})):
                    bad = {'services': {'executor': {'restart': 'no', 'volumes': [{**project, key: value}]}}}
                    with self.assertRaises(RuntimeError):
                        projects.check_project_model(bad, mounts)
                for service in ('setup', 'hermes', 'executor-net'):
                    with self.assertRaisesRegex(RuntimeError, service):
                        projects.check_project_model({'services': {
                            **model['services'], service: model['services']['executor']}}, mounts)
                source.rmdir()
                with patch.object(deployment, '_output', return_value=json.dumps(model)):
                    with self.assertRaisesRegex(RuntimeError, 'Required bind source missing'):
                        deployment.check_bind_sources(['compose'], ['up', 'executor'])
                self.assertFalse(source.exists())
                source.mkdir()
                with patch.object(deployment, '_output', return_value=json.dumps(model)):
                    deployment.check_bind_sources(['compose'], ['up', 'executor'])
                self.assertTrue(override.exists())
            self.assertFalse(override.exists())

    def test_projects_must_be_outside_deployment_and_each_other(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp' if sys.platform == 'darwin' else None) as directory:
            root = Path(directory).resolve()
            deployment_root = root / 'deployment'
            deployment_root.mkdir()
            allowed = root / 'project'
            allowed.mkdir()
            child = allowed / 'child'
            child.mkdir()
            protected = root / 'alias'
            protected.symlink_to(deployment_root)
            mounts = (projects.Mount('1:1', Path('/'), Path('/'), 'ext4'),)
            first, second = Path('/mnt/projects/first'), Path('/mnt/projects/second')
            validate = lambda sources: projects.validate_sources(sources, deployment_root, (mounts,), (), ())[0]
            self.assertEqual(validate({first: allowed}), {first: allowed})
            controls = root / 'tools'
            controls.mkdir()
            (deployment_root / 'config').symlink_to(controls)
            with self.assertRaisesRegex(ValueError, 'overlaps'):
                validate({first: controls})
            (deployment_root / 'config').unlink()
            base_model = {'services': {'setup': {'volumes': [
                {'source': str(controls), 'type': 'bind', 'target': '/controls'}]}}}
            binds = projects.bind_sources(base_model)
            with self.assertRaisesRegex(ValueError, 'overlaps'):
                projects.validate_sources({first: controls}, deployment_root, (mounts,), binds, ())
            webapp = deployment_root / 'config/webapp'
            webapp.mkdir(parents=True)
            (webapp / 'password').symlink_to(controls / 'link')
            (controls / 'link').symlink_to(root / 'password')
            with self.assertRaisesRegex(ValueError, 'overlaps'):
                validate({first: controls})
            with patch.dict('os.environ', {'PATH': str(controls)}):
                with self.assertRaisesRegex(ValueError, 'overlaps'):
                    validate({first: controls})
            with patch.object(sys, 'path', [*sys.path, str(controls)]):
                with self.assertRaisesRegex(ValueError, 'overlaps'):
                    validate({first: controls})
            for bad in (protected, root, root / 'missing'):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    validate({first: bad})
            with self.assertRaisesRegex(ValueError, 'overlaps'):
                validate({first: child, second: allowed})
            with self.assertRaisesRegex(ValueError, 'overlaps'):
                validate({first: allowed, second: child})
            regular = allowed / 'file'
            regular.touch()
            with self.assertRaisesRegex(ValueError, 'must be a directory'):
                validate({first: regular})

    def test_linux_mount_aliases_and_different_service_view(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp' if sys.platform == 'darwin' else None) as directory:
            root = Path(directory).resolve()
            deploy, project = root / 'deploy', root / 'project'
            protected = deploy / 'separate'
            nested = project / 'nested'
            alternate = root / 'alternate'
            source = alternate / 'child'
            for path in (protected, nested, source):
                path.mkdir(parents=True)
            base = projects.Mount('1:1', Path('/'), Path('/'), 'ext4')
            private = projects.Mount('1:2', Path('/'), protected, 'ext4')
            nested_alias = projects.Mount('1:2', Path('/'), nested, 'ext4')
            other_alias = projects.Mount('1:2', Path('/'), alternate, 'ext4')
            target = Path('/mnt/projects/test')
            for requested in (source, project):
                with self.subTest(requested=requested), self.assertRaises(ValueError):
                    projects.validate_sources({target: requested}, deploy,
                                              ((base, private, nested_alias, other_alias),), (), ())
            foreign = projects.Mount('1:3', Path('/'), project, 'ext4')
            with self.assertRaisesRegex(ValueError, 'different filesystem view'):
                projects.validate_sources({target: project}, deploy, ((base,), (base, foreign)), (), ())
            # The project itself resolves identically in both views. The
            # protected bind alias exists only in the engine mount table.
            engine_view = (base, projects.Mount('1:1', project, protected, 'ext4'))
            with self.assertRaisesRegex(ValueError, 'aliases a protected'):
                projects.validate_sources({target: project}, deploy, ((base,), engine_view), (), ())

    def test_source_resolves_to_path_with_separator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            link = root / 'project'
            for name in ('project,comma', 'project:colon', 'project"quote', 'project\nnewline'):
                with self.subTest(name=name):
                    source = root / name
                    source.mkdir()
                    link.symlink_to(source)
                    try:
                        with self.assertRaisesRegex(ValueError, 'resolved source contains an unsupported character'):
                            projects.source_directory(link)
                    finally:
                        link.unlink()

    def test_socket_or_fifo_is_not_an_ordinary_project_entry(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            os.mkfifo(source / 'fifo')
            with self.assertRaisesRegex(ValueError, 'special file'):
                projects.check_project_entries(source)

    def test_directory_replacement_changes_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory).resolve() / 'project'
            source.mkdir()
            mounts = {Path('/mnt/projects/p'): source}
            original = projects.source_ids(mounts)
            source.rename(source.with_name('moved'))
            with self.assertRaisesRegex(ValueError, 'source is missing'):
                projects.source_ids(mounts)
            source.mkdir()
            self.assertNotEqual(projects.source_ids(mounts), original)

    def test_missing_control_below_a_directory_alias_is_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, alias = root / 'project', root / 'alternate'
            source.mkdir()
            alias.symlink_to(source)
            self.assertTrue(projects.aliases(projects.identities(source), alias / 'missing'))

    def test_docker_uses_cli_context_resolution_and_rejects_remote(self):
        home = Path.home()
        with patch.object(projects, 'output', return_value='ssh://example.invalid') as output:
            with self.assertRaisesRegex(RuntimeError, 'local Docker'):
                projects.docker_socket(home, 'darwin')
            output.assert_called_once_with('docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}')
        socket = home / '.docker/run/docker.sock'
        with patch.object(projects, 'output', return_value='unix://' + str(socket)):
            self.assertEqual(projects.docker_socket(home, 'darwin'), socket.resolve())

    def test_selected_podman_provider_is_protected_even_when_outside_path(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ'):
            root = Path(directory).resolve()
            executable = root / 'compose-provider'
            executable.touch(mode=0o700)
            alias = root / 'provider-link'
            alias.symlink_to(executable)
            absent = root / 'first-choice'
            debug = ('Error looking up compose provider "$HOME/first-choice": exec: ' +
                     json.dumps(str(absent)) + ': not found')
            warning = ('level=debug msg=' + json.dumps(debug) + '\n>>>> Executing external compose provider ' +
                       json.dumps(str(alias)) + '. Please see ...')
            provider, preceding = projects.podman_compose_provider(warning)
            self.assertEqual((provider, preceding), (alias, absent))
            self.assertEqual(projects.os.environ['PODMAN_COMPOSE_PROVIDER'], str(alias))
            self.assertEqual(projects.control_locations(provider), {alias, executable})

    def test_docker_on_linux_checks_the_host_mount_table_only(self):
        socket = Path('/run/docker.sock')
        mountinfo = '10 1 8:1 / / rw - ext4 /dev/vda1 rw\n'
        info = {'OperatingSystem': 'Docker Desktop', 'SecurityOptions': [], 'DockerRootDir': '/docker/graph',
                'Runtimes': {'custom': {'path': '/custom/runtime'}, 'runc': {'path': 'runc'},
                             'io.containerd.runc.v2': {}}}
        with patch.object(projects.sys, 'platform', 'linux'), patch.dict('os.environ'), \
                patch.object(projects, 'docker_socket', return_value=socket), \
                patch.object(projects, 'output', return_value=json.dumps(info)) as output, \
                patch.object(projects, 'docker_config_paths', return_value=()), \
                patch.object(projects, 'linux_socket_peer') as peer, \
                patch.object(projects, 'process_mounts', side_effect=AssertionError('daemon mount probe')), \
                patch.object(Path, 'read_text', autospec=True, return_value=mountinfo) as read, \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('daemon command line probe')):
            views, protected, _ = projects.engine_views('docker', Path('/home/operator'))
        self.assertEqual(views, (projects.linux_mounts(mountinfo),))
        self.assertEqual(set(protected), {socket, Path('/docker/graph'), Path('/custom/runtime'),
                                          Path('/var/lib/containerd'), Path('/run/containerd')})
        output.assert_called_once_with('docker', 'info', '--format', '{{json .}}')
        peer.assert_called_once_with(socket, 'Docker', 0)
        read.assert_called_once_with(Path('/proc/self/mountinfo'))

    def test_podman_protects_paths_reported_by_the_api_and_cli(self):
        socket = Path('/run/user/71/podman/podman.sock')
        local = {'host': {'security': {'rootless': True}, 'remoteSocket': {'path': str(socket)},
                          'conmon': {'path': '/local/conmon'}},
                 'store': {'graphRoot': '/local/graph', 'runRoot': '/local/run',
                           'volumePath': '/local/volumes', 'configFile': '/local/storage.conf'}}
        remote = {
            'host': {'security': {'rootless': True}, 'ociRuntime': {'path': '/api/runtime'},
                     'networkBackendInfo': {'path': '/api/netavark', 'dns': {'path': '/api/dns'}},
                     'pasta': {'executable': '/api/pasta'}, 'slirp4netns': {'executable': '/api/slirp'}},
            'store': {'graphRoot': '/api/graph', 'runRoot': '/api/run', 'volumePath': '/api/volumes',
                      'graphOptions': {'overlay.additionalImageStores': ['/api/images'],
                                       'overlay.mount_program': {'Executable': '/api/mount-helper'}}}}
        with patch.object(projects.sys, 'platform', 'linux'), patch.object(projects.os, 'getuid', return_value=71), \
                patch.object(projects, 'check_engine', return_value=(local, '')), \
                patch.object(projects, 'output', return_value=json.dumps(remote)), \
                patch.object(projects, 'podman_compose_provider', return_value=()), \
                patch.object(projects, 'linux_service_pid'), patch.object(projects, 'process_mounts'), \
                patch.object(Path, 'read_text', return_value=''):
            _, protected, _ = projects.engine_views('podman', Path('/home/operator'))
        expected = ('/local/graph', '/local/run', '/local/volumes', '/local/storage.conf', '/local/conmon',
                    '/api/graph', '/api/run', '/api/volumes', '/api/images', '/api/mount-helper',
                    '/api/runtime', '/api/netavark', '/api/dns', '/api/pasta', '/api/slirp')
        self.assertEqual(set(protected), {socket, *map(Path, expected)})

    def test_docker_extra_plugin_search_paths_include_empty_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            extra = root / 'empty directory'
            config = root / 'config.json'
            config.write_text(json.dumps({'cliPluginsExtraDirs': [str(extra)]}))
            with patch.dict('os.environ', {'DOCKER_CONFIG': str(root)}):
                self.assertEqual(projects.docker_config_paths(root), (config, extra))

    def test_docker_desktop_protects_a_relocated_vm_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / 'Library/Group Containers/group.com.docker/settings-store.json'
            settings.parent.mkdir(parents=True)
            disk = home / 'engine disk'
            settings.write_text(json.dumps({'DataFolder': str(disk)}))
            self.assertEqual(list(projects.docker_desktop_storage(home)), [disk])

    def test_git_global_config_and_includes_are_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'global'
            missing = root / 'project/missing.gitconfig'
            config.write_text('[include]\npath = ' + str(missing) + '\n')
            with patch.dict('os.environ', {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_NOSYSTEM': '1'}):
                self.assertIn(missing, projects.git_config_paths(root))
                self.assertIn(config, projects.git_config_paths(root))
                self.assertIn(config.resolve(), projects.protected_paths(root, root, ()))
            xdg = root / 'xdg'
            (xdg / 'git').mkdir(parents=True)
            (xdg / 'git/config').symlink_to(missing)
            credentials = root / 'project/credentials'
            (xdg / 'git/credentials').symlink_to(credentials)
            with patch.dict('os.environ', {'XDG_CONFIG_HOME': str(xdg)}):
                protected = projects.protected_paths(root, root, ())
                self.assertTrue(missing.resolve() in protected)
                self.assertTrue(credentials.resolve() in protected)

    def test_deployment_git_hooks_are_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            deploy, hooks = root / 'deployment', root / 'project hooks '
            deploy.mkdir()
            hooks.mkdir()
            with patch.dict('os.environ', {'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}):
                git = ['git', '-C', str(deploy)]
                subprocess.run([*git, 'init', '-q', '--template='], check=True)
                mounts = (projects.Mount('1:1', Path('/'), Path('/'), 'ext4'),)
                share = {Path('/mnt/projects/test'): hooks}
                subprocess.run([*git, 'config', 'core.hooksPath', f'../{hooks.name}'], check=True)
                with self.assertRaisesRegex(ValueError, 'overlaps a protected'):
                    projects.validate_sources(share, deploy, (mounts,), (), ())
                subprocess.run([*git, 'config', '--unset', 'core.hooksPath'], check=True)
                default_hooks = deploy / '.git/hooks'
                default_hooks.symlink_to(hooks)
                with self.assertRaisesRegex(ValueError, 'overlaps a protected'):
                    projects.validate_sources(share, deploy, (mounts,), (), ())
                default_hooks.unlink()
                default_hooks.mkdir()
                (default_hooks / 'post-merge').symlink_to(hooks / 'post-merge')
                with self.assertRaisesRegex(ValueError, 'overlaps a protected'):
                    projects.validate_sources(share, deploy, (mounts,), (), ())
                (default_hooks / 'post-merge').unlink()
                subprocess.run([*git, 'config', 'core.fsmonitor', str(hooks / 'fsmonitor')], check=True)
                with self.assertRaisesRegex(ValueError, 'overlaps a protected'):
                    projects.validate_sources(share, deploy, (mounts,), (), ())
                subprocess.run([*git, 'config', '--unset', 'core.fsmonitor'], check=True)
                with patch.dict('os.environ', {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.fsmonitor',
                                               'GIT_CONFIG_VALUE_0': str(hooks / 'fsmonitor')}):
                    with self.assertRaisesRegex(ValueError, 'overlaps a protected'):
                        projects.validate_sources(share, deploy, (mounts,), (), ())

    def test_mount_changes_require_shutdown(self):
        mounts = {Path('/mnt/projects/p'): Path('/source')}
        original = [self.bind('/mnt/projects/p'), self.bind('/workspace')]
        with patch.object(stack, 'capture', side_effect=['abc', json.dumps(original)]):
            stack.require_same_project_mounts(['compose'], mounts)
        with patch.object(stack, 'capture', side_effect=['abc', json.dumps([self.bind('/workspace')])]):
            with self.assertRaisesRegex(ValueError, 'make down'):
                stack.require_same_project_mounts(['compose'], mounts)

    @staticmethod
    def bind(destination):
        return {'Destination': destination, 'Source': '/source', 'Type': 'bind', 'RW': True}

    def test_read_applied_destinations_without_widening_nested_paths(self):
        nested = '/mnt/projects/parent/name ${NAME} $$'
        volumes = [self.bind(path) for path in ('/workspace', nested, '/mnt/projects-other')]
        with patch.object(stack, 'capture', return_value=json.dumps(volumes)):
            self.assertEqual(stack.executor_roots(stack.attached_project_mounts('abc')),
                             ['/workspace', nested])
        with patch.object(stack, 'capture', return_value=json.dumps([self.bind('/workspace')])):
            self.assertEqual(stack.executor_roots(stack.attached_project_mounts('abc')),
                             ['/workspace'])
        for malformed in (None, [], [*volumes, self.bind('/mnt/projects')], [*volumes, self.bind(nested)],
                          [*volumes, self.bind('/mnt/projects/parent//other')],
                          [*volumes, dict(self.bind('/mnt/projects/other'), RW=False)]):
            with self.subTest(malformed=malformed), patch.object(stack, 'capture', return_value=json.dumps(malformed)):
                with self.assertRaisesRegex(RuntimeError, 'verify the executor mounts'):
                    stack.attached_project_mounts('abc')

    def test_chat_uses_running_gateway_settings_and_attached_roots(self):
        root = '/mnt/projects/nested/with space ${NAME}'
        entries = ['WEBAPP_TERMINAL_ENVIRONMENT=code', 'WEBAPP_EXTERNAL_CONTENT=ask', 'COMPUTER_USE_ENABLED=true',
                   f'{stack.EXECUTOR_ROOTS}={json.dumps(["/workspace", root])}']
        with patch.object(stack, 'maintenance_compose', return_value=['docker', 'compose']), \
                patch.object(stack, 'check_engine'), patch.object(stack, 'running_service', side_effect=['gateway', 'executor']), \
                patch.object(stack, 'attached_project_mounts', return_value={root: '/private/source'}), \
                patch.object(stack, 'capture', return_value=json.dumps(entries)), \
                patch.object(stack, 'inspect_launch', return_value=({'services': {}}, True)), \
                patch.object(stack, 'prepare_launch') as prepare, patch.object(stack, 'run') as run:
            stack.start_chat(['--in', root])
            command = run.call_args.args[0]
            self.assertEqual(command[:5], ['env', *entries])
            self.assertEqual(command[-7:], ['run', '--rm', '--no-deps', 'hermes', 'chat', '--in', root])
            self.assertNotIn('/private/source', repr(command))
            prepare.assert_called_once()

    def test_chat_refuses_missing_or_mismatched_gateway_policy(self):
        entries = ['WEBAPP_TERMINAL_ENVIRONMENT=code', 'WEBAPP_EXTERNAL_CONTENT=ask', 'COMPUTER_USE_ENABLED=false']
        for policy in ([], [f'{stack.EXECUTOR_ROOTS}=["/workspace", "/mnt/projects/other"]'],
                       [f'{stack.EXECUTOR_ROOTS}=null']):
            with self.subTest(policy=policy), patch.object(stack, 'maintenance_compose', return_value=['compose']), \
                    patch.object(stack, 'check_engine'), patch.object(stack, 'running_service', side_effect=['gateway', 'executor']), \
                    patch.object(stack, 'attached_project_mounts', return_value={}), \
                    patch.object(stack, 'capture', return_value=json.dumps(entries + policy)), patch.object(stack, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'verify the applied chat settings'):
                    stack.start_chat()
                run.assert_not_called()

    def test_running_service_requires_exactly_one_running_container(self):
        for result in (['abc', 'paused'], ['abc', 'restarting'], [''], ['abc\ndef']):
            with self.subTest(result=result), patch.object(stack, 'capture', side_effect=result):
                with self.assertRaisesRegex(RuntimeError, 'running hermes service'):
                    stack.running_service(['compose'], 'hermes')

    def test_invalid_setting_blocks_managed_startup_only(self):
        configuration = SimpleNamespace(executor_bind_mounts='broken')
        with patch.object(stack, 'settings', return_value=(configuration, [])) as settings, \
                patch.object(stack, 'run') as run, patch.object(stack, 'check_engine') as check_engine, \
                patch.object(stack, 'maintenance_compose', return_value=['compose']), \
                patch.object(stack, 'stop_funnel'), patch.object(stack, 'remove_networks'):
            with patch.object(sys, 'argv', ['stack.py', 'up']):
                with self.assertRaisesRegex(ValueError, 'absolute host:executor'):
                    stack.main_unlocked()
            run.assert_not_called()
            check_engine.assert_not_called()
            settings.reset_mock()
            for action in ('down', 'build'):
                with patch.object(sys, 'argv', ['stack.py', action]):
                    stack.main_unlocked()
            settings.assert_not_called()

    def test_startup_stops_if_a_source_disappears_during_build(self):
        config = SimpleNamespace(teep=False, funnel=False)
        with tempfile.TemporaryDirectory() as folder, ExitStack() as patches:
            root = Path(folder).resolve()
            auth = root / 'config/webapp/auth.json'
            auth.parent.mkdir(parents=True)
            auth.write_text('{}')
            source = root / 'project'
            source.mkdir()
            target = Path('/mnt/projects/p')
            mounts = {target: source}
            original_sources = projects.source_ids(mounts)
            model = {'services': {'executor': {'restart': 'no', 'volumes': [
                {'type': 'bind', 'source': str(source), 'target': str(target),
                 'bind': {'create_host_path': False}}]}}}
            patches.enter_context(patch.object(stack, 'ROOT', root))
            for name in ('require_same_project_mounts', 'run_preflight', 'validate', 'render',
                         'stop_funnel', 'initialize_research_config', 'report_research_config_diff',
                         'initialize_setup', 'prepare_launch', 'compose'):
                patches.enter_context(patch.object(stack, name))
            patches.enter_context(patch.object(deployment, '_output', return_value=json.dumps(model)))
            build = patches.enter_context(patch.object(stack, 'run', side_effect=lambda command: source.rmdir()))
            with self.assertRaisesRegex(RuntimeError, 'Required bind source missing'):
                stack.start_stack(config, [], ['compose'], mounts, original_sources)
            self.assertEqual(build.call_count, 1)
            self.assertIn('build', build.call_args.args[0])
            self.assertFalse(source.exists())


if __name__ == '__main__':
    unittest.main()
