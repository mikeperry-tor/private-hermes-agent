"""Storage initialization and mount boundaries for host-visible persistent data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'components/provisioning'))
from storage import initialize, verify_filesystem, LAYOUT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from deployment import compose_base  # noqa: E402


class PersistentStorageTests(unittest.TestCase):
    def test_failed_lock_probe_refuses_the_storage_filesystem(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('storage.subprocess.run', return_value=subprocess.CompletedProcess([], 0)):
                with self.assertRaisesRegex(RuntimeError, 'does not enforce interprocess file locks'):
                    verify_filesystem(folder)

    def test_host_initialization_preserves_data_and_never_changes_file_ownership(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'data'
            initialize(root)
            key = root / 'x402_treazury-auth/token'
            key.write_text('test-only private data')
            key.chmod(0o600)
            before = key.stat()
            with patch('storage.os.chown') as chown:
                initialize(root)
                chown.assert_not_called()
            self.assertEqual(key.read_text(), 'test-only private data')
            self.assertEqual(key.stat().st_uid, before.st_uid)
            self.assertEqual(key.stat().st_mode, before.st_mode)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)

    def test_container_initialization_changes_only_declared_directory_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'data'
            initialize(root)
            private_file = root / 'x402_treazury-auth/token'
            private_file.write_text('test-only key')
            private_file.chmod(0o600)
            with patch('storage.os.chown') as chown:
                initialize(root, ownership=True)
            allowed = {root / relative for relative in LAYOUT}
            self.assertTrue(all(call.args[0] in allowed for call in chown.call_args_list))
            self.assertEqual(private_file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(private_file.read_text(), 'test-only key')
            for relative, (_, _, mode) in LAYOUT.items():
                self.assertEqual((root / relative).stat().st_mode & 0o777, mode)

    def test_symlinked_root_or_component_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            outside = parent / 'outside'
            outside.mkdir()
            root = parent / 'data'
            root.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                initialize(root)
            root.unlink()
            root.mkdir()
            (root / 'ssh').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                initialize(root)
            self.assertFalse((outside / 'agent').exists())

    def test_persistent_mounts_preserve_wallet_and_executor_separation(self):
        env = {k: v for k, v in os.environ.items() if k not in ('COMPOSE_PROJECT_NAME', 'NETWORK_PREFIX')}
        result = subprocess.run([*compose_base(), '--env-file', '/dev/null', '-f', 'compose.yaml', '-f', 'compose.funnel.yaml',
                                 '--profile', '*', 'config', '--format', 'json'],
                                cwd=ROOT, env=env, text=True, capture_output=True, check=True)
        config = json.loads(result.stdout)
        for name, uid, volume in (('hermes-config', '10000:10000', 'hermes-data'),
                                  ('x402_treazury-inspect', '10003:10003', 'x402_treazury-data')):
            job = config['services'][name]
            self.assertEqual(job['network_mode'], 'none')
            self.assertEqual(job['user'], uid)
            self.assertEqual(job['cap_drop'], ['ALL'])
            self.assertEqual([(m['type'], m['source']) for m in job['volumes']], [('volume', volume)])
            self.assertFalse(job.get('depends_on'))
        self.assertEqual(set(config['volumes']), {'tor-x402_treazury', 'hermes-data', 'x402_treazury-data'})
        wallet_readers = set()
        config_readers = set()
        root = ROOT / 'data'
        for name, service in config['services'].items():
            for mount in service.get('volumes', []):
                if mount['type'] == 'volume' and mount['source'] == 'x402_treazury-data':
                    wallet_readers.add(name)
                if mount['type'] != 'bind':
                    continue
                source = Path(mount['source'])
                if source == ROOT / 'config/x402_treazury':
                    config_readers.add(name)
                    self.assertEqual(mount['target'], '/opt/x402/examples/deployments')
                    self.assertTrue(mount['read_only'])
                    self.assertFalse(mount['bind']['create_host_path'])
                if source == root:
                    self.assertIn(name, ('setup', 'setup-storage', 'mcp-config'))
                    self.assertEqual(service['network_mode'], 'none')
                elif source.is_relative_to(root):
                    self.assertFalse(mount['bind']['create_host_path'])
                    if name == 'executor':
                        self.assertIn(source.relative_to(root).as_posix(),
                                      ('ssh/executor', 'executor/home', 'executor/workspace'))
                    if name == 'hermes':
                        self.assertEqual(source.relative_to(root).as_posix(), 'ssh/agent')
        self.assertEqual(config_readers, {'x402_treazury', 'x402_treazury-setup', 'x402_treazury-admin'})
        self.assertEqual(wallet_readers, {'setup', 'setup-storage', 'x402_treazury', 'x402_treazury-setup', 'x402_treazury-admin', 'x402_treazury-inspect'})


if __name__ == '__main__':
    unittest.main()
