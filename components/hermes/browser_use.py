"""Deployment browser_exec route: one native harness session over executor SSH."""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import threading
import time
import uuid
from contextlib import suppress


@dataclass
class Session:
    env: object
    process: subprocess.Popen
    home: str
    endpoint: str
    browser: dict
    lock: object = field(default_factory=threading.Lock)


_sessions = {}
_key_locks = {}
# Lock hierarchy: _key_lock(key) -> _lock and session.lock -> _lock. Never acquire
# _key_lock(key) or session.lock while holding _lock, and keep slow remote probes
# and process spawns outside _lock so one cold session never stalls other keys.
_lock = threading.Lock()
_PROBE_TIMEOUT_S = 4.0


def _key_lock(key):
    with _lock:
        return _key_locks.setdefault(key, threading.Lock())


def _policy():
    from hermes_bootstrap import PRIVATE_HERMES_COMPUTER_USE
    from tools.browser_session_cloud import browser_section
    from tools.browser_session_cdp import get_cdp_override_raw
    cfg = browser_section()
    if not PRIVATE_HERMES_COMPUTER_USE:
        raise RuntimeError('Browser use requires COMPUTER_USE_ENABLED=true and the desktop executor')
    if (get_cdp_override_raw() or any(os.environ.get(k) for k in ('BU_CDP_URL', 'BU_CDP_WS')) or
            cfg.get('cloud_provider') not in ('local', '', None) or
            cfg.get('engine', 'auto') not in ('auto', 'chrome', '', None) or
            cfg.get('use_real_profile') or cfg.get('user_data_dir') or cfg.get('executable_path')):
        raise RuntimeError('This deployment supports only executor Chromium; remove cloud, external CDP, '
                           'real-profile or alternate-browser settings')


def _probe_harness(env, *, probe_timeout=_PROBE_TIMEOUT_S, deadline=None):
    from tools.bot_desktop import sandbox_host
    from tools.environments import streams

    cached = getattr(env, '_private_browser_harness', None)
    if cached is not None:
        return cached
    probe = streams.run_in(
        env, ['/opt/browser-harness/bin/python', '-c', 'import browser_harness.run; import browser_harness.daemon'],
        timeout=sandbox_host.probe_budget(deadline, probe_timeout))
    ok = probe.returncode == 0
    with suppress(AttributeError, TypeError):
        env._private_browser_harness = ok
    return ok


def available(*, deadline=None):
    from tools.bot_desktop import placement, sandbox_host
    from hermes_cli.private_computer_use import available as desktop_available
    try:
        _policy()
        if deadline is None:
            deadline = time.monotonic() + sandbox_host._DISCOVERY_BUDGET_S
        if not desktop_available(deadline=deadline):
            return False
        env = placement.terminal_environment(create=True)
        if env is None:
            return False
        return _probe_harness(env, probe_timeout=_PROBE_TIMEOUT_S, deadline=deadline)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return False


def close(cache_key=None, home_key=None, session_info=None, owner=None):
    from hermes_cli.process_identity import release_process_group_once_empty
    with _lock:
        keys = [key for key, value in _sessions.items()
                if (cache_key is None or key == cache_key) and
                (home_key is None or value.home == home_key) and
                (session_info is None or value.browser is session_info) and
                (owner is None or value is owner)]
        sessions = [_sessions.pop(key) for key in keys]
    for session in sessions:
        proc = session.process
        if proc.stdin:
            # A failed flush can leave a buffered write that close retries.
            with suppress(BrokenPipeError):
                proc.stdin.close()  # Remote EOF stops its CLI group and native daemon.
        # Native daemon shutdown can drain in-flight CDP. Do not kill the SSH
        # owner early and thereby lose the executor's EOF cleanup channel.
        threading.Thread(target=_reap, args=(proc, release_process_group_once_empty), daemon=True).start()


def _reap(proc, release):
    proc.wait()
    try:
        proc.stdout.close()
    finally:
        release(proc.pid, timeout=0)


def _validated_endpoint(key, env, info, expected=None):
    from tools.bot_desktop import runtime, sandbox_host
    from tools.environments import streams
    from tools.browser_session_lifecycle import cleanup_single_session
    from tools.browser_session_sandbox import GONE, _live_devtools, _shared_key

    if not runtime.owns_tool_sandbox(env):
        raise RuntimeError('The browser executor changed; start a browser on the recorded desktop')
    user = sandbox_host._user_for(env)
    udd = sandbox_host.browser_profile_dir(env)
    if info.get('launcher_key') != _shared_key(env, udd):
        raise RuntimeError('The browser executor changed; retry the command')
    found = _live_devtools(env, user, udd)
    if found is None:
        raise RuntimeError('Executor Chromium has no usable DevTools endpoint')
    if found is not GONE:
        port, path = found
        endpoint = f'ws://127.0.0.1:{port}{path}'
        forwarded = streams.forward_port(env, port, user=user)
        if (expected is None or endpoint == expected) and info.get('cdp_url') == f'ws://127.0.0.1:{forwarded}{path}':
            return endpoint
    cleanup_single_session(key, expected=info)
    raise RuntimeError('Executor Chromium changed during setup; retry the command')


def _session(key):
    from hermes_constants import hermes_home_key
    from hermes_cli.process_identity import own_process_groups
    from tools.bot_desktop import runtime
    from tools.environments import streams
    from tools.browser_session import get_session_info
    with _key_lock(key):
        # Native session lifecycle and startup policy own the shared Chromium.
        info = get_session_info(key)
        env, _ = runtime.tool_sandbox()
        with _lock:
            current = _sessions.get(key)
            if current and current.process.poll() is None and current.env is env and current.browser is info:
                return current
        endpoint = _validated_endpoint(key, env, info)
        close(cache_key=key)
        # A replacement must never share IPC with an owner still draining its
        # native shutdown after cancellation.
        digest = uuid.uuid4().hex[:20]
        root = '/tmp/bh/' + digest
        child_env = {
            'HOME': '/home/runner', 'PATH': '/opt/browser-harness/bin:/usr/local/bin:/usr/bin:/bin',
            'LANG': 'C.UTF-8', 'BH_HOME': root, 'BH_CONFIG_DIR': root,
            'BH_RUNTIME_DIR': root + '/r', 'BH_TMP_DIR': root + '/t',
            'BH_AGENT_WORKSPACE': root, 'BU_NAME': 's' + digest,
            'BH_DOWNLOAD_DIR': '/workspace/browser-use/downloads',
            'BU_CDP_WS': endpoint, 'BU_AUTOSPAWN': '', 'BH_REQUIRE_EXISTING_DAEMON': '1',
            'BH_TELEMETRY': '0', 'BROWSER_HARNESS_TELEMETRY': '0', 'ANONYMIZED_TELEMETRY': 'false',
            'BH_UPDATE_CHECK': '0', 'BH_RECORD': '0',
            'DISPLAY': runtime.published_env()['DISPLAY'], 'XDG_RUNTIME_DIR': '/tmp/hermes-runtime',
        }
        argv = ['env', '-i', *(f'{k}={v}' for k, v in child_env.items()),
                '/opt/browser-harness/bin/python', '-u', '/opt/private-hermes/browser-session.py']
        command = streams.remote_command(env, argv)
        if command is None:
            raise RuntimeError('Executor SSH stream is unavailable')
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        own_process_groups([proc.pid])
        current = Session(env, proc, hermes_home_key(), endpoint, info)
        with _lock:
            _sessions[key] = current
        return current


def _task_workspace(home, task_id):
    identity = json.dumps([home, str(task_id or 'default')]).encode()
    return '/workspace/browser-use/' + hashlib.sha256(identity).hexdigest()[:20]


def execute(code, session='', timeout_s=300, task_id=None, local=False):
    from agent.redact import redact_sensitive_text
    from tools.registry import tool_error, tool_result
    from tools import browser_use_cli as native
    from tools.browser_session import run_fenced_dispatch
    from tools.browser_session_lifecycle import update_session_activity
    from tools.interrupt import is_interrupted
    try:
        _policy()
        if local:
            raise RuntimeError('Real-profile browser routing is unavailable; use executor Chromium')
        if not isinstance(code, str) or not code.strip():
            raise RuntimeError('No Python code provided')
        if session and not native._SESSION_RE.fullmatch(session):
            raise RuntimeError('Invalid session name: use 1-64 letters, digits, dashes or underscores')
        if blocked := native._code_url_verdict(code, force_local=True).blocked:
            raise RuntimeError(blocked)
        key = native._backend_cache_key(task_id, session, sidecar=True)

        def dispatch(check_lease):
            if is_interrupted():
                raise RuntimeError('Browser execution interrupted before launch')
            current = _session(key)
            workspace = _task_workspace(current.home, task_id)

            def check_dispatch():
                if is_interrupted():
                    raise RuntimeError('Browser execution interrupted before launch')
                check_lease()

            with current.lock:
                proc = current.process
                check_dispatch()
                _validated_endpoint(key, current.env, current.browser, current.endpoint)
                check_dispatch()
                try:
                    proc.stdin.write((json.dumps({'code': code, 'setup': native._OWN_TAB_PREAMBLE if session else '',
                                                  'workspace': workspace,
                                                  'timeout': native._clamp_timeout(timeout_s)}) + '\n').encode())
                    proc.stdin.flush()
                    # Raw reads avoid buffered readline hiding an already-received response.
                    data = bytearray()
                    touched = 0.0
                    while b'\n' not in data:
                        if time.monotonic() - touched >= 1:
                            from tools.bot_desktop import runtime
                            update_session_activity(key)
                            runtime.touch_activity()
                            touched = time.monotonic()
                        if is_interrupted():
                            raise RuntimeError('Browser execution interrupted; already-issued actions may have '
                                               'completed. Do not replay automatically.')
                        if not select.select([proc.stdout], [], [], 0.2)[0]:
                            continue
                        chunk = os.read(proc.stdout.fileno(), 65536)
                        if not chunk:
                            raise RuntimeError('Browser SSH session ended; check executor SSH and the '
                                               'image-built harness dependencies. Action outcome may be unknown. '
                                               'Do not replay automatically.')
                        data.extend(chunk)
                    line, sep, trailing = bytes(data).partition(b'\n')
                    if not sep or trailing:
                        raise RuntimeError('Browser SSH session returned malformed output; '
                                           'action outcome may be unknown. Do not replay automatically.')
                    response = json.loads(line)
                    if 'error' in response:
                        raise RuntimeError(response['error'])
                    result = {'success': response['returncode'] == 0, 'exit_code': response['returncode'],
                              'output': redact_sensitive_text(response['stdout'], force=True),
                              'workspace': workspace, 'downloads': '/workspace/browser-use/downloads'}
                    if session:
                        result['session'] = session
                    if response.get('stderr'):
                        result['stderr'] = redact_sensitive_text(response['stderr'], force=True)[:native._STDERR_CAP_CHARS]
                    if response.get('screenshot'):
                        from tools.image_source import _MAX_INGEST_BYTES
                        from hermes_constants import get_hermes_home
                        target = Path(get_hermes_home()) / 'cache' / 'browser-use' / 'screenshots'
                        target.mkdir(parents=True, exist_ok=True)
                        target = target / (uuid.uuid4().hex + '.png')
                        try:
                            current.env.fetch_file(response['screenshot'], target, max_bytes=_MAX_INGEST_BYTES)
                        except Exception:
                            target.unlink(missing_ok=True)
                            raise
                        result['screenshot_path'] = str(target)
                        attached = native._native_screenshot_result(result, str(target))
                        if attached is not None:
                            return attached
                    return result
                except BaseException:
                    close(cache_key=key, owner=current)
                    raise

        result = run_fenced_dispatch(dispatch)
        return result if result.get('_multimodal') else tool_result(result)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        return tool_error(redact_sensitive_text(str(error), force=True))


def schema_overrides():
    from tools import browser_use_cli as native
    # No real-profile `local` parameter or cloud/vault installation advice.
    schema = native._description_header() + native._HELPERS_DIGEST
    schema += '\nThis deployment runs Python and Chromium in the SSH executor. Named sessions share its browser profile.'
    parameters = dict(native.BROWSER_EXEC_SCHEMA['parameters'])
    properties = dict(parameters['properties'])
    properties['session'] = {'type': 'string', 'description':
        'Named browser session with its own tab and daemon; cookies and downloads are shared. '
        'Reuse the name for related calls; omit for the current task\'s default session.'}
    parameters['properties'] = properties
    return {'description': schema, 'parameters': parameters}
