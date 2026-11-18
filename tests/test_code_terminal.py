"""Stack terminal setting, remote cwd data, and scoped native-shell preparation."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
bootstrap = types.SimpleNamespace(PRIVATE_HERMES_TERMINAL_ENVIRONMENT='code',
                                 PRIVATE_HERMES_TERMINAL_SSH=('10.203.82.3', '2222', 'runner', '/run/agent-ssh/id_ed25519'))
spec = importlib.util.spec_from_file_location('code_terminal', ROOT / 'components/hermes/code_terminal.py')
terminal = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, hermes_bootstrap=bootstrap):
    spec.loader.exec_module(terminal)


_BACKEND = types.SimpleNamespace(ConfigBackendUnavailable=SystemExit)


class CodeTerminalTests(unittest.IsolatedAsyncioTestCase):
    def test_invalid_modes_and_paths_fail_without_fallback(self):
        for value in ('', 'invalid', 'CODE', ' code'):
            with patch.object(terminal, 'PRIVATE_HERMES_TERMINAL_ENVIRONMENT', value), self.assertRaisesRegex(RuntimeError, 'must be code or agent'):
                terminal.environment()
        for path in ('', 'relative', '-oProxyCommand=bad', '/tmp/new\nline', '/tmp/\x00', '/tmp/\x1b'):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                terminal.validate_path(path)

    def test_remote_probe_preserves_directory_and_file_paths_as_data(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "space ü ' $(touch NEVER) ; trailing "
            directory.mkdir()
            file = directory / 'file'
            file.touch()
            for requested in (directory, file):
                probe = subprocess.run([sys.executable, '-c', terminal._PROBE, str(requested)],
                                       capture_output=True, text=True, check=True)
                self.assertEqual(json.loads(probe.stdout), str(directory.resolve()))
            self.assertFalse((directory / 'NEVER').exists())
            self.assertNotEqual(subprocess.run([sys.executable, '-c', terminal._PROBE, str(directory / 'absent')]).returncode, 0)

    async def test_agent_uses_native_selection_without_ssh_readiness(self):
        native = types.SimpleNamespace(resolve_argv=lambda **kw: (['/bin/sh', '-i'], '/local', {'TERM': 'xterm'}, 'sh'))
        with patch.dict(sys.modules, {'hermes_cli.web_host_terminal': native, 'hermes_cli.config_backend': _BACKEND}), \
                patch.object(terminal, 'PRIVATE_HERMES_TERMINAL_ENVIRONMENT', 'agent'), \
                patch.object(terminal, 'ssh_argv', side_effect=AssertionError('agent must not check SSH')):
            result = await terminal.prepare(Path('/profile'), '/local')
        self.assertEqual(result, (['/bin/sh', '-i'], '/local', {'TERM': 'xterm'}, 'Agent · sh', '/local'))

    async def test_ssh_failure_is_actionable_and_does_not_expose_raw_diagnostics(self):
        native = types.SimpleNamespace(resolve_argv=lambda **kw: (['sh'], '/local', {}, 'sh'))
        probe = types.SimpleNamespace(returncode=255, communicate=AsyncMock(return_value=(b'', None)))
        with patch.dict(sys.modules, {'hermes_cli.web_host_terminal': native, 'hermes_cli.config_backend': _BACKEND}), \
                patch.object(terminal, 'ssh_argv', return_value=['ssh']), \
                patch.object(asyncio, 'create_subprocess_exec', AsyncMock(return_value=probe)) as spawn:
            with self.assertRaisesRegex(RuntimeError, 'check executor availability') as error:
                await terminal.prepare(Path('/profile'))
            self.assertNotIn('private details', str(error.exception))
            self.assertEqual(spawn.call_args.kwargs['stderr'], asyncio.subprocess.DEVNULL)

    async def test_preparation_refuses_an_executor_without_bash(self):
        spawn = asyncio.create_subprocess_exec

        async def apply_probe(*argv, **kwargs):
            _, flag, program, cwd = shlex.split(argv[-1])
            return await spawn(sys.executable, flag, program, cwd, **kwargs)

        with tempfile.TemporaryDirectory() as root:
            native = types.SimpleNamespace(resolve_argv=lambda **kw: (['sh'], root, dict(os.environ, PATH=root), 'sh'))
            with patch.dict(sys.modules, {'hermes_cli.web_host_terminal': native, 'hermes_cli.config_backend': _BACKEND}), \
                    patch.object(terminal, 'ssh_argv', return_value=['ssh']), \
                    patch.object(asyncio, 'create_subprocess_exec', apply_probe):
                with self.assertRaisesRegex(RuntimeError, 'Bash is unavailable on the executor'):
                    await terminal.prepare(Path(root), root)

    async def test_cancelling_preparation_reaps_the_probe(self):
        native = types.SimpleNamespace(resolve_argv=lambda **kw: (['sh'], '/local', {}, 'sh'))
        spawn = asyncio.create_subprocess_exec
        started = asyncio.Event()
        process = None

        async def stalled_probe(*args, **kwargs):
            nonlocal process
            process = await spawn(sys.executable, '-c', 'import threading; threading.Event().wait()', **kwargs)
            started.set()
            return process

        with patch.dict(sys.modules, {'hermes_cli.web_host_terminal': native, 'hermes_cli.config_backend': _BACKEND}), \
                patch.object(terminal, 'ssh_argv', return_value=['ssh']), \
                patch.object(asyncio, 'create_subprocess_exec', stalled_probe):
            preparation = asyncio.create_task(terminal.prepare(Path('/profile')))
            try:
                await asyncio.wait_for(started.wait(), 10)
                preparation.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(preparation, 10)
                self.assertIsNotNone(process.returncode)
            finally:
                if process is not None and process.returncode is None:
                    process.kill()
                    await process.wait()

    async def test_config_backend_unavailable_becomes_code_terminal_error(self):
        class FakeBackendUnavailable(SystemExit):
            pass

        with (
            patch.dict(sys.modules, {
                'hermes_cli.config_backend': types.SimpleNamespace(ConfigBackendUnavailable=FakeBackendUnavailable),
                'hermes_cli.web_host_terminal': types.SimpleNamespace(
                    resolve_argv=Mock(side_effect=FakeBackendUnavailable('secret plane uri')),
                ),
            }),
            patch.object(terminal, 'PRIVATE_HERMES_TERMINAL_ENVIRONMENT', 'code'),
            self.assertRaises(terminal.CodeTerminalError) as raised,
        ):
            await terminal.prepare(Path('/tmp/home'), '/workspace')
        self.assertIn('configuration backend', str(raised.exception))
        self.assertNotIn('secret plane uri', str(raised.exception))

    async def test_probe_reaps_child_on_non_cancellation_error(self):
        probe = Mock()
        probe.returncode = None
        probe.communicate = AsyncMock(side_effect=RuntimeError('unexpected reader error'))
        probe.wait = AsyncMock(return_value=-9)
        with (
            patch.dict(sys.modules, {
                'hermes_cli.config_backend': types.SimpleNamespace(ConfigBackendUnavailable=SystemExit),
                'hermes_cli.web_host_terminal': types.SimpleNamespace(
                    resolve_argv=Mock(return_value=(['bash'], '/tmp', {}, 'bash')),
                ),
            }),
            patch.object(terminal, 'PRIVATE_HERMES_TERMINAL_ENVIRONMENT', 'code'),
            patch.object(terminal, 'ssh_argv', return_value=['ssh', 'exec']),
            patch('asyncio.create_subprocess_exec', AsyncMock(return_value=probe)),
            self.assertRaises(RuntimeError),
        ):
            await terminal.prepare(Path('/tmp/home'), '/workspace')
        probe.kill.assert_called_once_with()
        probe.wait.assert_awaited_once()
