"""Exercise packaged dependency probes and native status consumers without SSH."""
import subprocess
from unittest.mock import patch
from types import SimpleNamespace

from tools.bot_desktop import placement, runtime, sandbox_host
from tools.environments import streams
from tui_gateway import methods_display

executor = SimpleNamespace(_bd_desktop_user=None)
where = placement.Placement(placement.TERMINAL, 'ssh')
for output, expected in [(b'', []), (b'Xvnc\nxauth\n', ['Xvnc', 'xauth'])]:
    with patch.object(streams, 'run_in', return_value=subprocess.CompletedProcess([], 0, output, b'')):
        assert sandbox_host.missing_binaries(executor) == expected
with patch.object(streams, 'run_in', return_value=subprocess.CompletedProcess([], 255, b'', b'private SSH details')):
    try:
        sandbox_host.missing_binaries(executor)
    except RuntimeError as error:
        assert 'inspect desktop dependencies' in str(error)
        assert 'private SSH details' not in str(error)
    else:
        raise AssertionError('failed probe became an empty missing-command list')

with patch.object(placement, 'resolve', return_value=where), \
        patch.object(runtime, '_owned_sandbox_env', return_value=None), \
        patch.object(runtime, '_sandbox_env', return_value=executor), \
        patch.object(sandbox_host, 'published_env', return_value={}):
    for missing in ([], ['Xvnc']):
        with patch.object(sandbox_host, 'missing_binaries', return_value=missing):
            status = runtime.status()
            assert status.missing == missing
            assert not status.running
            assert bool(status.blocker) == bool(missing)
    with patch.object(runtime, '_sandbox_env', return_value=None):
        status = runtime.status()
        assert not status.installed and not status.running and status.blocker
        assert methods_display._display_snapshot()['blocker'] == status.blocker
    for failure in (RuntimeError('private SSH details'), OSError('private SSH details'),
                    subprocess.TimeoutExpired('private command', 20)):
        with patch.object(sandbox_host, 'missing_binaries', side_effect=failure):
            status = runtime.status()
            assert not status.installed and not status.running
            assert status.missing == []  # Unknown dependencies, not a missing-package verdict.
            assert status.blocker and 'connection' in status.blocker
            assert 'private' not in status.blocker
            snapshot = methods_display._display_snapshot()
            assert not snapshot['installed'] and snapshot['blocker'] == status.blocker
    with patch.object(sandbox_host, 'missing_binaries', return_value=[]), \
            patch.object(sandbox_host, 'published_env', return_value={'DISPLAY': ':20'}):
        assert runtime.status().running  # A later successful probe recovers without a marker.
print('PASS: successful/missing/failed probes, useful native UI/RPC status snapshots and recovery')
