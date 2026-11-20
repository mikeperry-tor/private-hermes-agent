"""Run inside disposable Hermes; exercise actual remote browser_exec, no inference."""
import concurrent.futures
from contextlib import contextmanager
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

import model_tools
from tools import browser_use_cli as browser
from tools.bot_desktop import runtime, placement, lease
from tools.environments import streams
from tools.registry import registry
from tools import browser_use_executor as remote
from tools.hosted_tool_policy import tool_refusal


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def run(code, name='fixture', **kw):
    result = decoded(browser.browser_exec(code, session=name, task_id='browser-fixture', **kw))
    assert not result.get('error'), result
    assert result.get('success', result.get('_multimodal')), result
    return result


assert browser.browser_exec_available()
assert registry.get_entry('browser_exec')
assert all(tool_refusal(n) for n in ('browser_cdp', 'browser_dialog', 'browser_vault'))
assert runtime.start().running
registered = decoded(registry.dispatch('browser_exec', {'code':'print("registry-remote")',
                                  'session':'registry-fixture'}, task_id='browser-fixture'))
assert registered.get('output','').strip() == 'registry-remote', registered
# Interleave last-owner cleanup with a real attachment to the same Chromium,
# after DevTools discovery and before the successor's cache record is published.
from unittest.mock import Mock, patch
from tools import browser_session, browser_session_lifecycle, browser_session_sandbox
from tools import browser_url_policy
from tools.bot_desktop import sandbox_host

with patch.object(browser_url_policy, 'check_website_access', return_value={
        'message': 'Blocked by website policy', 'host': 'fixture.invalid', 'rule': 'fixture.invalid', 'source': 'fixture',
}):
    refused = decoded(browser.browser_exec("goto_url('https://fixture.invalid')", task_id='browser-fixture'))
    assert refused.get('error') == 'Blocked by website policy', refused

old_key = browser._backend_cache_key('browser-fixture', 'registry-fixture')
old_record = browser_session._active_sessions[old_key]
original_launch = old_record['sandbox_launch']


create_sandbox = browser_session_sandbox.create_sandbox_session


def attach_during_cleanup(key):
    candidate = create_sandbox(key)
    assert candidate['sandbox_launch'] == original_launch
    assert candidate['cdp_url'] == old_record['cdp_url']
    browser_session_lifecycle.cleanup_single_session(old_key)
    assert browser_session_sandbox._launched[candidate['launcher_key']][1:3] == original_launch
    return candidate


replacement_name = 'attachment-successor'
replacement_key = browser._backend_cache_key('browser-fixture', replacement_name)
with patch.object(browser_session_sandbox, 'create_sandbox_session', side_effect=attach_during_cleanup) as create:
    successor = browser_session.get_session_info(replacement_key)
    create.assert_called_once_with(replacement_key)
assert successor['sandbox_launch'] == original_launch
assert 'attachment-survived' in run('print("attachment-survived")', replacement_name)['output']
print('PASS: Chromium survives last-owner cleanup during attachment and publication', flush=True)
env = placement.terminal_environment()
user = sandbox_host._user_for(env)
profile = sandbox_host.browser_profile_dir(env)

# A new named session cannot displace the recorded process while it still
# holds the Chromium singleton, even if its endpoint file is missing.
owner = browser_session_sandbox._launched[successor['launcher_key']]
missing_key = browser._backend_cache_key('browser-fixture', 'missing-endpoint-contender')
active_port = f'{profile}/DevToolsActivePort'
hidden_port = f'{active_port}.fixture-hidden'
assert streams.run_in(env, ['mv', active_port, hidden_port], user=user, timeout=10).returncode == 0
try:
    try:
        browser_session.get_session_info(missing_key)
    except RuntimeError as error:
        assert 'still owns the profile' in str(error), error
    else:
        raise AssertionError('published a second browser while the original owned the profile')
    assert missing_key not in browser_session._active_sessions
    assert browser_session_sandbox._launched[successor['launcher_key']] is owner
finally:
    assert streams.run_in(env, ['mv', hidden_port, active_port], user=user, timeout=10).returncode == 0
print('PASS: missing DevTools state keeps the live native profile owner', flush=True)


def remove_fixture_chromium(pid):
    # This process belongs to the disposable fixture. Force its exit so the
    # recovery check does not depend on how Chromium handles suspended TERM.
    assert streams.run_in(env, ['kill', '-KILL', pid], timeout=10).returncode == 0
    for _ in range(100):
        proc = streams.run_in(env, ['ps', '-o', 'stat=', '-p', pid], timeout=10)
        if proc.returncode != 0 or proc.stdout.lstrip().startswith(b'Z'):
            return
        time.sleep(.1)
    raise AssertionError('The retired Chromium fixture did not exit')


def assert_retiring_browser_refuses():
    try:
        browser_session.get_session_info(replacement_key)
    except RuntimeError as error:
        assert 'still shutting down' in str(error), error
    else:
        raise AssertionError('published a retiring Chromium endpoint')


wrong_browser_script = """
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sys

class DifferentBrowser(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        result = dict(webSocketDebuggerUrl=f'ws://127.0.0.1:{self.server.server_port}/devtools/browser/other')
        self.wfile.write(json.dumps(result).encode())

with HTTPServer(('127.0.0.1', int(sys.argv[1])), DifferentBrowser) as listener:
    print(listener.server_port, flush=True)
    listener.serve_forever()
"""

# Let TERM queue without exiting so DevTools still listens during the next attach.
pid = str(original_launch[0])
assert streams.run_in(env, ['kill', '-STOP', pid], timeout=10).returncode == 0
try:
    browser_session_lifecycle.cleanup_single_session(replacement_key)
    status = streams.run_in(env, ['cat', f'/proc/{pid}/status'], timeout=10)
    pending = next(line.split()[-1] for line in status.stdout.splitlines() if line.startswith(b'ShdPnd:'))
    assert status.returncode == 0 and int(pending, 16) & (1 << (signal.SIGTERM - 1)), 'TERM was not sent to the suspended Chromium'
    assert_retiring_browser_refuses()

    # A different responsive endpoint in the file does not prove that the
    # suspended original has released the singleton.
    listener = streams.open_stream(env, ['python3', '-u', '-c', wrong_browser_script, '0'])
    assert streams.run_in(env, ['mv', active_port, hidden_port], user=user, timeout=10).returncode == 0
    try:
        port = int(listener.stdout.readline())
        path = '/devtools/browser/other'
        write = streams.run_in(env, ['python3', '-c',
            'from pathlib import Path; import sys; Path(sys.argv[1]).write_text(sys.argv[2])',
            active_port, f'{port}\n{path}\n'], user=user, timeout=10)
        assert write.returncode == 0
        assert browser_session_sandbox._live_devtools(env, user, profile) == (port, path)
        assert_retiring_browser_refuses()
        assert successor['launcher_key'] in browser_session_sandbox._retiring
    finally:
        listener.kill()
        listener.wait()
        assert streams.run_in(env, ['mv', hidden_port, active_port], user=user, timeout=10).returncode == 0
finally:
    remove_fixture_chromium(pid)
print('PASS: matching and changed DevTools endpoints refuse while the retired owner remains', flush=True)

# Inject port forwarding failure only after a real Chromium has published its
# endpoint. Hold its shutdown acknowledgement to exercise the immediate retry.
real_signal = browser_session_sandbox._signal_launch
pending_signals = []


def delay_new_shutdown(launch):
    if launch[1:3] == original_launch:  # confirm the first fixture really left before starting this one
        return real_signal(launch)
    pending_signals.append(launch)
    return True


with patch.object(browser_session_sandbox, '_signal_launch', delay_new_shutdown):
    try:
        with patch.object(streams, 'forward_port', side_effect=RuntimeError('fixture forwarding failure')):
            try:
                browser_session.get_session_info(replacement_key)
            except RuntimeError as error:
                assert 'fixture forwarding failure' in str(error), error
            else:
                raise AssertionError('a failed forward published a browser')
        assert_retiring_browser_refuses()
        assert len(pending_signals) == 2 and pending_signals[0] == pending_signals[1]
    finally:
        if pending_signals:
            remove_fixture_chromium(str(pending_signals[0][1]))
print('PASS: failed startup retires the actual Chromium before a forwarding retry', flush=True)

# Lose the SSH reply after the real detached command has returned in the
# executor. The next session must recover that precise Chromium as its owner.
real_run = streams.run_in
launch_reply = []


def lose_detached_reply(target, argv, **kwargs):
    reply = real_run(target, argv, **kwargs)
    if browser_session_sandbox._LAUNCH_OWNER_ARG in argv[-1] and 'setsid ' in argv[-1]:
        assert reply.returncode == 0, reply.stderr
        launch_reply.append(tuple(reply.stdout.decode().split()[-2:]))
        raise subprocess.TimeoutExpired('fixture detached browser reply', 1)
    return reply


with patch.object(streams, 'run_in', side_effect=lose_detached_reply):
    try:
        browser_session.get_session_info(replacement_key)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise AssertionError('the detached launch reply was not lost')
assert len(launch_reply) == 1
endpoint = browser_session_sandbox._wait_for_port(env, user, profile)
with patch.object(browser_session_sandbox, '_live_devtools',
                  side_effect=[browser_session_sandbox.GONE, endpoint, endpoint]):
    recovered = browser_session.get_session_info(replacement_key)
assert recovered['sandbox_launch'] == (int(launch_reply[0][0]), launch_reply[0][1]), recovered
with patch.object(browser_session_sandbox, '_signal_launch', wraps=browser_session_sandbox._signal_launch) as stop:
    browser_session_lifecycle.cleanup_single_session(replacement_key)
    assert any(call.args[0][1:3] == recovered['sandbox_launch'] for call in stop.call_args_list)
remove_fixture_chromium(launch_reply[0][0])
print('PASS: lost detached Chromium reply recovers the exact launcher and allows native cleanup', flush=True)
# A replacement started outside Hermes' registry on the same desktop profile
# must stay under its actual owner's control when its attachments are closed.
managed = browser_session.get_session_info(replacement_key)
remove_fixture_chromium(str(managed['sandbox_launch'][0]))
borrowed_pid, _ = browser_session_sandbox._start_chromium(
    env, user, sandbox_host.chromium_executable(env), profile,
    {**runtime.published_env(), 'TMPDIR': streams.sandbox_temp_dir(env)})
borrowed_name = 'independently-started-browser'
borrowed_key = browser._backend_cache_key('browser-fixture', borrowed_name)
try:
    browser_session_sandbox._wait_for_port(env, user, profile)
    borrowed = browser_session.get_session_info(borrowed_key)
    assert borrowed['launcher_key'] == managed['launcher_key']
    browser_session_lifecycle.cleanup_single_session(replacement_key)
    browser_session_lifecycle.cleanup_single_session(borrowed_key)
    again = browser_session.get_session_info(borrowed_key)
    assert again['cdp_url'] == borrowed['cdp_url']
    assert 'sandbox_launch' not in borrowed and 'sandbox_launch' not in again
    assert run('print("borrowed-browser-alive")', borrowed_name)['output'].strip() == 'borrowed-browser-alive'
finally:
    browser_session_lifecycle.cleanup_single_session(borrowed_key)
    remove_fixture_chromium(str(borrowed_pid))
print('PASS: a same-profile independent Chromium remains attachable after releasing a task', flush=True)
# Let the independent browser acquire the profile after the managed path has
# observed no endpoint, while both native launch attempts use the same profile.
native_spawn = browser_session_sandbox._spawn_owned
dock_pids = []
dock_key = browser._backend_cache_key('browser-fixture', 'initial-dock-winner')


def dock_wins_first(env, user, profile, key, published):
    pid, _ = browser_session_sandbox._start_chromium(
        env, user, sandbox_host.chromium_executable(env), profile,
        {**published, 'TMPDIR': streams.sandbox_temp_dir(env)})
    dock_pids.append(pid)
    browser_session_sandbox._wait_for_port(env, user, profile)
    return native_spawn(env, user, profile, key, published)


try:
    with patch.object(browser_session_sandbox, '_spawn_owned', side_effect=dock_wins_first):
        dock = browser_session.get_session_info(dock_key)
    browser_session_lifecycle.cleanup_single_session(dock_key)
    again = browser_session.get_session_info(dock_key)
    assert again['cdp_url'] == dock['cdp_url']
    assert 'sandbox_launch' not in dock and 'sandbox_launch' not in again
    assert run('print("dock-winner-alive")', 'initial-dock-winner')['output'].strip() == 'dock-winner-alive'
finally:
    browser_session_lifecycle.cleanup_single_session(dock_key)
    if dock_pids:
        remove_fixture_chromium(str(dock_pids[0]))
print('PASS: a dock Chromium winning cold discovery keeps its endpoint and cleanup authority', flush=True)
# A recycled port can answer while the profile still names a crashed browser.
# This listener deliberately advertises a different WebSocket browser path.
wrong_listener = streams.open_stream(env, ['python3', '-u', '-c', wrong_browser_script, '0'])
try:
    recycled_port = int(wrong_listener.stdout.readline())
    stale_path = '/devtools/browser/previous-browser'
    write = streams.run_in(env, ['python3', '-c',
        'from pathlib import Path; import sys; Path(sys.argv[1]).write_text(sys.argv[2])',
        f'{profile}/DevToolsActivePort', f'{recycled_port}\n{stale_path}\n'])
    assert write.returncode == 0
    assert browser_session_sandbox._live_devtools(env, user, profile) is browser_session_sandbox.GONE
    fresh = browser_session.get_session_info(replacement_key)
    assert not fresh['cdp_url'].endswith(stale_path) and 'sandbox_launch' in fresh
    assert run('print("recycled-port-recovered")', replacement_name)['output'].strip() == 'recycled-port-recovered'
finally:
    wrong_listener.kill()
    wrong_listener.wait()
print('PASS: a recycled TCP port cannot publish a stale DevTools path', flush=True)
# Verify the live dispatch guard can distinguish temporary probe loss from
# a stale endpoint even while native lookup has a positive confirmation.
warm = browser_session._active_sessions[replacement_key]
warm_runner = remote._sessions[replacement_key]
observed_stdin = Mock(wraps=warm_runner.process.stdin)
with (
    patch.object(warm_runner.process, 'stdin', observed_stdin),
    patch.object(browser_session_sandbox, '_live_devtools', return_value=None),
):
    refusal = decoded(browser.browser_exec(
        'raise AssertionError("runner accepted an inconclusive probe")',
        session=replacement_name, task_id='browser-fixture'))
assert 'no usable DevTools endpoint' in refusal.get('error', ''), refusal
observed_stdin.write.assert_not_called()
assert browser_session._active_sessions[replacement_key] is warm
assert remote._sessions[replacement_key] is warm_runner


def check_recycled_runner(recycle_while_queued):
    # Recycle the exact port while native lookup still has a positive cache.
    warm = browser_session._active_sessions[replacement_key]
    old_runner = remote._sessions[replacement_key]
    original_lock = old_runner.lock
    warm_port, _ = browser_session_sandbox._live_devtools(env, user, profile)
    listener = None

    def recycle():
        nonlocal listener
        remove_fixture_chromium(str(warm['sandbox_launch'][0]))
        listener = streams.open_stream(env, ['python3', '-u', '-c', wrong_browser_script, str(warm_port)])
        assert int(listener.stdout.readline()) == warm_port
        assert browser_session_sandbox.sandbox_browser_alive(warm), 'warm cache was not exercised'

    @contextmanager
    def queued():
        with original_lock:
            if recycle_while_queued:
                recycle()
            yield

    try:
        if not recycle_while_queued:
            recycle()
        observed = Mock(wraps=old_runner.process.stdin)
        with patch.object(old_runner, 'lock', queued()), patch.object(old_runner.process, 'stdin', observed):
            refusal = decoded(browser.browser_exec(
                'raise AssertionError("stale runner received model code")',
                session=replacement_name, task_id='browser-fixture'))
        assert 'changed during setup' in refusal.get('error', ''), refusal
        observed.write.assert_not_called()
        assert replacement_key not in browser_session._active_sessions
        assert replacement_key not in remote._sessions
        recovered = run('print("warm-recycled-port-recovered")', replacement_name)
        assert recovered['output'].strip() == 'warm-recycled-port-recovered'
        assert remote._sessions[replacement_key] is not old_runner
    finally:
        if listener is not None:
            listener.kill()
            listener.wait()


check_recycled_runner(recycle_while_queued=False)
check_recycled_runner(recycle_while_queued=True)
print('PASS: warm and queued dispatch retire stale runners with zero Python writes and recover on explicit retry', flush=True)
namespace = streams.run_in(env, ['readlink', '/proc/self/ns/net'], timeout=10)
assert namespace.returncode == 0, namespace.stderr.decode()
executor_netns = namespace.stdout.decode().strip()
assert executor_netns.startswith('net:['), executor_netns
native_screenshot = browser._native_screenshot_result
browser._native_screenshot_result = lambda *args: None  # Separate screenshot staging from provider choice.
server = streams.open_stream(env, ['python3', '-u', '-c', r'''
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
class Page(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200)
  self.send_header('Content-Type','text/html')
  self.end_headers()
  self.wfile.write(b'<title>executor-browser-fixture</title><input id="entry"><button onclick="document.title=document.querySelector(\'#entry\').value">save</button><a download="proof.txt" href="data:text/plain,executor-download">download</a>')
 def log_message(self,*args): pass
# A speculative browser connection must not block the later Python client.
s=ThreadingHTTPServer(('127.0.0.1',0),Page)
print(s.server_port,flush=True)
s.serve_forever()
'''])
port = int(server.stdout.readline())
try:
    result = run('import os,pathlib,subprocess,json\n'
                 'assert os.getuid()==10000\n'
                 'assert not any(k in os.environ for k in ["NEARAI_API_KEY","OPENAI_API_KEY","HERMES_HOME","BROWSER_USE_API_KEY"])\n'
                 'assert not pathlib.Path("/opt/hermes").exists()\n'
                 'assert not pathlib.Path("/opt/data").exists()\n'
                 'assert not pathlib.Path("/var/lib/x402").exists()\n'
                 'status=pathlib.Path("/proc/self/status").read_text()\n'
                 'assert "CapEff:\\t0000000000000000" in status and "CapPrm:\\t0000000000000000" in status\n'
                 'assert "NoNewPrivs:\\t1" in status\n'
                 'assert subprocess.check_output(["id","-u"]).strip()==b"10000"\n'
                 'pathlib.Path("python-marker").write_text("executor-python")\n'
                 'print("remote-only",os.getcwd())')
    assert 'remote-only' in result['output']
    workspace = result['workspace']
    assert not Path(workspace, 'python-marker').exists()
    assert streams.run_in(env, ['cat', workspace + '/python-marker']).stdout == b'executor-python'
    result = run(f'new_tab("http://127.0.0.1:{port}/")\nprint(page_info())')
    assert 'executor-browser-fixture' in result['output'], result
    filled = run('cdp("Target.activateTarget",targetId=current_tab()["targetId"])\nfill_input("#entry","typed-in-executor")\njs("document.querySelector(\'button\').click()")\nprint(js("JSON.stringify({title:document.title,value:document.querySelector(\'#entry\').value})"))')
    assert 'typed-in-executor' in filled['output'], filled
    title = run('print(js("document.title"))')
    assert 'typed-in-executor' in title['output'], title
    download = run('js("document.querySelector(\'a\').click()")\n'
                   'import time,pathlib,os\n'
                   'p=pathlib.Path(os.environ["BH_DOWNLOAD_DIR"])/"proof.txt"\n'
                   'for _ in range(50):\n'
                   ' if p.exists(): break\n'
                   ' time.sleep(.1)\n'
                   'assert p.read_text()=="executor-download"\nprint(str(p))')
    assert '/workspace/browser-use/downloads/proof.txt' in download['output'], download
    shot = run('print(capture_screenshot())')
    p = Path(shot['screenshot_path'])
    assert p.is_file() and p.read_bytes().startswith(b'\x89PNG'), shot
    assert '/cache/browser-use/screenshots/' in str(p)
    for filename in ('relative.png', '/tmp/browser fixture screenshot.png'):
        shot = run(f'print(capture_screenshot({filename!r}))')
        assert Path(shot['screenshot_path']).read_bytes().startswith(b'\x89PNG'), shot
    # Chromium's live absolute socket symlink must not break intended native
    # file sync. Its profile remains authoritative in the executor bind data.
    from hermes_constants import get_hermes_home
    synced = Path(get_hermes_home()) / 'cache' / 'documents' / 'browser-sync-fixture.txt'
    synced.parent.mkdir(parents=True, exist_ok=True)
    synced.write_text('initial fixture')
    env._sync_manager.sync(force=True)
    pairs = [(host, path) for host, path in env._sync_manager._get_files_fn() if host == str(synced)]
    assert len(pairs) == 1, pairs
    target = pairs[0][1]
    changed = streams.run_in(env, ['python3','-c',
                          'from pathlib import Path; import sys; Path(sys.argv[1]).write_text("changed in executor")', target])
    assert changed.returncode == 0, changed.stderr.decode()
    with tempfile.NamedTemporaryFile(suffix='.tar') as archive:
        env._ssh_bulk_download(Path(archive.name))
        with tarfile.open(archive.name) as data:
            names = data.getnames()
        assert not any('/bot-desktop/browser-profile' in name for name in names)
        assert target.lstrip('/') in names
    env._sync_manager.sync_back()
    assert synced.read_text() == 'changed in executor'
    env._sync_manager.sync(force=True)  # Acknowledge the pulled version before native exit cleanup.
    (p.parent.parent / 'fixture-artifacts.json').write_text(json.dumps({
        'screenshot': str(p), 'download': '/workspace/browser-use/downloads/proof.txt'}))
    assert run('print(js("document.title"))')['output'] == 'typed-in-executor\n'
    # Native named tabs are distinct, while their browser profile remains shared.
    run(f'new_tab("http://127.0.0.1:{port}/")', name='second')
    assert 'executor-browser-fixture' in run('print(js("document.title"))', name='second')['output']
    assert 'typed-in-executor' in run('print(js("document.title"))')['output']
    for task, name in [('unnamed-one', ''), ('unnamed-two', ''), ('literal-default', 'default')]:
        value = decoded(browser.browser_exec(f'new_tab("http://127.0.0.1:{port}/")\njs("document.title=\'{task}\'")',
                                            session=name, task_id=task))
        assert value.get('success'), value
    for task, name in [('unnamed-one', ''), ('unnamed-two', ''), ('literal-default', 'default')]:
        value = decoded(browser.browser_exec('print(js("document.title"))', session=name, task_id=task))
        assert task in value.get('output', ''), value
    # Cold calls for one identity serialize daemon creation and model execution.
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda n: run(f'print({n})', name='concurrent'), range(2)))
    assert {r['output'].strip() for r in results} == {'0', '1'}
    # A printed gateway-looking path is fetched from the executor, never read locally.
    canary = Path('/tmp/browser-agent-canary.png')
    canary.write_bytes(b'gateway-secret')
    output = run('print("/tmp/browser-agent-canary.png")')
    assert 'screenshot_path' not in output
    assert b'gateway-secret' not in json.dumps(output).encode()
    same_path = run('print(capture_screenshot("/tmp/browser-agent-canary.png"))')
    assert Path(same_path['screenshot_path']).read_bytes().startswith(b'\x89PNG'), same_path
    assert canary.read_bytes() == b'gateway-secret'
    run('from pathlib import Path\n'
        'Path("agent_helpers.py").write_text("def fixture_helper():\\n import os; return os.getuid()\\n")\n'
        'Path(".env").write_text("BU_CDP_WS=ws://10.203.83.3:8337\\nBH_TELEMETRY=1\\n")')
    daemon = run('from browser_harness import _ipc,admin\nprint(_ipc.pid_path(admin.NAME).read_text())', name='daemon-crash')
    raw = daemon['output'].strip()
    pid = json.loads(raw)['pid'] if raw.startswith('{') else int(raw)
    assert streams.run_in(env, ['kill', '-KILL', str(pid)]).returncode == 0
    helpers = run('import os\nassert fixture_helper()==10000\n'
                  'assert os.environ["BU_CDP_WS"].startswith("ws://127.0.0.1:")\n'
                  'assert os.environ["BH_TELEMETRY"]=="0"\nprint("remote-helpers")', name='daemon-crash')
    assert 'remote-helpers' in helpers['output']
    run('from pathlib import Path\nPath("agent_helpers.py").unlink()\nPath(".env").unlink()')
    from tools import vision_tools
    vision_tools._should_use_native_vision_fast_path = lambda: True
    browser._native_screenshot_result = native_screenshot
    attached = run('print(capture_screenshot())')
    assert attached.get('_multimodal'), attached
    assert attached['content'][1]['image_url']['url'].startswith('data:image/'), attached
    browser._native_screenshot_result = lambda *args: None
    traceback = decoded(browser.browser_exec('# first\n# second\nraise RuntimeError("fixture-trace")', session='trace'))
    assert traceback.get('exit_code') != 0 and 'line 3' in traceback.get('stderr',''), traceback
    lease.acquire('browser-fixture-human')
    denied = decoded(browser.browser_exec('raise AssertionError("must not run")', session='fixture'))
    assert denied.get('code') == 'human_has_control', denied
    lease.release('browser-fixture-human')
    # Native thread-scoped stop closes just this identity and reports uncertainty.
    from tools.interrupt import set_interrupt
    set_interrupt(True)
    try:
        denied = decoded(browser.browser_exec('import time; time.sleep(30)', session='cancelled', task_id='browser-fixture'))
        assert 'interrupted' in denied.get('error',''), denied
    finally:
        set_interrupt(False)
    assert run('print("retry-after-cancel")', name='cancelled')['output'].strip() == 'retry-after-cancel'
    worker = {}
    def active_call():
        worker['tid'] = threading.get_ident()
        return decoded(browser.browser_exec(
            'import subprocess,pathlib,time\n'
            'p=subprocess.Popen(["python3","-c","import time; time.sleep(30)"])\n'
            'pathlib.Path("/workspace/browser-active-child").write_text(str(p.pid))\n'
            'time.sleep(30)\npathlib.Path("/workspace/browser-cancel-failed").touch()',
            session='active-cancel', task_id='browser-fixture'))
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        work = pool.submit(active_call)
        for _ in range(100):
            pid = streams.run_in(env, ['cat', '/workspace/browser-active-child'], timeout=10)
            if pid.returncode == 0:
                break
            time.sleep(.1)
        else:
            raise AssertionError('Active browser child did not start')
        key = browser._backend_cache_key('browser-fixture', 'active-cancel')
        owner = remote._sessions[key].process
        set_interrupt(True, thread_id=worker['tid'])
        try:
            stopped = work.result(timeout=20)
            assert 'interrupted' in stopped.get('error',''), stopped
            owner.wait(timeout=20)
            probe = streams.run_in(env, ['python3', '-c',
                'from pathlib import Path; p=Path("/proc/' + pid.stdout.decode().strip() + '/status"); '
                'assert not p.exists() or "State:\\tZ" in p.read_text(); '
                'assert not Path("/workspace/browser-cancel-failed").exists()'])
            assert probe.returncode == 0, probe.stderr.decode()
        finally:
            set_interrupt(False, thread_id=worker['tid'])
    assert 'typed-in-executor' in run('print(js("document.title"))')['output']
    # Native timeout likewise stops the affected session; completed workspace files survive.
    timed = decoded(browser.browser_exec('import time; time.sleep(30)', session='timeout', timeout_s=5))
    assert 'timed out' in timed.get('error',''), timed
    retry = decoded(browser.browser_exec('print("retry-after-timeout")', session='timeout'))
    assert retry.get('output','').strip() == 'retry-after-timeout', retry
    # Explicit unsupported settings fail before any model code or external route.
    from tools import browser_session_cloud
    section = browser_session_cloud.browser_section
    try:
        for setting in ({'cloud_provider':'browser-use'}, {'engine':'lightpanda'},
                        {'use_real_profile':True}, {'cdp_url':'http://10.203.83.3:8337'}):
            browser_session_cloud.browser_section = lambda: {**section(), **setting}
            refused = decoded(browser.browser_exec('raise AssertionError("must not execute")'))
            assert refused.get('error') and 'executor Chromium' in refused['error'], refused
    finally:
        browser_session_cloud.browser_section = section
    # Core qualifies public Tor for this exact namespace. Here prove native
    # Python networking/placement and forbidden peers without a second public
    # DNS/TLS dependency in every browser and webapp run.
    network = run('import os,urllib.request,socket\n'
                  f'assert os.readlink("/proc/self/ns/net")=={executor_netns!r}\n'
                  f'assert b"executor-browser-fixture" in urllib.request.urlopen("http://127.0.0.1:{port}/",timeout=10).read()\n'
                  'for address in [("10.203.83.3",8337),("10.203.85.2",80),("192.168.65.2",80),("169.254.169.254",80)]:\n'
                  ' s=socket.socket(); s.settimeout(1)\n'
                  ' try: s.connect(address)\n'
                  ' except OSError: pass\n'
                  ' else: raise AssertionError(address)\n'
                  ' finally: s.close()\n'
                  'print("executor-network-only")', name='network')
    assert 'executor-network-only' in network['output'], network
    # Exercise EOF specifically while real native daemon startup is pending.
    # A fixture-only rendezvous delays startup; production has no such hook.
    child_env = json.loads(run('import os,json\nprint(json.dumps(dict(os.environ)))')['output'])
    for key, suffix in [('BH_HOME',''), ('BH_CONFIG_DIR',''), ('BH_RUNTIME_DIR','/r'), ('BH_TMP_DIR','/t')]:
        child_env[key] = '/tmp/bh/startup-cancel' + suffix
    child_env['BU_NAME'] = 'startup-cancel'
    runner = Path(remote.__file__).with_name('browser_use_executor_runner.py').read_text()
    shot = Path(remote.__file__).with_name('browser_use_shot.py').read_text()
    delayed = """import time
from pathlib import Path
from browser_harness import admin
start=admin.ensure_daemon
def delayed():
 Path('/workspace/browser-startup-entered').touch()
 while not Path('/workspace/browser-startup-continue').exists(): time.sleep(.05)
 start()
admin.ensure_daemon=delayed
""" + runner + '\nmain(' + repr(shot) + ')'
    owner = streams.open_stream(env, ['env', '-i', *(k+'='+v for k,v in child_env.items()),
                                '/opt/browser-harness/bin/python', '-u', '-c', delayed])
    owner.stdin.write((json.dumps({'code':'from pathlib import Path; Path("/workspace/browser-startup-code-ran").touch()',
                                  'workspace':child_env['BH_AGENT_WORKSPACE'], 'setup':'', 'timeout':30})+'\n').encode())
    owner.stdin.flush()
    for _ in range(100):
        entered = streams.run_in(env, ['test','-f','/workspace/browser-startup-entered'])
        if entered.returncode == 0:
            break
        time.sleep(.1)
    else:
        raise AssertionError('Startup cancellation rendezvous not reached')
    owner.stdin.close()
    assert streams.run_in(env, ['touch','/workspace/browser-startup-continue']).returncode == 0
    owner.wait(timeout=90)
    startup = json.loads(owner.stdout.readline())
    assert 'not launched' in startup.get('error',''), startup
    assert streams.run_in(env, ['test','!','-e','/workspace/browser-startup-code-ran']).returncode == 0
    # Abrupt gateway-worker death closes SSH via the native owner-death supervisor.
    program = ('import json,os; from tools.browser_use_cli import browser_exec; '
               'r=browser_exec(' + repr('import os,json\nfrom browser_harness import _ipc,admin\n'
                   'raw=_ipc.pid_path(admin.NAME).read_text()\n'
                   'pid=json.loads(raw)["pid"] if raw.startswith("{") else int(raw)\n'
                   'print(json.dumps({"owner":os.getppid(),"daemon":pid}))') +
               ',session="owner-death",task_id="owner-death"); '
               'print(r,flush=True); os._exit(0)')
    result = subprocess.run([sys.executable, '-c', program], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    identities = json.loads(json.loads(result.stdout)['output'])
    for _ in range(100):
        gone = streams.run_in(env, ['python3', '-c',
            'from pathlib import Path; ids=' + repr(list(identities.values())) + '; '
            'assert all(not (p:=Path(f"/proc/{i}/status")).exists() or "State:\\tZ" in p.read_text() for i in ids)'])
        if gone.returncode == 0:
            break
        time.sleep(.1)
    else:
        raise AssertionError('Remote owner/daemon survived gateway owner death')
    # Native cleanup tears down the corresponding persistent SSH/harness owner.
    key = browser._backend_cache_key('browser-fixture', 'fixture')
    owner = remote._sessions[key].process
    from tools.browser_session_lifecycle import cleanup_single_session
    cleanup_single_session(key)
    owner.wait(timeout=20)
    assert key not in remote._sessions
    print('PASS: remote Python/child placement, Chromium DOM/type/download/capture, named/unnamed sessions, concurrent startup, '
          'screenshot staging/vision, native cache sync, takeover, active/startup cancellation, timeout/retry, daemon crash, '
          'owner death, executor namespace/forbidden paths and native cleanup')
finally:
    lease.release('browser-fixture-human')
    remote.close()
    server.kill()
    server.wait()
