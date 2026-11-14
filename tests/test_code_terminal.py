"""Stack terminal setting, remote cwd data, and scoped native-shell preparation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
bootstrap = types.SimpleNamespace(PRIVATE_HERMES_TERMINAL_ENVIRONMENT='code',
                                 PRIVATE_HERMES_TERMINAL_SSH=('10.203.82.3', '2222', 'runner', '/run/agent-ssh/id_ed25519'))
spec = importlib.util.spec_from_file_location('code_terminal', ROOT / 'components/hermes/code_terminal.py')
terminal = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, hermes_bootstrap=bootstrap):
    spec.loader.exec_module(terminal)


class CodeTerminalTests(unittest.TestCase):
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

    def test_agent_uses_native_selection_without_ssh_readiness(self):
        native = types.SimpleNamespace(resolve_argv=lambda **kw: (['/bin/sh', '-i'], '/local', {'TERM': 'xterm'}, 'sh'))
        with patch.dict(sys.modules, {'hermes_cli.web_host_terminal': native}), \
                patch.object(terminal, 'PRIVATE_HERMES_TERMINAL_ENVIRONMENT', 'agent'), \
                patch.object(terminal, 'ssh_argv', side_effect=AssertionError('agent must not check SSH')):
            result = terminal.prepare(Path('/profile'), '/local')
        self.assertEqual(result, (['/bin/sh', '-i'], '/local', {'TERM': 'xterm'}, 'Agent · sh', '/local'))

    def test_ssh_failure_is_actionable_and_does_not_expose_raw_diagnostics(self):
        native = types.SimpleNamespace(resolve_argv=lambda **kw: (['sh'], '/local', {}, 'sh'))
        with patch.dict(sys.modules, {'hermes_cli.web_host_terminal': native}), \
                patch.object(terminal, 'ssh_argv', return_value=['ssh']), \
                patch.object(terminal.subprocess, 'run', return_value=subprocess.CompletedProcess([], 255, '', 'private details')):
            with self.assertRaisesRegex(RuntimeError, 'check executor availability') as error:
                terminal.prepare(Path('/profile'))
            self.assertNotIn('private details', str(error.exception))
