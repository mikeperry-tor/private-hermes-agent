"""Old transport failures and losing native sessions cannot close a successor."""
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from unittest.mock import Mock, patch

from hermes_cli import private_browser_use as remote
from tools import browser_session, browser_session_lifecycle as lifecycle, interrupt, browser_use_cli
from tools.bot_desktop import lease, runtime
from tools import browser_session_sandbox
from tools.browser_supervisor import SUPERVISOR_REGISTRY

browser = {'features': {'sandbox': True}}
key = browser_use_cli._backend_cache_key(None, "", sidecar=True)
old = remote.Session(Mock(), Mock(), 'home', 'endpoint', browser)
successor = remote.Session(Mock(), Mock(), 'home', 'endpoint', browser)
read_fd, write_fd = os.pipe()
os.close(write_fd)
with os.fdopen(read_fd, 'rb') as output:
    old.process.stdout = output
    with patch.object(remote, '_sessions', {key: successor}), \
         patch.object(remote, '_policy'), patch.object(remote, '_session', return_value=old), \
         patch.object(remote, '_validated_endpoint'), \
         patch.object(browser_session, 'run_fenced_dispatch', side_effect=lambda run: run(lambda: None)), \
         patch.object(interrupt, 'is_interrupted', return_value=False), \
         patch.object(runtime, 'touch_activity'):
        result = json.loads(remote.execute('print(1)'))
        assert 'outcome may be unknown' in result['error'], result
        successor.process.stdin.close.assert_not_called()
        assert remote._sessions[key] is successor

read_fd, write_fd = os.pipe()
os.write(write_fd, b'{"returncode":0,"stdout":"ok"}\nextra trailing bytes')
os.close(write_fd)
malformed = remote.Session(Mock(), Mock(), 'home', 'endpoint', browser)
with os.fdopen(read_fd, 'rb') as output:
    malformed.process.stdout = output
    with patch.object(remote, '_sessions', {key: malformed}), \
         patch.object(remote, '_policy'), patch.object(remote, '_session', return_value=malformed), \
         patch.object(remote, '_validated_endpoint'), \
         patch.object(browser_session, 'run_fenced_dispatch', side_effect=lambda run: run(lambda: None)), \
         patch.object(interrupt, 'is_interrupted', return_value=False), \
         patch.object(runtime, 'touch_activity'), \
         patch.object(remote.threading, 'Thread'):
        result = json.loads(remote.execute('print(1)'))
        assert 'malformed output' in result['error'] and 'Do not replay' in result['error'], result
        malformed.process.stdin.close.assert_called_once()
        assert key not in remote._sessions

with patch.object(remote, '_sessions', {key: successor}), patch.object(remote.threading, 'Thread'):
    lifecycle.release_session_backend(key, {'features': {'sandbox': True}})
    successor.process.stdin.close.assert_not_called()
    assert remote._sessions[key] is successor
    lifecycle.release_session_backend(key, browser)
    successor.process.stdin.close.assert_called_once()
    assert key not in remote._sessions
print('PASS: old failed transport and losing native session preserve the exact successor owner')

stale = {'features': {'local': True}}
new_session = {'features': {'local': True}}
new_supervisor = Mock()


def finish_slow_probe(info):
    assert info is stale
    with patch.object(browser_session, '_backend_dead', side_effect=lambda observed: observed is stale):
        current = browser_session.get_session_info(key)
    successor.browser = current
    remote._sessions[key] = successor
    SUPERVISOR_REGISTRY._by_task[key] = new_supervisor
    return True


with (
    patch.object(browser_session, '_active_sessions', {key: stale}),
    patch.object(browser_session, '_session_last_activity', {}),
    patch.object(browser_session, '_session_owner_homes', {}),
    patch.object(browser_session, '_cleanup_failures', {}),
    patch.object(browser_session, '_create_session_for_key', return_value=new_session),
    patch.object(browser_session, '_backend_dead', side_effect=finish_slow_probe),
    patch.object(lifecycle, 'start_cleanup_thread'),
    patch.object(remote, '_sessions', {}),
    patch.object(remote.threading, 'Thread'),
    patch.object(SUPERVISOR_REGISTRY, '_by_task', {}),
    patch.object(SUPERVISOR_REGISTRY, '_home_by_task', {}),
):
    successor.process.stdin.close.reset_mock()
    recovered = browser_session.get_session_info(key)
    assert remote._sessions[key] is successor and successor.browser is recovered
    assert SUPERVISOR_REGISTRY.get(key) is new_supervisor
    successor.process.stdin.close.assert_not_called()
    new_supervisor.stop.assert_not_called()
print('PASS: an older native liveness result preserves the replacement browser and supervisor')

launcher_key = 'fixture-sandbox-launch'
stale_launch = {'features': {'sandbox': True}, 'launcher_key': launcher_key,
                'cdp_url': 'ws://127.0.0.1:1234/devtools/browser/old', 'sandbox_launch': (101, '111')}
replacement_launch = {'features': {'sandbox': True}, 'launcher_key': launcher_key,
                      'cdp_url': 'ws://127.0.0.1:1234/devtools/browser/new', 'sandbox_launch': (102, '112')}
with (
    patch.object(browser_session_sandbox, '_launched', {launcher_key: browser_session_sandbox._Launch(Mock(), 102, '112', 'profile', '/devtools/browser/new')}),
    patch.object(browser_session_sandbox, '_stop_launched') as stop,
):
    lifecycle.release_session_backend('old-launch', stale_launch)
    stop.assert_not_called()
    lifecycle.release_session_backend('new-launch', replacement_launch)
    stop.assert_called_once_with(launcher_key)
print('PASS: stale cleanup cannot stop Chromium relaunched under the same launcher key')

for change in ('interrupt', 'takeover'):
    @contextmanager
    def queued():
        if change == 'takeover':
            lease.acquire('qualification-viewer')
            lease.release('qualification-viewer')
        yield

    current = remote.Session(Mock(), Mock(), 'home', 'endpoint', browser, lock=queued())
    with (
        patch.object(remote, '_sessions', {key: current}),
        patch.object(remote, '_policy'),
        patch.object(remote, '_session', return_value=current),
        patch.object(interrupt, 'is_interrupted', side_effect=[False, change == 'interrupt']),
    ):
        result = json.loads(remote.execute('raise AssertionError("must not launch")'))
        assert ('before launch' in result.get('error', '') if change == 'interrupt'
                else result.get('code') == 'human_has_control'), result
        current.process.stdin.write.assert_not_called()
        current.process.stdin.close.assert_not_called()
        assert remote._sessions[key] is current

with subprocess.Popen([sys.executable, '-c', 'pass'], stdin=subprocess.PIPE) as failed:
    failed.wait(timeout=10)
    failed.stdin.write(b'buffered request')
    try:
        failed.stdin.flush()
    except BrokenPipeError:
        pass
    else:
        raise AssertionError('The fixture must have a broken write pipe')
    current = remote.Session(Mock(), Mock(), 'home', 'endpoint', browser)
    first = remote.Session(Mock(), failed, 'home', 'endpoint', browser)
    with (
        patch.object(remote, '_sessions', {'failed': first, 'current': current}),
        patch.object(remote.threading, 'Thread') as reap,
    ):
        remote.close()
        assert not remote._sessions
        assert [item.kwargs['args'][0] for item in reap.call_args_list] == [failed, current.process]
        current.process.stdin.close.assert_called_once()
print('PASS: queued actions send no code after revocation; a broken pipe leaves no owner unreaped')

from tempfile import TemporaryDirectory
from pathlib import Path
from tools import browser_session_cloud
commands = []
with (
    patch.object(browser_session_cloud, 'browser_section',
                 return_value={'chromium_args': ['--window-position', '0', '--window-size', '0']}),
    patch('tools.environments.streams.run_in', side_effect=lambda _env, argv, **_kw: (
        commands.append(argv), subprocess.CompletedProcess(argv, 0, b'4242 999\n', b''))[1]),
):
    assert browser_session_sandbox._start_chromium(object(), None, '/usr/bin/chromium', '/tmp/p',
                                                  {'DISPLAY': ':5'}, owner='owner-token') == (4242, '999')
assert '--window-position 0 --window-size 0' in commands[-1][-1], commands[-1][-1]
assert '--hermes-chromium-launch-owner=owner-token about:blank' in commands[-1][-1], commands[-1][-1]

with TemporaryDirectory() as root:
    glob_profile = Path(root) / 'profile[glob]?*'
    glob_profile.mkdir()
    stamp = browser_session_sandbox._LAUNCH_OWNER_ARG + browser_session_sandbox._launch_owner_stamp(str(glob_profile))
    with subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)', stamp,
                           f'--user-data-dir={glob_profile}'], start_new_session=True) as proc:
        try:
            with patch('tools.environments.streams.run_in',
                       side_effect=lambda _env, argv, **_kw: subprocess.run(argv, capture_output=True)):
                recovered = browser_session_sandbox._recover_launch(object(), None, str(glob_profile))
                assert recovered is not None and recovered.pid == proc.pid
        finally:
            proc.terminate()
            proc.wait(timeout=10)
print('PASS: chromium_args repeated values, owner_arg placement before about:blank, and glob profile recovery')

import threading
entered = threading.Event()
release = threading.Event()
warm_proc = Mock()
warm_proc.poll.return_value = None
warm = remote.Session(object(), warm_proc, 'home', 'ws://warm', {'features': {'sandbox': True}, 'cdp_url': 'ws://warm'})
to_close = remote.Session(object(), Mock(), 'home', 'ws://close', {'features': {'sandbox': True}, 'cdp_url': 'ws://close'})
to_close.process.stdin.close = Mock()
cold_errors = []

def slow_get_info(k):
    if k == 'key-a':
        entered.set()
        assert release.wait(timeout=5.0)
        raise RuntimeError('abort cold startup after concurrency check')
    return warm.browser

def cold_start():
    try:
        remote._session('key-a')
    except Exception as error:
        cold_errors.append(str(error))

with (
    patch.object(remote, '_sessions', {'key-b': warm, 'key-c': to_close}),
    patch.object(remote, '_key_locks', {}),
    patch.object(remote, '_policy'),
    patch.object(remote, '_validated_endpoint', return_value='ws://warm'),
    patch('tools.browser_session.get_session_info', side_effect=slow_get_info),
    patch('tools.bot_desktop.runtime.tool_sandbox', return_value=(warm.env, {'DISPLAY': ':20'})),
):
    cold_thread = threading.Thread(target=cold_start)
    cold_thread.start()
    try:
        assert entered.wait(timeout=5.0)
        assert remote._session('key-b') is warm  # warm lookup does not wait on the cold key's lock
        remote.close(cache_key='key-c')
        assert 'key-c' not in remote._sessions
    finally:
        release.set()
        cold_thread.join(timeout=5.0)
assert cold_errors and 'abort cold startup' in cold_errors[0], cold_errors
print('PASS: cold _session(key) startup does not stall close() or warm _session() on other keys')
