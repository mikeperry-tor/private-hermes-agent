"""Setup failure must block startup; opt-in research policy stays atomic and offline."""
from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import provisioning
import deployment


def load_wrapper():
    spec = importlib.util.spec_from_file_location(
        'x402_treazury_wrapper', ROOT / 'components/x402_treazury/x402_treazury-wrapper.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WrapperSelectionTests(unittest.TestCase):
    def test_wrapper_falls_back_only_on_enoent_and_respects_cli_conflicts(self):
        wrapper = load_wrapper()
        with tempfile.TemporaryDirectory() as folder:
            override = Path(folder) / 'research_desk.toml'
            default = Path(folder) / 'default.toml'
            with patch.object(wrapper, 'OVERRIDE', str(override)), \
                    patch.object(wrapper, 'DEFAULT', str(default)):
                self.assertEqual(wrapper.resolve_config(), str(default))
                override.write_text('version = 1\n')
                self.assertEqual(wrapper.resolve_config(), str(override))
                override.unlink()
                override.symlink_to(Path(folder) / 'missing-target')
                self.assertEqual(wrapper.resolve_config(), str(override))
            with patch.object(wrapper.os, 'lstat', side_effect=PermissionError(13, 'Permission denied')), \
                    self.assertRaisesRegex(SystemExit, 'Cannot inspect research configuration override'):
                wrapper.resolve_config()
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(wrapper.needs_default_config(['serve']))
            self.assertTrue(wrapper.needs_default_config(['config', 'show']))
            self.assertFalse(wrapper.needs_default_config(['build-info']))
            self.assertFalse(wrapper.needs_default_config(['--help']))
            self.assertFalse(wrapper.needs_default_config(['config', 'show', '--provider', 'exa']))
            self.assertFalse(wrapper.needs_default_config(['wallet', 'status', '--state-dir', '/var/lib/x402/state']))
            self.assertFalse(wrapper.needs_default_config(['wallet', 'status', '--config=/tmp/custom.toml']))
        with patch.dict(os.environ, {'X402_TREAZURY_CONFIG': '/tmp/explicit.toml'}, clear=True):
            self.assertFalse(wrapper.needs_default_config(['serve']))


class ProvisioningTests(unittest.TestCase):
    def test_policy_comparison_uses_selected_image_and_engine_without_network_or_state_mounts(self):
        for selected in ('docker', 'podman'):
            with self.subTest(engine=selected), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                path = root / 'config/x402_treazury/research_desk.toml'
                path.parent.mkdir(parents=True)
                path.write_text('cap = 2\n')
                path.chmod(0o640)
                model = json.dumps({'services': {'x402_treazury': {'image': 'selected-local-image'}}})
                with patch.object(deployment, 'engine', return_value=selected), \
                        patch.object(deployment, 'check_engine', side_effect=AssertionError('offline startup gate')), \
                        patch.object(provisioning.subprocess, 'check_output',
                                     side_effect=[model, b'cap = 1\n', model, b'cap = 1\n']) as calls, \
                        redirect_stdout(output := io.StringIO()):
                    command = deployment.compose_base()
                    provisioning.research_config_diff(command, root)
                    provisioning.report_research_config_notice(command, root)
                    expected_engine = deployment.engine_command()
                for render, read in (calls.call_args_list[:2], calls.call_args_list[2:]):
                    self.assertEqual(render.args[0][:len(command)], command)
                    extraction = read.args[0]
                    self.assertEqual(extraction[:len(expected_engine)], expected_engine)
                    self.assertEqual(extraction[extraction.index('--network') + 1], 'none')
                    self.assertEqual(extraction[extraction.index('--pull') + 1], 'never')
                    self.assertEqual(extraction[-1], provisioning.PACKAGED_RESEARCH_CONFIG)
                    self.assertIn('selected-local-image', extraction)
                    self.assertFalse(set(extraction) & {'--volume', '-v', '--mount'})
                self.assertIn('-cap = 1\n+cap = 2', output.getvalue())
                self.assertIn('make x402_treazury-config-diff', output.getvalue())
                self.assertIn('make x402_treazury-config-reset', output.getvalue())
                self.assertEqual(path.read_text(), 'cap = 2\n')
                self.assertEqual(path.stat().st_mode & 0o777, 0o640)
                self.assertFalse((root / 'data').exists())

    def test_default_mode_diff_and_notice_skip_image_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(provisioning, 'packaged_research_config',
                              side_effect=AssertionError('default mode must not invoke engine')):
                with redirect_stdout(diff_out := io.StringIO()):
                    provisioning.research_config_diff([], root)
                with redirect_stdout(notice_out := io.StringIO()), redirect_stderr(notice_err := io.StringIO()):
                    provisioning.report_research_config_notice([], root)
            self.assertIn('Using packaged image defaults', diff_out.getvalue())
            self.assertEqual(notice_out.getvalue(), '')
            self.assertEqual(notice_err.getvalue(), '')
            # An empty directory behaves the same as an absent directory.
            provisioning.ensure_research_config_dir(root)
            self.assertEqual((root / 'config/x402_treazury').stat().st_mode & 0o777, 0o755)
            with patch.object(provisioning, 'packaged_research_config',
                              side_effect=AssertionError('empty dir must not invoke engine')):
                with redirect_stdout(notice_out := io.StringIO()):
                    provisioning.report_research_config_notice([], root)
            self.assertEqual(notice_out.getvalue(), '')

    def test_diff_direction_preservation_and_invalid_path_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'config/x402_treazury/research_desk.toml'
            path.parent.mkdir(parents=True)
            path.write_text('cap = 2\n')
            path.chmod(0o640)
            with patch.object(provisioning, 'packaged_research_config', return_value=b'cap = 1\n'), \
                    redirect_stdout(output := io.StringIO()):
                provisioning.research_config_diff([], root)
            self.assertIn('--- packaged default', output.getvalue())
            self.assertIn('+++ saved config', output.getvalue())
            self.assertIn('-cap = 1\n+cap = 2', output.getvalue())
            self.assertEqual(path.read_text(), 'cap = 2\n')
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertEqual(list(path.parent.iterdir()), [path])
            with patch.object(provisioning, 'packaged_research_config', return_value=b'cap = 2\n'), \
                    redirect_stdout(output := io.StringIO()):
                provisioning.research_config_diff([], root)
            self.assertIn('matches packaged defaults', output.getvalue())
            # Dangling symlink and wrong-type directory fail explicitly.
            path.unlink()
            path.symlink_to(root / 'missing')
            with self.assertRaisesRegex(RuntimeError, 'regular file'):
                provisioning.research_config_diff([], root)
            path.unlink()
            path.parent.rmdir()
            path.parent.write_text('not a directory')
            with self.assertRaisesRegex(RuntimeError, 'must be a directory'):
                provisioning.research_config_diff([], root)

    def test_notice_states_for_tracked_and_legacy_configs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'config/x402_treazury/research_desk.toml'
            base = root / 'config/x402_treazury/.research_desk.toml.base'
            path.parent.mkdir(parents=True)
            # Tracked & image unchanged (user edited locally): stay silent.
            path.write_text('cap = 2\n')
            base.write_text('cap = 1\n')
            with patch.object(provisioning, 'packaged_research_config', return_value=b'cap = 1\n'), \
                    redirect_stdout(out := io.StringIO()):
                provisioning.report_research_config_notice([], root)
            self.assertEqual(out.getvalue(), '')
            # Tracked & unmodified, image updated: point to diff and reset.
            path.write_text('cap = 1\n')
            with patch.object(provisioning, 'packaged_research_config', return_value=b'cap = 3\n'), \
                    redirect_stdout(out := io.StringIO()):
                provisioning.report_research_config_notice([], root)
            self.assertIn('no local edits', out.getvalue())
            self.assertIn('make x402_treazury-config-reset', out.getvalue())
            # Tracked & diverged: point to diff, merge, and reset.
            path.write_text('cap = 2\n')
            with patch.object(provisioning, 'packaged_research_config', return_value=b'cap = 3\n'), \
                    redirect_stdout(out := io.StringIO()):
                provisioning.report_research_config_notice([], root)
            self.assertIn('make x402_treazury-config-diff', out.getvalue())
            self.assertIn('make x402_treazury-config-merge', out.getvalue())
            self.assertIn('make x402_treazury-config-reset', out.getvalue())
            # Legacy (no .base) differing: point to diff and reset, not merge.
            base.unlink()
            with patch.object(provisioning, 'packaged_research_config', return_value=b'cap = 3\n'), \
                    redirect_stdout(out := io.StringIO()):
                provisioning.report_research_config_notice([], root)
            self.assertIn('make x402_treazury-config-diff', out.getvalue())
            self.assertIn('make x402_treazury-config-reset', out.getvalue())
            self.assertNotIn('make x402_treazury-config-merge', out.getvalue())
            # Matching packaged default stays silent.
            path.write_text('cap = 3\n')
            with patch.object(provisioning, 'packaged_research_config', return_value=b'cap = 3\n'), \
                    redirect_stdout(out := io.StringIO()):
                provisioning.report_research_config_notice([], root)
            self.assertEqual(out.getvalue(), '')

    def test_notice_failure_is_advisory_while_diff_failure_raises(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'config/x402_treazury/research_desk.toml'
            path.parent.mkdir(parents=True)
            path.write_text('cap = 2\n')
            error = RuntimeError('image not built')
            with patch.object(provisioning, 'packaged_research_config', side_effect=error):
                with redirect_stderr(output := io.StringIO()):
                    provisioning.report_research_config_notice([], root)
                self.assertIn('comparison unavailable', output.getvalue())
                self.assertIn('make x402_treazury-config-diff', output.getvalue())
                with self.assertRaises(RuntimeError):
                    provisioning.research_config_diff([], root)

    def test_opt_in_config_creates_file_and_base_and_preserves_existing_without_poisoning_base(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = json.dumps({'services': {'x402_treazury': {'image': 'test-image'}}})
            with patch.object(provisioning.subprocess, 'check_output', side_effect=[model, b'version=1\n']) as call:
                created = provisioning.initialize_research_config(['docker', 'compose'], root)
            self.assertTrue(created)
            extraction = call.call_args.args[0]
            self.assertIn('none', extraction)
            self.assertNotIn('--volume', extraction)
            path = root / 'config/x402_treazury/research_desk.toml'
            base = root / 'config/x402_treazury/.research_desk.toml.base'
            self.assertEqual(path.read_text(), 'version=1\n')
            self.assertEqual(base.read_text(), 'version=1\n')
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            self.assertEqual(base.stat().st_mode & 0o777, 0o644)
            path.write_text('# operator edit\n')
            path.chmod(0o640)
            base.unlink()
            with patch.object(provisioning.subprocess, 'check_output') as call:
                created = provisioning.initialize_research_config(['docker', 'compose'], root)
            self.assertFalse(created)
            call.assert_not_called()
            self.assertEqual(path.read_text(), '# operator edit\n')
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertFalse(base.exists())

    def test_failed_extraction_does_not_create_config_and_hints_build(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = json.dumps({'services': {'x402_treazury': {'image': 'test-image'}}})
            error = subprocess.CalledProcessError(1, ['docker'], stderr=b'No such image')
            with patch.object(provisioning.subprocess, 'check_output', side_effect=[model, error]):
                with self.assertRaisesRegex(RuntimeError, 'Run make build or make up first'):
                    provisioning.initialize_research_config(['docker', 'compose'], root)
            self.assertFalse((root / 'config/x402_treazury/research_desk.toml').exists())
            self.assertFalse((root / 'config/x402_treazury/.research_desk.toml.base').exists())

    def test_three_way_merge_validates_offline_and_protects_live_file_on_conflict_or_rejection(self):
        base_text = 'a = 1\nb = 1\nc = 1\nd = 1\ne = 1\n'
        saved_text = 'a = 1\nb = 1\nc = 1\nd = 1\ne = 2\n'
        new_text = 'a = 9\nb = 1\nc = 1\nd = 1\ne = 1\n'
        expected_merged = 'a = 9\nb = 1\nc = 1\nd = 1\ne = 2\n'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'config/x402_treazury/research_desk.toml'
            base = root / 'config/x402_treazury/.research_desk.toml.base'
            merge = root / 'config/x402_treazury/research_desk.toml.merge'
            path.parent.mkdir(parents=True)
            path.write_text(saved_text)
            base.write_text(base_text)
            merge.write_text('stale conflict\n')
            seen = {}

            def fake_validate(command, candidate, root=ROOT):
                seen['candidate_text'] = candidate.read_text()
                seen['candidate_mode'] = candidate.stat().st_mode & 0o777

            with patch.object(provisioning, 'packaged_research_config', return_value=new_text.encode()), \
                    patch.object(provisioning, 'validate_research_config_candidate', side_effect=fake_validate), \
                    redirect_stdout(out := io.StringIO()):
                provisioning.merge_research_config(['docker', 'compose'], root)
            self.assertEqual(seen['candidate_text'], expected_merged)
            self.assertEqual(seen['candidate_mode'], 0o644)
            self.assertEqual(path.read_text(), expected_merged)
            self.assertEqual(base.read_text(), new_text)
            self.assertFalse(merge.exists())
            self.assertIn('make down && make up', out.getvalue())

            # Validation rejection leaves live files untouched and writes .merge.
            path.write_text(saved_text)
            base.write_text(base_text)
            with patch.object(provisioning, 'packaged_research_config', return_value=new_text.encode()), \
                    patch.object(provisioning, 'validate_research_config_candidate',
                                 side_effect=RuntimeError('unknown wallet group')):
                with self.assertRaisesRegex(RuntimeError, 'unknown wallet group'):
                    provisioning.merge_research_config(['docker', 'compose'], root)
            self.assertEqual(path.read_text(), saved_text)
            self.assertEqual(base.read_text(), base_text)
            self.assertEqual(merge.read_text(), expected_merged)

            # Textual conflict leaves live files untouched and writes conflict markers to .merge.
            conflict_new = 'a = 1\nb = 1\nc = 1\nd = 1\ne = 9\n'
            with patch.object(provisioning, 'packaged_research_config', return_value=conflict_new.encode()):
                with self.assertRaisesRegex(RuntimeError, 'conflict'):
                    provisioning.merge_research_config(['docker', 'compose'], root)
            self.assertEqual(path.read_text(), saved_text)
            self.assertEqual(base.read_text(), base_text)
            self.assertIn('<<<<<<<', merge.read_text())

            # Fatal git merge-file error (>127) leaves .merge untouched.
            merge.unlink()
            fatal = subprocess.CompletedProcess(['git'], 255, stdout=b'', stderr=b'binary file')
            with patch.object(provisioning, 'packaged_research_config', return_value=conflict_new.encode()), \
                    patch.object(provisioning.subprocess, 'run', return_value=fatal):
                with self.assertRaisesRegex(RuntimeError, 'exit 255'):
                    provisioning.merge_research_config(['docker', 'compose'], root)
            self.assertFalse(merge.exists())

            # Legacy copy without .base refuses 3-way merge cleanly.
            base.unlink()
            with patch.object(provisioning, 'packaged_research_config', return_value=new_text.encode()):
                with self.assertRaisesRegex(RuntimeError, '.research_desk.toml.base is absent'):
                    provisioning.merge_research_config(['docker', 'compose'], root)

            # Non-diverged merge states: default, current, matches_packaged, stale_unmodified.
            path.write_text(saved_text)
            base.write_text(base_text)
            with patch.object(provisioning, 'packaged_research_config', return_value=base_text.encode()), \
                    redirect_stdout(out := io.StringIO()):
                provisioning.merge_research_config(['docker', 'compose'], root)
            self.assertIn('nothing to merge', out.getvalue())

            path.write_text(new_text)
            with patch.object(provisioning, 'packaged_research_config', return_value=new_text.encode()), \
                    redirect_stdout(out := io.StringIO()):
                provisioning.merge_research_config(['docker', 'compose'], root)
            self.assertEqual(base.read_text(), new_text)
            self.assertIn('already matches', out.getvalue())

            path.write_text(base_text)
            base.write_text(base_text)
            with patch.object(provisioning, 'packaged_research_config', return_value=new_text.encode()), \
                    patch.object(provisioning, 'validate_research_config_candidate') as validate, \
                    redirect_stdout(out := io.StringIO()):
                provisioning.merge_research_config(['docker', 'compose'], root)
            validate.assert_called_once()
            self.assertEqual(path.read_text(), new_text)
            self.assertEqual(base.read_text(), new_text)
            self.assertIn('Updated unmodified', out.getvalue())

            path.unlink()
            with patch.object(provisioning, 'packaged_research_config',
                              side_effect=AssertionError('default mode merge must not invoke engine')), \
                    redirect_stdout(out := io.StringIO()):
                provisioning.merge_research_config(['docker', 'compose'], root)
            self.assertIn('nothing to merge', out.getvalue())

    def test_validate_candidate_runs_offline_without_wallet_mount(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config_dir = root / 'config/x402_treazury'
            config_dir.mkdir(parents=True)
            candidate = config_dir / '.research-config-candidate-test'
            candidate.write_text('version = 1\n')
            model = json.dumps({'services': {'x402_treazury': {'image': 'test-image'}}})
            ok = subprocess.CompletedProcess([], 0, stdout='', stderr='')
            with patch.object(provisioning.subprocess, 'check_output', return_value=model), \
                    patch.object(provisioning.subprocess, 'run', return_value=ok) as run:
                provisioning.validate_research_config_candidate(['docker', 'compose'], candidate, root=root)
            argv = run.call_args.args[0]
            self.assertEqual(argv[argv.index('--network') + 1], 'none')
            self.assertEqual(argv[argv.index('--pull') + 1], 'never')
            self.assertIn('--read-only', argv)
            self.assertNotIn('/var/lib/x402', ' '.join(argv))
            self.assertIn(f'X402_TREAZURY_CONFIG=/opt/x402/examples/deployments/{candidate.name}', argv)

    def test_reset_backs_up_edited_config_and_returns_to_default_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'config/x402_treazury/research_desk.toml'
            base = root / 'config/x402_treazury/.research_desk.toml.base'
            backup = root / 'config/x402_treazury/research_desk.toml.bak'
            path.parent.mkdir(parents=True)
            # Edited local file -> writes .bak and removes override + .base.
            path.write_text('cap = 2\n')
            base.write_text('cap = 1\n')
            with patch.object(provisioning, 'packaged_research_config', return_value=b'cap = 1\n'), \
                    redirect_stdout(out := io.StringIO()):
                provisioning.reset_research_config([], root)
            self.assertFalse(path.exists())
            self.assertFalse(base.exists())
            self.assertEqual(backup.read_text(), 'cap = 2\n')
            self.assertIn('research_desk.toml.bak', out.getvalue())
            self.assertIn('make down && make up', out.getvalue())
            backup.unlink()

            # Unedited file matching packaged default -> no .bak created.
            path.write_text('cap = 1\n')
            base.write_text('cap = 1\n')
            with patch.object(provisioning, 'packaged_research_config', return_value=b'cap = 1\n'), \
                    redirect_stdout(out := io.StringIO()):
                provisioning.reset_research_config([], root)
            self.assertFalse(path.exists())
            self.assertFalse(base.exists())
            self.assertFalse(backup.exists())

            # Unavailable image -> still backs up safely and removes override.
            path.write_text('cap = 9\n')
            base.write_text('cap = 1\n')
            with patch.object(provisioning, 'packaged_research_config', side_effect=RuntimeError('missing image')), \
                    redirect_stdout(out := io.StringIO()):
                provisioning.reset_research_config([], root)
            self.assertFalse(path.exists())
            self.assertFalse(base.exists())
            self.assertEqual(backup.read_text(), 'cap = 9\n')

            # Already in default mode -> cleans orphan .base and reports cleanly.
            base.write_text('orphan\n')
            with redirect_stdout(out := io.StringIO()):
                provisioning.reset_research_config([], root)
            self.assertFalse(base.exists())
            self.assertIn('Already using packaged image defaults', out.getvalue())

            # Dangling symlink override -> removed cleanly.
            path.symlink_to(root / 'missing-target')
            with redirect_stdout(out := io.StringIO()):
                provisioning.reset_research_config([], root)
            self.assertFalse(os.path.lexists(path))

            # Wrong-type override or companion directory refuses reset before mutating state.
            path.mkdir()
            with self.assertRaisesRegex(RuntimeError, 'regular file'):
                provisioning.reset_research_config([], root)
            path.rmdir()
            path.write_text('cap = 2\n')
            base.mkdir()
            with self.assertRaisesRegex(RuntimeError, 'must not be a directory'):
                provisioning.reset_research_config([], root)
            self.assertEqual(path.read_text(), 'cap = 2\n')

    def test_failed_canonical_setup_reports_logs_and_exit_code(self):
        with patch.object(provisioning, 'check_bind_sources') as binds, patch.object(provisioning.subprocess, 'run') as run, \
                patch.object(provisioning.subprocess, 'check_output', side_effect=['setup-id\n', '7\n']):
            with self.assertRaisesRegex(RuntimeError, 'Offline setup failed.*exit 7'):
                provisioning.initialize_setup(['docker', 'compose'])
            binds.assert_called_once_with(['docker', 'compose'], ['up', '--no-deps', 'setup'])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][-1], 'setup')
        self.assertEqual(run.call_args_list[1].args[0][-4:], ['logs', '--tail', '40', 'setup'])


if __name__ == '__main__':
    unittest.main()
