"""Runs inside disposable Hermes against its real SSH desktop, with no provider calls."""
import asyncio
import json
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, Mock, patch
import model_tools
from tools.bot_desktop import placement, runtime, sandbox_host, lease
from tools.environments import streams
from tools.computer_use import cua_backend_session, tool
from tools.registry import registry

assert tool.check_computer_use_requirements(), 'desktop requirements unavailable'
assert registry.get_entry('computer_use')
assert placement.resolve().where == placement.TERMINAL
status = runtime.start()
assert status.running and status.placement == 'terminal:ssh', status
env = placement.terminal_environment()
published = runtime.published_env()


def remote(code):
    result = streams.run_in(env, ['bash', '-c', code], child_env=published, timeout=30)
    assert result.returncode == 0, (result.stdout.decode(), result.stderr.decode())
    return result.stdout.decode()


assert remote('id -u').strip() == '10000'
remote("python3 -c \"import pathlib; s=pathlib.Path('/proc/self/status').read_text(); assert 'CapEff:\\t0000000000000000' in s; assert 'CapPrm:\\t0000000000000000' in s; assert 'NoNewPrivs:\\t1' in s\"")
remote('test ! -e /opt/data && test ! -e /var/lib/x402 && test ! -e /run/agent-ssh && test ! -e /Users')
remote('test ! -r /run/executor-auth/ssh_host_ed25519_key; ! touch /etc/computer-use-canary; ! sudo -n true')
remote("python3 -c 'import threading; t=threading.Thread(target=lambda:None); t.start(); t.join()'")
remote("nohup xfce4-terminal --disable-server --title computer-use-fixture > /tmp/cu-terminal.log 2>&1 </dev/null &")
time.sleep(1)

# Fixture-only approvals and image handling: no real account actions or inference.
os.environ['HERMES_INTERACTIVE'] = '1'
tool.set_approval_callback(lambda *args, **kwargs: 'once')
tool._should_route_through_aux_vision = lambda: False


def act(**args):
    result = tool.handle_computer_use(args, session_id='computer-use-fixture')
    result = json.loads(result) if isinstance(result, str) else result
    assert not result.get('error'), result
    if result.get('code') == 'background_unavailable':
        assert result['verdict']['recommended'] == 'foreground', result
        result = tool.handle_computer_use({**args, 'delivery_mode': 'foreground'},
                                         session_id='computer-use-fixture')
        result = json.loads(result) if isinstance(result, str) else result
    assert result.get('ok', True), result
    return result


captured = act(action='capture', mode='vision', app='xfce4-terminal')
assert captured.get('_multimodal'), str(captured)[:500]
process_probe = '''import pathlib
seen=set()
for proc in pathlib.Path('/proc').glob('[0-9]*'):
 try:
  name=(proc/'comm').read_text().strip()
  if name not in {'Xvnc','xfwm4','xfdesktop','xfce4-panel','cua-driver'}: continue
  fields=dict(line.split(':',1) for line in (proc/'status').read_text().splitlines() if ':' in line)
  assert set(fields['Uid'].split())=={'10000'}, (name,fields['Uid'])
  assert all(int(fields[k].strip(),16)==0 for k in ('CapEff','CapPrm','CapInh','CapAmb')), name
  assert fields['NoNewPrivs'].strip()=='1', name
  seen.add(name)
 except FileNotFoundError: pass
assert {'Xvnc','xfwm4','xfdesktop','xfce4-panel','cua-driver'} <= seen, seen
'''
probe = streams.run_in(env, ['python3', '-c', process_probe], timeout=20)
assert probe.returncode == 0, probe.stderr.decode()
act(action='click', coordinate=[90, 90])
marker = 'computer-use-ok-' + secrets.token_hex(8)
act(action='type', text=f'printf {marker} > /workspace/computer-use-marker')
act(action='key', keys='return')
time.sleep(.5)
assert remote('cat /workspace/computer-use-marker') == marker
act(action='scroll', direction='up', amount=2)
lease.acquire('fixture-viewer')
blocked = json.loads(tool.handle_computer_use({'action': 'capture'}, session_id='computer-use-fixture'))
assert blocked['code'] == 'human_has_control', blocked
lease.release('fixture-viewer')

session = tool._get_backend('computer-use-fixture')._session
inspect_desktop = session._assert_desktop


def takeover_during_inspection():
    inspect_desktop()
    lease.acquire('fixture-viewer')
    lease.release('fixture-viewer')


with patch.object(session, '_assert_desktop', takeover_during_inspection), \
     patch.object(session._session, 'call_tool', AsyncMock()) as send:
    blocked = json.loads(tool.handle_computer_use(
        {'action': 'list_apps'}, session_id='computer-use-fixture'))
    assert blocked['code'] == 'human_has_control', blocked
    send.assert_not_awaited()

# The bridge can time out while its loop is blocked inside the last lease read.
lease_entered, finish_lease, lease_done = threading.Event(), threading.Event(), threading.Event()


def blocked_lease_read():
    lease_entered.set()
    assert finish_lease.wait(10)
    lease_done.set()


def call_through_bridge():
    token = cua_backend_session.dispatch_fence.set(blocked_lease_read)
    try:
        session._bridge.run(session._call_tool_async('list_apps', {}), timeout=3)
    except TimeoutError:
        return
    finally:
        cua_backend_session.dispatch_fence.reset(token)
    raise AssertionError('CUA bridge did not time out')


with patch.object(session._session, 'call_tool', AsyncMock()) as send, ThreadPoolExecutor(1) as pool:
    call = pool.submit(call_through_bridge)
    try:
        assert lease_entered.wait(10), 'CUA request did not reach the final lease read'
        call.result(timeout=10)
    finally:
        finish_lease.set()
    assert lease_done.wait(10)
    session._bridge.run(asyncio.sleep(0))
    send.assert_not_awaited()

# Permission revocation during the final lease read must refuse the operation
# before any message reaches the old driver.
current_mode = Mock(return_value='standard')
read_lease = lease.get


def change_mode_during_lease_read(profile_key=None):
    if threading.current_thread().name == 'cua-driver-loop':
        current_mode.return_value = 'bounded'
    return read_lease(profile_key)


with patch.object(tool, '_cua_permission_mode', current_mode), \
     patch.object(lease, 'get', change_mode_during_lease_read), \
     patch.object(session._session, 'call_tool', AsyncMock()) as send:
    blocked = json.loads(tool.handle_computer_use(
        {'action': 'list_apps'}, session_id='computer-use-fixture'))
    assert 'permissions changed' in blocked['error'], blocked
    # Retiring the old driver may send its own end_session cleanup request.
    assert all(call.args[0] == 'end_session' for call in send.await_args_list), send.await_args_list
act(action='list_apps')

# A restarted launcher can reuse the same X display while the model still has
# a cached driver and screen targets. The first call must refuse that owner.
assert runtime.stop()
assert runtime.start().running
replacement = runtime.published_env()
assert replacement['DISPLAY'] == published['DISPLAY']
assert replacement['DBUS_SESSION_BUS_ADDRESS'] != published['DBUS_SESSION_BUS_ADDRESS']
stale = json.loads(tool.handle_computer_use(
    {'action': 'list_apps'}, session_id='computer-use-fixture'))
assert 'recorded desktop changed' in stale['error'].lower(), stale
act(action='capture', mode='vision', app='screen')
tool.release_computer_use_session('computer-use-fixture')

# The fixture's terminal belonged to the old X session. Reopen it on the new screen.
published = replacement
remote("nohup xfce4-terminal --disable-server --title computer-use-fixture > /tmp/cu-terminal.log 2>&1 </dev/null &")
time.sleep(1)
act(action='capture', mode='vision', app='xfce4-terminal')
tool.release_computer_use_session('computer-use-fixture')

# The browser's own diagnostic reports sandbox layers, not just startup success.
chrome = sandbox_host.chromium_executable(env)
result = streams.run_in(env, [chrome, '--headless', '--disable-gpu', '--no-first-run', '--allow-chrome-scheme-url',
                             '--user-data-dir=/tmp/cu-browser-check', '--dump-dom', 'chrome://sandbox'],
                        child_env=published, timeout=30)
assert result.returncode == 0, result.stderr.decode()[-2000:]
page = result.stdout.decode()
text = re.sub('<[^>]*>', ' ', page)
assert re.search(r'Layer 1 Sandbox\s+Namespace', text), text[-2000:]
for layer in ('PID namespaces', 'Network namespaces', 'Seccomp-BPF sandbox'):
    assert re.search(re.escape(layer) + r'\s+Yes', text), text[-2000:]

# Namespace-local root must not acquire authority over the parent-owned network.
namespace_probe = '''import os,socket
fd=os.open('/proc/self/ns/net',os.O_RDONLY)
try: os.setns(fd,0)
except PermissionError: pass
else: raise AssertionError('joined parent network namespace')
try: socket.socket(socket.AF_INET,socket.SOCK_RAW,socket.IPPROTO_TCP)
except PermissionError: pass
else: raise AssertionError('raw socket in parent network namespace')
'''
probe = streams.run_in(env, ['unshare', '-Ur', 'python3', '-c', namespace_probe], timeout=20)
assert probe.returncode == 0, probe.stderr.decode()

# Drive native idle eligibility against real processes using only disposable
# activity timestamps; no production timeout or additional watchdog is added.
runtime.touch_activity()
activity = runtime.state_dir() / 'activity'
past = time.time() - runtime.idle_stop_seconds() - 2
lease.acquire('idle-fixture-viewer')
os.utime(activity, (past, past))
assert not runtime.stop_if_idle(), 'active human lease was stopped'
lease.release('idle-fixture-viewer')
assert runtime.stop_if_idle()
assert not runtime.published_env()
act(action='capture', mode='vision', app='screen')
tool.release_computer_use_session('computer-use-fixture')
# A lost derived display publication must be repairable without clearing home,
# workspace or browser state, even while the old launcher still exists.
directory = sandbox_host._remote_dir(env, runtime._profile_name())
probe = streams.run_in(env, ['python3', '-c',
                            'import pathlib,sys; (pathlib.Path(sys.argv[1])/"env").unlink()', directory], timeout=20)
assert probe.returncode == 0, probe.stderr.decode()
assert not runtime.published_env()
act(action='capture', mode='vision', app='screen')
tool.release_computer_use_session('computer-use-fixture')
print('PASS: real SSH desktop capture/click/type/key/scroll, executor marker, lease takeover and driver reconnect')
print('PASS: runner has no effective/permitted capabilities, no sudo or private mounts; root is read-only')
print('PASS: Chromium starts without sandbox bypass; chrome://sandbox exposes namespace/seccomp diagnostics')
print('PASS: user-namespace root cannot join or create raw sockets in the parent network namespace')
print('PASS: native idle stop preserves active takeover, stops an idle desktop and capture restarts its display')
print('PASS: missing derived display publication is reconstructed by native restart/retry')
