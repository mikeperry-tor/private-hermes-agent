"""Exercise packaged dependency probes and native status consumers without SSH."""
import asyncio
import json
import subprocess
import sys
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from pathlib import Path

from hermes_cli import browser_preview_signins, cli_commands_mixin
from hermes_cli.web_routers.display import _bridge, _open_rfb
from PIL import ImageGrab
from tools.bot_desktop import placement, runtime, sandbox_host, thumbnail
from tools import terminal_tool
from tools.terminal_scope import TerminalPolicyUnavailable
from tools.environments import streams
from tui_gateway import methods_display, server

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

# Discovery budget shares one absolute deadline across env creation, CUA binary check, and harness probe.
import time as _time
from hermes_cli import private_browser_use, private_computer_use
budget_env = SimpleNamespace(_bd_desktop_user=None)
clock = {'offset': 0.0}
real_monotonic = _time.monotonic
seen_timeouts = []
with (
    patch.object(sandbox_host.time, 'monotonic', side_effect=lambda: real_monotonic() + clock['offset']),
    patch.object(private_computer_use.time, 'monotonic', side_effect=lambda: real_monotonic() + clock['offset']),
    patch.object(private_browser_use.time, 'monotonic', side_effect=lambda: real_monotonic() + clock['offset']),
    patch.object(placement, 'resolve', return_value=where),
    patch.object(placement, 'terminal_environment', side_effect=lambda create=True: (clock.__setitem__('offset', clock['offset'] + 5.0), budget_env)[1]),
    patch.object(private_browser_use, '_policy'),
    patch.object(streams, 'run_in', side_effect=lambda _e, argv, **kw: (
        seen_timeouts.append(kw['timeout']), subprocess.CompletedProcess(argv, 0, b'', b''))[1]),
):
    assert private_browser_use.available()
    assert private_browser_use.available()  # harness probe memoized on env
assert len(seen_timeouts) == 3  # cua check #1, harness check #1 (memoized on #2), cua check #2
assert all(0.25 <= t <= 3.1 for t in seen_timeouts), seen_timeouts
assert sandbox_host.probe_budget(real_monotonic() - 1.0, 4.0) == 0.25

with patch.object(placement, 'resolve', return_value=where), \
        patch.object(runtime, '_owned_sandbox_env', return_value=None), \
        patch.object(runtime, '_sandbox_env', return_value=executor), \
        patch.object(sandbox_host, 'published_env', return_value={}):
    for missing in ([], ['Xvnc']):
        with patch.object(sandbox_host, 'missing_binaries', return_value=missing):
            status = runtime.status()
            assert status.missing == missing
            assert status.installed == (not missing)
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
    with patch.object(sandbox_host, 'missing_binaries', side_effect=RuntimeError('private SSH details')), \
            patch.object(sandbox_host, 'published_env', return_value={'DISPLAY': ':20'}):
        status = runtime.status()
        assert not status.installed and status.blocker and status.running
        assert status.display == ':20'
    with patch.object(sandbox_host, 'missing_binaries', return_value=['Xvnc']), \
            patch.object(sandbox_host, 'published_env', side_effect=OSError('private SSH details')):
        status = runtime.status()
        assert not status.installed and not status.running and status.missing == ['Xvnc']
        assert 'Xvnc' in status.blocker and 'private SSH details' not in status.blocker
    with patch.object(sandbox_host, 'missing_binaries', return_value=[]), \
            patch.object(sandbox_host, 'published_env', side_effect=OSError('private SSH details')):
        status = runtime.status()
        assert status.installed and not status.running and not status.missing
        assert 'inspect the desktop display' in status.blocker
for code, output, expected in [(3, b'', {}), (0, b'DISPLAY=:20\n', {'DISPLAY': ':20'})]:
    with patch.object(streams, 'run_in', return_value=subprocess.CompletedProcess([], code, output, b'')):
        assert sandbox_host._published(executor, '/fixture', strict=True) == expected
with patch.object(streams, 'run_in', return_value=subprocess.CompletedProcess([], 255, b'', b'private SSH details')):
    try:
        sandbox_host._published(executor, '/fixture', strict=True)
    except RuntimeError as error:
        assert 'inspect the desktop display' in str(error)
        assert 'private SSH details' not in str(error)
    else:
        raise AssertionError('failed display command became a stopped screen')
print('PASS: successful/missing/failed probes, useful native UI/RPC status snapshots and recovery')

# A prior gateway screen and a stale running remote screen cannot bypass
# admission in the thumbnail or viewer paths.
refused = placement.Placement(placement.REFUSED, 'ssh', 'executor policy refused')
with patch.object(placement, 'resolve', return_value=refused), \
        patch.object(runtime, '_launcher_pid', return_value=42), \
        patch.object(runtime, 'sandbox_screen_running', return_value=True), \
        patch.object(runtime, 'open_rfb_stream') as relay, \
        patch.object(ImageGrab, 'grab') as local_grab:
    assert thumbnail.thumbnail_data_url() is None
    status = runtime.status()
    assert not status.running and status.blocker == refused.reason
    response = server.handle_request({'jsonrpc': '2.0', 'id': 1, 'method': 'display.observe', 'params': {}})
    assert response['error']['message'] == refused.reason
    try:
        asyncio.run(_open_rfb(runtime.state_dir().parent))
    except OSError as error:
        assert str(error) == refused.reason
    else:
        raise AssertionError('disabled desktop opened a relay')
    relay.assert_not_called()
    local_grab.assert_not_called()

with patch.object(placement, 'resolve', return_value=where), \
        patch.object(runtime, '_owned_sandbox_env', return_value=executor), \
        patch.object(sandbox_host, 'published_env', return_value={'DISPLAY': ':20'}), \
        patch.object(sandbox_host, 'grab_jpeg', return_value=b'jpeg') as remote_grab:
    assert thumbnail.thumbnail_data_url() == 'data:image/jpeg;base64,anBlZw=='
    assert remote_grab.call_args.args[0] is executor


async def retained_screen():
    reader, writer, relay = await _open_rfb(runtime.state_dir().parent)
    try:
        assert await reader.readline() == b'RFB 003.008\n'
    finally:
        writer.close()
        await writer.wait_closed()
        relay.wait(timeout=5)


owner = sandbox_host.ssh_owner('executor.test', 'runner', 2222, '/run/test-key')
config = {'env_type': 'ssh', 'ssh_host': owner[0], 'ssh_port': 2222, 'ssh_user': owner[1], 'ssh_key': owner[3]}
assert owner[:4] == ['executor.test', 'runner', '2222', '/run/test-key']
assert owner[4] == ['-F', '/etc/ssh/ssh_config.d/99-private-hermes.conf',
                    '-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes']
marker = {'backend': 'SSHEnvironment', 'ssh': owner}
with patch.object(placement, 'resolve', return_value=where), \
        patch.object(terminal_tool, '_get_env_config', return_value=config), \
        patch.object(sandbox_host, '_read_marker', return_value=marker), \
        patch.object(sandbox_host, '_owner_identity', return_value=marker), \
        patch.object(runtime, '_sandbox_env', side_effect=lambda *, create: executor if create else None) as lookup, \
        patch.object(sandbox_host, 'open_rfb_stream', side_effect=lambda *_: subprocess.Popen(
            [sys.executable, '-c', "print('RFB 003.008')"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)) as relay:
    asyncio.run(retained_screen())
    assert [item.kwargs['create'] for item in lookup.call_args_list] == [False, True]
    assert relay.call_args.args[0] is executor

with patch.object(terminal_tool, '_get_env_config', return_value=config), \
        patch.object(sandbox_host, '_read_marker', return_value={'ssh': ['other.test', *owner[1:]]}), \
        patch.object(runtime, '_sandbox_env') as lookup:
    assert runtime._owned_sandbox_env() is None
    lookup.assert_not_called()

with patch.object(cli_commands_mixin, '_normalize_cdp_url', side_effect=AssertionError('external CDP probe')), \
        patch.object(cli_commands_mixin, '_say_block') as diagnostic:
    cli_commands_mixin._browser_connect(None, 'https://example.invalid')
    assert 'external CDP' in diagnostic.call_args.args[0]
response = server.handle_request({'jsonrpc': '2.0', 'id': 1, 'method': 'browser.manage',
                                  'params': {'action': 'connect', 'url': 'https://example.invalid'}})
assert 'external CDP' in response['error']['message']
assert 'real profile' in browser_preview_signins.export_signins()['error']


ws = Mock(close=AsyncMock())
with patch.object(placement, 'resolve', return_value=where), \
        patch.object(runtime, '_owned_sandbox_env', side_effect=subprocess.TimeoutExpired('fixture', 15)):
    asyncio.run(_bridge(ws, {'hermes_home': str(runtime.state_dir().parent)}))
ws.close.assert_awaited_once_with(code=4001, reason='Bot Desktop is not running')

marker_path = sandbox_host._marker()
marker_path.parent.mkdir(parents=True, exist_ok=True)
marker_path.write_text(json.dumps(marker))
with patch.object(runtime, '_owned_sandbox_env', return_value=executor), \
        patch.object(streams, 'run_in', return_value=subprocess.CompletedProcess([], 255)) as attempt:
    try:
        runtime.stop()
    except RuntimeError as error:
        assert 'Could not stop the desktop' in str(error)
    else:
        raise AssertionError('failed SSH was reported as a stopped desktop')
    assert json.loads(marker_path.read_text()) == marker
    attempt.return_value = subprocess.CompletedProcess([], 3)
    assert not runtime.stop()
    assert not marker_path.exists()

marker_path.write_text(json.dumps(marker))
with patch.object(runtime, '_owned_sandbox_env', return_value=None), \
        patch.object(runtime, '_sandbox_env') as provision:
    try:
        runtime._start_in_sandbox(1)
    except RuntimeError as error:
        assert 'stop it before starting another' in str(error)
    else:
        raise AssertionError('desktop start replaced its unavailable owner')
    try:
        runtime.stop()
    except RuntimeError as error:
        assert 'restore its SSH settings' in str(error)
    else:
        raise AssertionError('an unverified desktop was reported as stopped')
    assert json.loads(marker_path.read_text()) == marker
    provision.assert_not_called()
marker_path.unlink()

ws.reset_mock()
with patch.object(placement, '_terminal_backend', side_effect=TerminalPolicyUnavailable('fixture refusal')):
    asyncio.run(_bridge(ws, {'hermes_home': str(runtime.state_dir().parent)}))
ws.close.assert_awaited_once_with(code=4001, reason='Bot Desktop is not running')


from agent.background_review import _COMBINED_REVIEW_PROMPT, _permitted_review_prompt, _review_tool_whitelist
review = SimpleNamespace(_memory_enabled=False, _user_profile_enabled=False, tools=[
    {'function': {'name': 'read_file'}}, {'function': {'name': 'browser_vault'}},
])
allowed, extras = _review_tool_whitelist(review, {'extra_tools': ['read_file', 'browser_vault']})
assert allowed == extras == {'read_file'}
assert "Summarize any useful findings" in _permitted_review_prompt(_COMBINED_REVIEW_PROMPT, allowed)


with TemporaryDirectory() as folder:
    env = SimpleNamespace(_bd_desktop_user=None, get_temp_dir=lambda: folder)
    screen = Path(folder) / 'hermes-bot-desktop' / 'default'
    screen.mkdir(parents=True)
    with subprocess.Popen(['sleep', '30'], start_new_session=True) as unrelated:
        try:
            (screen / 'launcher.pid').write_text(str(unrelated.pid))
            with patch.object(streams, 'run_in', side_effect=lambda _env, argv, **_: subprocess.run(
                    argv, capture_output=True)):
                assert not sandbox_host.stop(env, 'default')
            assert unrelated.poll() is None
        finally:
            unrelated.terminate()

from tools import browser_session_sandbox

with TemporaryDirectory() as folder:
    profile = Path(folder)
    (profile / 'SingletonLock').symlink_to('old-executor-99999999')
    stamp = browser_session_sandbox._LAUNCH_OWNER_ARG + browser_session_sandbox._launch_owner_stamp(folder)
    with subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)', stamp,
                           '--user-data-dir=' + folder], start_new_session=True) as pending:
        try:
            with patch.object(streams, 'run_in', side_effect=lambda _env, argv, **_: subprocess.run(
                    argv, capture_output=True)):
                owner = browser_session_sandbox._recover_launch(object(), None, folder)
                assert owner is not None and owner.pid == pending.pid
                assert browser_session_sandbox._recover_launch(
                    object(), None, folder, '/devtools/browser/not-ours') is None
        finally:
            pending.terminate()
