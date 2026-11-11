"""Readiness follows actual endpoint outcomes; elapsed time only reports progress."""
import asyncio
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import x402_treazury as treasury


class Probe:
    def __init__(self, *results):
        self.results = iter(results)
        self.closed = False

    def poll(self):
        return next(self.results)

    def communicate(self):
        self.closed = True


class EndpointWaitTests(unittest.TestCase):
    def setUp(self):
        self.controller = treasury.Controller(['test-compose'])
        self.instance = ('container', 'current-start', '0')
        self.controller.serving_instance = Mock(return_value=self.instance)
        self.failures = []
        @contextmanager
        def diagnostics(*args):
            yield self.failures
        guard = patch.object(treasury, 'serving_diagnostics', diagnostics)
        guard.start()
        self.addCleanup(guard.stop)
        self.output = io.StringIO()
        redirect = redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def test_long_pending_probe_reports_and_succeeds_without_deadline(self):
        probe = Probe(None, None, 0)
        with patch.object(treasury.subprocess, 'Popen', return_value=probe), \
                patch.object(treasury.time, 'monotonic', side_effect=[0, 31, 10**12]), \
                patch.object(treasury.time, 'sleep'):
            self.assertEqual(self.controller.wait_for_endpoints(), self.instance)
        self.assertEqual(self.output.getvalue().count('Still waiting'), 2)
        self.assertTrue(probe.closed)

    def test_transient_probe_retries_but_permanent_protocol_failure_does_not(self):
        transient, ready = Probe(75), Probe(0)
        with patch.object(treasury.subprocess, 'Popen', side_effect=[transient, ready]), \
                patch.object(treasury.time, 'sleep'):
            self.controller.wait_for_endpoints()
        self.assertTrue(transient.closed and ready.closed)
        failed = Probe(1)
        with patch.object(treasury.subprocess, 'Popen', return_value=failed), \
                self.assertRaisesRegex(RuntimeError, 'initialization/listing failed'):
            self.controller.wait_for_endpoints()
        self.assertTrue(failed.closed)

    def test_native_error_or_observer_loss_during_pending_probe_cleans_up(self):
        for failure in ('native terminal endpoint error', 'startup log observer stopped'):
            self.failures.clear()
            probe = Probe(None)
            with patch.object(treasury.subprocess, 'Popen', return_value=probe), \
                    patch.object(treasury.time, 'sleep', side_effect=lambda _: self.failures.append(failure)), \
                    self.assertRaisesRegex(RuntimeError, failure):
                self.controller.wait_for_endpoints()
            self.assertTrue(probe.closed)

    def test_lifecycle_changes_and_cancellation_clean_up_pending_probe(self):
        for changed in (('replacement', 'current-start', '0'), ('container', 'new-start', '0'),
                        ('container', 'current-start', '1')):
            self.controller.serving_instance.side_effect = [self.instance, self.instance, changed]
            probe = Probe(None)
            with patch.object(treasury.subprocess, 'Popen', return_value=probe), \
                    patch.object(treasury.time, 'sleep'), \
                    self.assertRaisesRegex(RuntimeError, 'restarted or was replaced'):
                self.controller.wait_for_endpoints()
            self.assertTrue(probe.closed)
        self.controller.serving_instance.side_effect = None
        probe = Probe(None)
        with patch.object(treasury.subprocess, 'Popen', return_value=probe), \
                patch.object(treasury.time, 'sleep', side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            self.controller.wait_for_endpoints()
        self.assertTrue(probe.closed)

    def test_service_exit_does_not_launch_a_probe(self):
        self.controller.serving_instance.side_effect = RuntimeError('Research service stopped')
        with patch.object(treasury.subprocess, 'Popen') as spawn, self.assertRaises(RuntimeError):
            self.controller.wait_for_endpoints()
        spawn.assert_not_called()


class DiagnosticContractTests(unittest.TestCase):
    def test_early_native_process_exit_displays_its_current_lifetime_logs(self):
        controller = treasury.Controller(['test-compose'])
        controller.running = lambda service: ''
        controller.call = Mock(return_value=subprocess.CompletedProcess([], 0, stdout='stopped-id\n'))
        with patch.object(treasury.subprocess, 'check_output',
                          return_value='2026-11-11 22:32:02.496429564 +0000 UTC\n'), \
                patch.object(treasury.subprocess, 'run') as logs, \
                self.assertRaisesRegex(RuntimeError, 'Research service stopped'):
            controller.serving_instance()
        self.assertEqual(logs.call_args.args[0],
                         ['docker', 'logs', '--since', '1794436322.496429', 'stopped-id'])

    def test_start_times_of_both_engines_become_the_same_unix_timestamp(self):
        # Podman's StartedAt contains spaces; logs --since takes a Unix timestamp on both engines.
        for started in ('2026-11-11T22:32:02.496429564Z', '2026-11-11 22:32:02.496429564 +0000 UTC',
                        '2026-11-11T23:32:02.496429564+01:00'):
            with self.subTest(started=started):
                self.assertEqual(treasury.log_since(started), '1794436322.496429')
        self.assertEqual(treasury.log_since('2026-11-11T22:32:02Z'), '1794436322.000000')
        with self.assertRaises(ValueError):
            treasury.log_since('2026-11-11')

    def test_instance_keeps_start_time_and_restart_count_apart(self):
        controller = treasury.Controller(['test-compose'])
        controller.running = lambda service: 'serving-id'
        with patch.object(treasury.subprocess, 'check_output',
                          return_value='2|2026-11-11 22:32:02.496429564 +0000 UTC\n'):
            self.assertEqual(controller.serving_instance(), ('serving-id', '1794436322.496429', '2'))

    def follow(self, line):
        process = Mock(stdout=io.StringIO(line))
        process.poll.return_value = 0
        with patch.object(treasury.subprocess, 'Popen', return_value=process) as spawn, \
                patch.object(treasury.threading, 'Thread') as thread, redirect_stderr(io.StringIO()) as output:
            thread.return_value.start.side_effect = lambda: thread.call_args.kwargs['target']()
            with treasury.serving_diagnostics('container', 'current-start', ROOT) as failures:
                result = list(failures)
            self.assertIn('--since', spawn.call_args.args[0])
            self.assertIn('current-start', spawn.call_args.args[0])
        return result, output.getvalue()

    def test_only_exact_terminal_endpoint_diagnostics_trigger_endpoint_failure(self):
        for message in treasury.ENDPOINT_FAILURES:
            failures, shown = self.follow('ERROR x402_treazury: ' + message + ' server="web"\n')
            self.assertIn('unavailable endpoint functionality', failures[0])
            self.assertIn(message, shown)
        failures, _ = self.follow('ERROR x402_treazury: SOCKS endpoint unreachable; retrying\n')
        self.assertIn('log observer stopped', failures[0])
        self.assertNotIn('unavailable endpoint functionality', failures[0])

    def test_silent_observer_exit_is_an_explicit_error(self):
        failures, _ = self.follow('')
        self.assertIn('log observer stopped', failures[0])

    def test_probe_control_pipe_eof_cancels_remote_work(self):
        spec = importlib.util.spec_from_file_location('endpoint_client', ROOT / 'components/x402_treazury/mcp-client.py')
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
        read_fd, write_fd = os.pipe()
        with os.fdopen(read_fd) as reader, os.fdopen(write_fd, 'w') as writer:
            async def exercise():
                started, cancelled = asyncio.Event(), asyncio.Event()
                async def pending():
                    started.set()
                    try:
                        await asyncio.Future()
                    finally:
                        cancelled.set()
                with patch.object(client, 'main', pending), patch.object(client.sys, 'stdin', reader):
                    task = asyncio.create_task(client.controlled_probe())
                    await started.wait()
                    writer.close()
                    with self.assertRaises(client.GatewayPending):
                        await asyncio.wait_for(task, timeout=2)  # test watchdog only
                self.assertTrue(cancelled.is_set())
            asyncio.run(exercise())
