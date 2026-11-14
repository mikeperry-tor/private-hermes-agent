"""Exercise staged activation and financial-command failure paths without money."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'components/x402_treazury'))
spec = importlib.util.spec_from_file_location('onboarding', ROOT / 'components/x402_treazury/onboarding.py')
onboarding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(onboarding)
sys.path.insert(0, str(ROOT / 'scripts'))
from x402_treazury import Controller, operation_lock
from endpoints import ADDRESS, ENDPOINTS


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = Path(self.folder.name)
        self.state = self.home / 'state'
        self.state.mkdir()
        (self.state / 'wallet.key').write_text('unfunded test placeholder')
        self.config = {'treasury': {'state_dir': str(self.state)}, 'sources': {'a': {}, 'b': {}},
                       'network': {'mode': 'tor', 'socks_endpoint': 'unix:/run/tor-x402_treazury/socks', 'socks_auth': 'tor_extended'},
                       'servers': {name: {'listen': f'{ADDRESS}:{port}', 'allowed_hosts': [ADDRESS],
                                          'auth': True, 'disable_host_check': False,
                                          'bearer_token_env': 'X402_TREAZURY_MCP_TOKEN'}
                                   for name, port in ENDPOINTS.items()}}
        self.calls = []
        self.fail = None
        self.treasury_id = 'test-treasury-identity'
        self.build_revision = 'test-source'
        self.native_patch = patch.object(onboarding, 'native', side_effect=self.native)
        self.native_patch.start()
        self.addCleanup(self.native_patch.stop)
        for key, value in (('HOME', self.home), ('RECORD', self.home / 'onboarding/preparation.json')):
            mocked = patch.object(onboarding, key, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def native(self, args, phase, **kwargs):
        self.calls.append(args)
        if phase == self.fail:
            raise onboarding.PhaseError(phase, 17, 'native operation failed')
        if args == ['config', 'show']:
            return self.config
        if args == ['build-info']:
            return {'source_revision': self.build_revision, 'source_dirty': False}
        if args == ['wallet', 'status', '--json']:
            return {'treasury_id': self.treasury_id}
        if args == ['wallet', 'addresses']:
            return {'receive_addresses': [{'encoded_address': 'test-address'}]}
        if args == ['wallet', 'bootstrap', '--json']:
            return {'schema_version': 3, 'captured_completed_groups': ['general'],
                    'incomplete_captured_jobs': [], 'balance_estimates': []}
        if args == ['catalog', 'warm']:
            return {'direct': False, 'outcome': 'ok', 'sources': [
                {'source': n, 'status': 'ready', 'catalog_cache': 'fresh'} for n in self.config['sources']]}
        if args == ['wallet', 'init']:
            self.state.mkdir()
            (self.state / 'wallet.key').write_text('test-only key placeholder')

    def test_complete_sequence_record_and_identity_binding(self):
        onboarding.prepare()
        self.assertTrue(onboarding.inspect()['prepared'])
        self.assertLess(self.calls.index(['wallet', 'bootstrap', '--json']), self.calls.index(['catalog', 'warm']))
        self.assertEqual(onboarding.RECORD.stat().st_mode & 0o777, 0o600)
        self.assertEqual(onboarding.RECORD.parent.stat().st_mode & 0o777, 0o700)
        self.treasury_id = 'different-wallet'
        self.assertFalse(onboarding.inspect()['prepared'])

    def test_successful_native_output_is_diagnostic_not_completion_authority(self):
        original = self.native
        def changed(args, phase, **kwargs):
            if phase in ('bootstrap', 'catalogs'):
                self.calls.append(args)
                return 'changed native presentation'
            return original(args, phase, **kwargs)
        with patch.object(onboarding, 'native', side_effect=changed):
            onboarding.prepare()
        self.assertTrue(onboarding.inspect()['prepared'])
        self.assertNotIn('result', json.loads(onboarding.RECORD.read_text()))

    def test_degraded_warming_completes_even_with_every_source_unavailable(self):
        original = self.native
        def degraded(args, phase, **kwargs):
            if phase == 'catalogs':
                self.calls.append(args)
                self.assertFalse(kwargs.get('structured', False))
                return {'direct': False, 'outcome': 'degraded', 'sources': [
                    {'source': n, 'status': 'unavailable', 'failure': {
                        'stage': 'headers', 'reason': 'connection_failed',
                        'message': 'Could not connect to the catalog server or configured proxy'}}
                    for n in self.config['sources']]}
            return original(args, phase, **kwargs)
        with patch.object(onboarding, 'native', side_effect=degraded):
            onboarding.prepare()
        self.assertTrue(onboarding.inspect()['prepared'])
        self.assertEqual(onboarding.inspect()['record']['completed'], ['bootstrap', 'catalogs'])
        self.assertEqual(self.calls.count(['wallet', 'bootstrap', '--json']), 1)

    def test_implementation_changes_preserve_completion_and_serving(self):
        onboarding.prepare()
        record = onboarding.RECORD.read_bytes()
        self.build_revision = 'different-source'
        with patch.object(onboarding, '__file__', '/unrelated/new/coordinator.py'):
            self.assertTrue(onboarding.inspect()['prepared'])
            onboarding.serve()
        self.assertEqual(onboarding.RECORD.read_bytes(), record)
        self.assertNotIn(['build-info'], self.calls)
        self.assertIn(['serve'], self.calls)

    def test_absent_wrong_and_incomplete_completion_refuse_serving(self):
        for record in ({}, {'schema': 1, 'treasury_id': 'other', 'completed': ['bootstrap', 'catalogs']},
                       {'schema': 1, 'treasury_id': self.treasury_id, 'completed': ['bootstrap']}):
            onboarding.write_record(record)
            with self.assertRaises(RuntimeError):
                onboarding.serve()
        self.assertNotIn(['serve'], self.calls)

    def test_unreadable_runtime_config_does_not_block_saved_wallet(self):
        onboarding.prepare()
        self.fail = 'configuration'
        self.assertTrue(onboarding.inspect()['prepared'])
        with patch.object(sys, 'argv', ['onboarding.py', 'status']):
            onboarding.main()
        with self.assertRaises(onboarding.PhaseError):
            onboarding.serve()

    def test_policy_changes_allow_native_serving_but_corrupt_record_does_not(self):
        onboarding.prepare()
        self.config['sources']['new-source'] = {}
        self.assertTrue(onboarding.inspect()['prepared'])
        onboarding.serve()
        self.assertIn(['serve'], self.calls)
        onboarding.RECORD.write_text('{invalid')
        self.calls.clear()
        with self.assertRaises(RuntimeError):
            onboarding.serve()
        self.assertNotIn(['serve'], self.calls)
        self.assertFalse(onboarding.inspect()['prepared'])

    def test_each_failure_stops_later_phases_and_retry_keeps_wallet(self):
        for phase, completed in (('bootstrap', []), ('catalogs', ['bootstrap'])):
            self.calls.clear()
            self.fail = phase
            with self.assertRaises(onboarding.PhaseError):
                onboarding.prepare()
            record = json.loads(onboarding.RECORD.read_text())
            self.assertEqual(record['completed'], completed)
            self.assertEqual(record['failure']['exit_code'], 17)
            self.assertFalse(onboarding.inspect()['prepared'])
            self.assertNotIn(['serve'], self.calls)
            if phase == 'bootstrap':
                self.assertNotIn(['catalog', 'warm'], self.calls)
        self.fail = None
        onboarding.prepare()
        self.assertTrue(onboarding.inspect()['prepared'])
        self.assertEqual((self.state / 'wallet.key').read_text(), 'unfunded test placeholder')

    def test_partial_state_and_unreadable_key_never_trigger_init(self):
        (self.state / 'wallet.key').unlink()
        with self.assertRaises(RuntimeError):
            onboarding.initialize()
        self.assertNotIn(['wallet', 'init'], self.calls)
        (self.state / 'wallet.key').write_text('test-only key')
        self.fail = 'wallet addresses'
        with self.assertRaises(onboarding.PhaseError):
            onboarding.initialize()
        self.assertNotIn(['wallet', 'init'], self.calls)

    def test_absent_wallet_is_created_once_and_repeated_init_displays_status(self):
        (self.state / 'wallet.key').unlink()
        self.state.rmdir()
        onboarding.initialize()
        onboarding.initialize()
        self.assertEqual(self.calls.count(['wallet', 'init']), 1)
        self.assertIn(['wallet', 'status'], self.calls)

    def test_status_works_with_owner_and_invalid_state_is_not_inspected_twice(self):
        with onboarding.owner(), patch.object(sys, 'argv', ['onboarding.py', 'status']):
            onboarding.main()
        self.assertIn(['wallet', 'status'], self.calls)
        self.calls.clear()
        self.fail = 'wallet addresses'
        with patch.object(sys, 'argv', ['onboarding.py', 'status']), self.assertRaises(RuntimeError):
            onboarding.main()
        self.assertEqual(self.calls.count(['wallet', 'addresses']), 1)
        self.assertNotIn(['wallet', 'status'], self.calls)

    def test_absent_status_does_not_create_wallet(self):
        (self.state / 'wallet.key').unlink()
        self.state.rmdir()
        with patch.object(sys, 'argv', ['onboarding.py', 'status']):
            onboarding.main()
        self.assertNotIn(['wallet', 'init'], self.calls)
        self.assertNotIn(['wallet', 'status'], self.calls)

    def test_init_failure_is_recorded_and_retry_preserves_later_preparation(self):
        (self.state / 'wallet.key').unlink()
        self.state.rmdir()
        self.fail = 'wallet creation'
        with self.assertRaises(onboarding.PhaseError):
            onboarding.initialize()
        self.assertEqual(onboarding.inspect()['record']['failure']['exit_code'], 17)
        self.assertTrue(onboarding.inspect()['wallet_absent'])
        self.fail = None
        onboarding.initialize()
        onboarding.prepare()
        onboarding.initialize()
        self.assertTrue(onboarding.inspect()['prepared'])
        self.assertEqual(self.calls.count(['wallet', 'init']), 2)

    def test_funding_and_wallet_policy_edits_preserve_preparation_without_storing_config(self):
        self.config['funding'] = {'near_api_key_env': 'TEST_PROVIDER_CREDENTIAL'}
        onboarding.prepare()
        self.assertTrue(onboarding.inspect()['prepared'])
        self.assertNotIn('TEST_PROVIDER_CREDENTIAL', onboarding.RECORD.read_text())
        self.config['funding']['near_api_key_env'] = 'OTHER_PROVIDER_CREDENTIAL'
        self.config['wallets'] = {'renamed': {'mode': 'zcash_rotation'}}
        self.config['servers']['web']['wallet'] = 'renamed'
        self.assertTrue(onboarding.inspect()['prepared'])

    def test_wallet_owner_and_host_operation_locks_refuse_competing_operations(self):
        with onboarding.owner(), self.assertRaises(RuntimeError):
            with onboarding.owner():
                pass
        with operation_lock(self.home), self.assertRaises(RuntimeError):
            with operation_lock(self.home):
                pass

    def test_lost_wallet_with_retained_identity_record_is_not_replaced(self):
        onboarding.prepare()
        (self.state / 'wallet.key').unlink()
        self.state.rmdir()
        with self.assertRaises(RuntimeError):
            onboarding.initialize()
        self.assertNotIn(['wallet', 'init'], self.calls)

    def test_direct_transport_is_rejected_before_any_wallet_operation(self):
        self.config['network']['mode'] = 'direct'
        with self.assertRaises(RuntimeError):
            onboarding.prepare()
        self.assertNotIn(['wallet', 'bootstrap', '--json'], self.calls)

    def test_forbidden_deployment_edits_refuse_serving_before_wallet_work(self):
        onboarding.prepare()
        mutations = (
            ('network', 'socks_endpoint', '127.0.0.1:9050'),
            ('network', 'socks_auth', 'none'),
            ('treasury', 'state_dir', '/tmp/new-wallet'),
            ('treasury', 'key_file', '/tmp/wallet.key'),
            ('server', 'listen', '0.0.0.0:3011'),
            ('server', 'allowed_hosts', ['example.com']),
            ('server', 'auth', False),
            ('server', 'disable_host_check', True),
            ('server', 'bearer_token_env', 'OTHER_TOKEN'),
        )
        for section, key, value in mutations:
            target = self.config['servers']['web'] if section == 'server' else self.config[section]
            with self.subTest(section=section, key=key), patch.dict(target, {key: value}):
                self.calls.clear()
                with self.assertRaises(RuntimeError):
                    onboarding.serve()
                self.assertNotIn(['serve'], self.calls)
                self.assertNotIn(['wallet', 'status', '--json'], self.calls)
                self.assertTrue(onboarding.inspect()['wallet_valid'])
                self.assertTrue(onboarding.inspect()['prepared'])
                with patch.object(sys, 'argv', ['onboarding.py', 'status']):
                    onboarding.main()
        with patch.dict(self.config['servers'], {'extra': {}}):
            self.assertTrue(onboarding.inspect()['prepared'])
            with self.assertRaises(RuntimeError):
                onboarding.serve()
        self.assertTrue(onboarding.inspect()['prepared'])

    def test_activation_failure_does_not_erase_completed_preparation(self):
        onboarding.prepare()
        with patch.object(sys, 'argv', ['onboarding.py', 'activation-failed']):
            onboarding.main()
        self.assertTrue(onboarding.inspect()['prepared'])
        self.assertEqual(onboarding.inspect()['record']['activation'], 'activation-failed')

    def test_failure_before_atomic_replace_cannot_publish_completion(self):
        with patch.object(Path, 'replace', side_effect=OSError('test interrupted write')):
            with self.assertRaises(OSError):
                onboarding.prepare()
        self.assertFalse(onboarding.RECORD.exists())


class NativeExecutionTests(unittest.TestCase):
    def test_success_streams_summary_and_coverage_diagnostics_without_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'native'
            executable.write_text('#!' + sys.executable + '\nimport sys\n'
                                  'print("native summary presentation")\n'
                                  'print("ERROR: source unavailable; coverage reduced",file=sys.stderr)\n')
            executable.chmod(0o700)
            with patch.object(onboarding, 'BINARY', str(executable)), \
                    contextlib.redirect_stdout(io.StringIO()) as stdout, \
                    contextlib.redirect_stderr(io.StringIO()) as stderr:
                onboarding.native(['catalog', 'warm'], 'catalogs')
            self.assertIn('native summary presentation', stdout.getvalue())
            self.assertIn('source unavailable; coverage reduced', stderr.getvalue())

    def test_failure_retains_native_exit_and_redacts_environment_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'native'
            executable.write_text('#!' + sys.executable + '\nimport os,sys\nprint(os.environ["TEST_API_KEY"],file=sys.stderr)\nsys.exit(19)\n')
            executable.chmod(0o700)
            with patch.object(onboarding, 'BINARY', str(executable)), patch.dict(os.environ, {'TEST_API_KEY': 'private-test-credential'}):
                with self.assertRaises(onboarding.PhaseError) as raised:
                    onboarding.native([], 'test failure', quiet=True)
            self.assertEqual(raised.exception.code, 19)
            self.assertIn('[redacted]', raised.exception.tail)
            self.assertNotIn('private-test-credential', raised.exception.tail)

    def test_signal_is_forwarded_and_child_completes_cleanup_without_force_kill(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            ready, cleaned = folder / 'ready', folder / 'cleaned'
            executable = folder / 'native'
            executable.write_text('#!' + sys.executable + '\nimport signal,time\nfrom pathlib import Path\n'
                                  'def stop(*args):\n Path(' + repr(str(cleaned)) + ').touch()\n raise SystemExit(0)\n'
                                  'signal.signal(signal.SIGTERM,stop)\nPath(' + repr(str(ready)) + ').touch()\n'
                                  'while True: time.sleep(.05)\n')
            executable.chmod(0o700)
            code = 'import sys; sys.path.insert(0,' + repr(str(ROOT / 'components/x402_treazury')) + '); import onboarding; onboarding.BINARY=' + repr(str(executable)) + '; onboarding.native([],"signal test")'
            parent = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                for _ in range(100):
                    if ready.exists():
                        break
                    time.sleep(.05)
                self.assertTrue(ready.exists())
                parent.send_signal(signal.SIGTERM)
                _, stderr = parent.communicate(timeout=10)
                self.assertTrue(cleaned.exists())
                self.assertIn(b'exit 143', stderr)
            finally:
                if parent.poll() is None:
                    parent.kill()
                    parent.wait()


class ActivationTests(unittest.TestCase):
    def setUp(self):
        seed = patch('x402_treazury.initialize_research_config')
        self.seed = seed.start()
        self.addCleanup(seed.stop)
        diff = patch('x402_treazury.report_research_config_diff')
        self.diff = diff.start()
        self.addCleanup(diff.stop)

    def controller(self):
        controller = Controller(['docker', 'compose'])
        controller.events = []
        controller.inspect = lambda: {'prepared': True}
        controller.configure = lambda mode: controller.events.append(('config', mode))
        controller.running = lambda service: 'test-container'
        controller.call = lambda *args, **kwargs: controller.events.append(args)
        controller.admin = lambda action: controller.events.append(('admin', action))
        controller.wallet_command = lambda action: controller.events.append(('wallet', action))
        controller.client = lambda action, **kwargs: controller.events.append(('client', action)) or subprocess.CompletedProcess([], 0)
        controller.wait_for_endpoints = lambda: controller.events.append(('client', 'probe')) or ('test-container', 'started', '0')
        controller.require_instance = lambda instance: None
        return controller

    def test_existing_init_only_displays_offline_status(self):
        controller = self.controller()
        controller.inspect = lambda: {'wallet_absent': False, 'wallet_valid': True}
        controller.initialize()
        self.assertEqual(controller.events, [('admin', 'status')])

    def test_absent_init_starts_network_but_invalid_state_does_not(self):
        controller = self.controller()
        controller.inspect = lambda: {'wallet_absent': True, 'wallet_valid': False}
        with patch('x402_treazury.subprocess.run'), patch('x402_treazury.initialize_research_config'):
            controller.initialize()
        self.assertEqual(controller.events, [('up', '-d', '--wait', '--no-deps', 'tor', 'agent-net'),
                                             ('wallet', 'init')])
        controller.events.clear()
        controller.inspect = lambda: {'wallet_absent': False, 'wallet_valid': False, 'reason': 'unreadable wallet'}
        with self.assertRaisesRegex(RuntimeError, 'unreadable wallet'):
            controller.initialize()
        self.assertEqual(controller.events, [])

    def test_prepare_disconnects_and_stops_owner_before_commands_then_connects(self):
        controller = self.controller()
        states = iter(({'prepared': False}, {'prepared': True}))
        controller.inspect = lambda: next(states)
        with patch('subprocess.check_output', return_value='0'):
            controller.prepare()
        events = controller.events
        self.assertEqual(events[0], ('build', 'x402_treazury'))
        self.assertLess(events.index(('config', 'disconnect')), events.index(('wallet', 'prepare')))
        self.assertLess(events.index(('stop', '--timeout', '-1', 'x402_treazury')), events.index(('wallet', 'prepare')))
        self.assertLess(events.index(('client', 'probe')), events.index(('config', 'connect')))
        self.assertIn(('client', 'reload'), events)
        self.assertNotIn(('restart', 'hermes'), events)

    def test_failed_preparation_never_starts_or_connects_serve(self):
        controller = self.controller()
        controller.inspect = lambda: {'prepared': False}
        controller.wallet_command = lambda action: (_ for _ in ()).throw(RuntimeError('phase failed'))
        with self.assertRaises(RuntimeError):
            controller.prepare()
        self.assertNotIn(('config', 'connect'), controller.events)
        self.assertNotIn(('up', '-d', '--no-deps', 'x402_treazury'), controller.events)

    def test_invalid_runtime_policy_preserves_history_and_existing_connections(self):
        for prepared in (False, True):
            controller = self.controller()
            controller.inspect = lambda: {'prepared': prepared}
            controller.admin = lambda action: (_ for _ in ()).throw(RuntimeError('invalid runtime policy'))
            with self.assertRaisesRegex(RuntimeError, 'invalid runtime policy'):
                controller.prepare()
            self.assertEqual(controller.events, [('build', 'x402_treazury')])

    def test_failed_build_leaves_serving_and_preparation_untouched(self):
        controller = self.controller()
        controller.inspect = lambda: self.fail('Build failure must precede wallet inspection')
        def failed(*args, **kwargs):
            controller.events.append(args)
            raise subprocess.CalledProcessError(1, ['docker', 'compose', *args])
        controller.call = failed
        with self.assertRaises(subprocess.CalledProcessError):
            controller.prepare()
        self.assertEqual(controller.events, [('build', 'x402_treazury')])
        self.seed.assert_not_called()

    def test_prepare_entrypoint_builds_before_seeding_missing_policy(self):
        import x402_treazury
        for fail in (False, True):
            with self.subTest(build_fails=fail):
                controller = self.controller()
                def build(*args, **kwargs):
                    controller.events.append(args)
                    if fail:
                        raise subprocess.CalledProcessError(1, list(args))
                controller.call = build
                self.seed.side_effect = lambda *args: controller.events.append(('seed-policy',))
                self.diff.side_effect = lambda *args: controller.events.append(('config-diff',))
                with patch.object(sys, 'argv', ['x402_treazury.py', 'prepare']), \
                        patch.object(x402_treazury, 'Controller', return_value=controller), \
                        patch.object(x402_treazury, 'operation_lock', return_value=contextlib.nullcontext()):
                    if fail:
                        with self.assertRaises(subprocess.CalledProcessError):
                            x402_treazury.main()
                        self.assertEqual(controller.events, [('build', 'x402_treazury')])
                    else:
                        x402_treazury.main()
                        self.assertEqual(controller.events[:3], [('build', 'x402_treazury'), ('seed-policy',), ('config-diff',)])

    def test_prepare_retries_activation_without_repeating_completed_wallet_work(self):
        controller = self.controller()
        with patch('subprocess.check_output', return_value='0'):
            controller.prepare()
        self.assertEqual(controller.events[0], ('build', 'x402_treazury'))
        self.assertIn(('config', 'connect'), controller.events)
        self.assertFalse(any(event[0] in ('wallet', 'stop') for event in controller.events))

    def test_reload_failure_disconnects_clients_and_keeps_preparation(self):
        controller = self.controller()
        def client(action, **kwargs):
            if action == 'reload':
                return subprocess.CompletedProcess([], 1, stderr='reload failed')
            return subprocess.CompletedProcess([], 0)
        controller.client = client
        with patch('subprocess.check_output', return_value='0'), self.assertRaises(RuntimeError):
            controller.activate()
        self.assertIn(('admin', 'activation-failed'), controller.events)
        self.assertEqual(controller.events[-2], ('config', 'disconnect'))

    def test_endpoint_failure_or_cancel_never_registers_clients_or_repeats_preparation(self):
        for error in (RuntimeError('native endpoint failed'), KeyboardInterrupt()):
            controller = self.controller()
            def failed():
                raise error
            controller.wait_for_endpoints = failed
            with self.assertRaises(type(error)):
                controller.activate()
            self.assertNotIn(('config', 'connect'), controller.events)
            self.assertNotIn(('wallet', 'prepare'), controller.events)
            self.assertIn(('admin', 'activation-failed'), controller.events)
            self.assertIn(('config', 'disconnect'), controller.events)

    def test_unprepared_startup_leaves_hermes_available_without_wallet_commands(self):
        controller = self.controller()
        controller.inspect = lambda: {'prepared': False, 'reason': 'not prepared'}
        controller.running = lambda service: ''
        with contextlib.redirect_stdout(io.StringIO()):
            controller.startup()
        self.assertFalse(any(event[0] == 'wallet' for event in controller.events))
        self.assertNotIn(('config', 'connect'), controller.events)
