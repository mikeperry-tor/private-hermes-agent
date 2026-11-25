"""Ordinary terminal runtime checks through authenticated native WebSockets/bridge."""
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import time
from urllib.parse import quote

from playwright.sync_api import expect, sync_playwright
import smoke
from webapp_smoke import wait_ready

LOCAL = 'http://127.0.0.1:19120'
PUBLIC = 'https://webapp-test.example.ts.net:10000'


def model_check(code):
    # The production WebApp runs model tooling as Hermes, even though its s6
    # container entrypoint is root. Never create native PM state as root in tests.
    return smoke.execute('hermes', '/opt/hermes/.venv/bin/python', '-c', code, user='10000:10000')


def open_shell(page, cwd=None, attach=None, environment=None, *, action=None, startup=False, acknowledge=True):
    return page.evaluate('''async (args) => {
      const response = await fetch('/api/webapp/socket-ticket?socket=host-terminal',{method:'POST'});
      if (!response.ok) throw new Error('ticket '+response.status);
      const url = new URL('/api/host-terminal', location.origin.replace(/^http/,'ws'));
      url.searchParams.set('ticket',(await response.json()).ticket);
      const {acknowledge, ...query} = args;
      for (const [key,value] of Object.entries(query)) if(value!==null) url.searchParams.set(key,value);
      const state = window.testShell = {output:'', meta:null, closed:null, preparing:false, ackStartup:false};
      const ws = state.ws = new WebSocket(url);
      ws.binaryType='arraybuffer';
      ws.onmessage = e => {
        if(typeof e.data==='string' && e.data.startsWith('\\0HERMES_TERMINAL_META:')) {
          const frame=JSON.parse(e.data.slice('\\0HERMES_TERMINAL_META:'.length));
          if(frame.preparing) {
            state.preparing=true;
            state.ackStartup=frame.ackStartup===true;
          } else {
            state.meta=frame;
            if (state.ackStartup && acknowledge && frame.terminalId) {
              ws.send('\\0HERMES_TERMINAL_META:'+JSON.stringify({attached:frame.terminalId}));
            }
          }
        } else state.output += typeof e.data==='string' ? e.data : new TextDecoder().decode(e.data);
      };
      ws.onclose=e=>state.closed={code:e.code,reason:e.reason};
    }''', {'cwd': cwd, 'attach': attach, 'environment': environment, 'action': action,
           'startup': '1' if startup else None, 'acknowledge': acknowledge})


def metadata(page):
    page.wait_for_function('() => testShell.meta !== null || testShell.closed !== null', timeout=30000)
    state = page.evaluate('({meta:testShell.meta, closed:testShell.closed, output:testShell.output})')
    assert state['meta'] is not None, state
    return state['meta']


def command(page, command):
    token = secrets.token_hex(10)
    page.evaluate("args => testShell.ws.send(args.command + \"; printf '\\n__DONE_%s__\\n' '\" + args.token + \"'\\n\")",
                  {'command': command, 'token': token})
    try:
        page.wait_for_function('token => testShell.output.includes("__DONE_"+token+"__")', arg=token, timeout=30000)
    except Exception:
        print(page.evaluate('({output:testShell.output,closed:testShell.closed})'), flush=True)
        raise
    return page.evaluate('testShell.output')


def close_shell(page, meta):
    page.evaluate('testShell.ws.close()')
    page.wait_for_function('() => testShell.closed !== null')
    page.evaluate('''async token => {
      const r=await fetch('/api/webapp/socket-ticket?socket=host-terminal',{method:'POST'});
      const u=new URL('/api/host-terminal',location.origin.replace(/^http/,'ws'));
      u.searchParams.set('ticket',(await r.json()).ticket);u.searchParams.set('attach',token);u.searchParams.set('action','close');
      await new Promise((resolve,reject)=>{const w=new WebSocket(u); w.onclose=e=>e.code===1000?resolve():reject(new Error(e.reason));w.onerror=reject;});
    }''', meta['terminalId'])


def denied(page, cwd=None, reason="terminal"):
    open_shell(page, cwd=cwd)
    page.wait_for_function('() => testShell.closed !== null', timeout=30000)
    state = page.evaluate('({meta:testShell.meta, output:testShell.output, closed:testShell.closed})')
    assert state['meta'] is None, state
    assert state['closed']['code'] == 4411 and reason in state['closed']['reason'].lower(), state


def cancel_unacknowledged_code_shell(page):
    """Drop the socket after metadata was sent but before confirming receipt."""
    open_shell(page, environment='executor', startup=True, acknowledge=False)
    meta = metadata(page)
    assert page.evaluate('testShell.ackStartup')
    marker = '/tmp/terminal-receipt-' + secrets.token_hex(8)
    command(page, f"printf '%s' $$ > {marker}")
    pid = int(smoke.python('executor', f'from pathlib import Path; print(Path({marker!r}).read_text())').stdout)
    page.evaluate('testShell.ws.close()')
    page.wait_for_function('() => testShell.closed !== null')
    smoke.eventually(lambda: smoke.python('executor',
        f"import os; assert not os.path.exists('/proc/{pid}'), 'unacknowledged terminal is still alive'"))
    open_shell(page, attach=meta['terminalId'])
    page.wait_for_function('() => testShell.closed !== null')
    assert page.evaluate('testShell.meta === null && testShell.closed.code === 4410')
    print('PASS: Code socket loss before acknowledging the token reaps the terminal', flush=True)


def cancel_starting_code_tab(page):
    """Hold the remote cwd probe after SSH login, then close through the real bridge."""
    marker = 'terminal-probe-' + secrets.token_hex(8)
    probe = '/tmp/' + marker
    fixture_home = '/home/runner/.bashrc'
    gate = (
        f'\nif [[ $BASH_EXECUTION_STRING == *{marker}* ]]; then\n'
        f'  touch {probe}/entered\n'
        f'  until [[ -f {probe}/release ]]; do sleep 0.05; done\n'
        '  exit 2\n'
        'fi\n'
    )
    smoke.python('executor', f"""from pathlib import Path
root = Path({probe!r})
root.mkdir()
bashrc = Path({fixture_home!r})
original = bashrc.read_bytes() if bashrc.exists() else None
if original is not None:
    (root / 'original-bashrc').write_bytes(original)
bashrc.write_bytes({gate.encode()!r} + (original or b''))
""")
    try:
        page.evaluate("""path => {
          const api = window.hermesDesktop.terminal;
          window.fixtureTerminalStartup = api.start({cwd:path, restoreKey:'held-code-startup'})
            .then(() => 'published', error => error.message);
        }""", probe)
        smoke.eventually(lambda: smoke.python('executor',
            f'from pathlib import Path; assert (Path({probe!r}) / "entered").is_file()'))
        find_probe = rf"""from pathlib import Path
live = []
for process in Path('/proc').glob('[0-9]*/cmdline'):
    try:
        argv = process.read_bytes().split(b'\0')
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        continue
    if argv[0] == b'/usr/bin/ssh' and any({marker.encode()!r} in arg for arg in argv[1:]):
        live.append(process.parent.name)
"""
        smoke.python('hermes', find_probe + 'assert live')
        assert page.evaluate("() => window.hermesDesktop.terminal.closeSaved('held-code-startup')")
        assert 'cancelled' in page.evaluate('window.fixtureTerminalStartup')
        smoke.eventually(lambda: smoke.python('hermes', find_probe + 'assert not live'))
    finally:
        smoke.python('executor', f"""from pathlib import Path
root = Path({probe!r})
(root / 'release').touch()
bashrc = Path({fixture_home!r})
backup = root / 'original-bashrc'
if backup.exists():
    bashrc.write_bytes(backup.read_bytes())
    backup.unlink()
else:
    bashrc.unlink()
""")
    print('PASS: closing a starting Code tab reaps its connected SSH probe', flush=True)


def change_identity(action):
    """Mutate only nonce-marked fixture keys through the native offline setup mount.

    Rootless Podman maps runner-owned bind files to subordinate host UIDs, so
    the host user must not read/write them directly. No private key is printed.
    """
    script = '''import hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
root=Path('/persistent-data')
assert (root/'.test-storage').is_file()
folder=root/'ssh/agent'
key,known=folder/'id_ed25519',folder/'known_hosts'
paths=(key,known)
action=sys.argv[1]
if action=='missing':
    for p in paths: p.with_name(p.name+'.terminal-test-backup').write_bytes(p.read_bytes())
    key.unlink()
elif action in ('restore','finish'):
    for p in (paths if action=='finish' else (key,)):
        backup=p.with_name(p.name+'.terminal-test-backup')
        p.write_bytes(backup.read_bytes())
        if action=='finish': backup.unlink()
elif action=='host-missing':
    known.unlink()
elif action in ('rejected','host'):
    with tempfile.TemporaryDirectory() as tmp:
        wrong=Path(tmp)/'key'
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(wrong)],check=True)
        if action=='rejected': key.write_bytes(wrong.read_bytes())
        else: known.write_bytes(b'[10.203.82.3]:2222 '+wrong.with_suffix('.pub').read_bytes())
else: raise AssertionError(action)
for p in paths:
    if p.exists(): os.chown(p,10000,10000); p.chmod(0o600)
print(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in paths}))
'''
    result = smoke.compose('run', '--rm', '-T', '--no-deps', '--entrypoint',
                           '/opt/hermes/.venv/bin/python', 'setup', '-c', script, action)
    expected = json.loads(result.stdout)
    check = ('import hashlib; from pathlib import Path; '
             'p=Path("/run/agent-ssh"); '
             'actual={name:hashlib.sha256((p/name).read_bytes()).hexdigest() if (p/name).exists() else None for name in '
             + repr(list(expected)) + '}; assert actual==' + repr(expected))
    for attempt in range(50):
        if smoke.python('hermes', check, check=False).returncode == 0:
            return
        time.sleep(.1)
    raise AssertionError('Changed fixture SSH material did not become visible')


def check_model_host_key(*, trusted):
    # A probe-only environment owns a fresh SSH master and cannot reuse an
    # already authenticated model shell when the fixture changes known_hosts.
    model_check(f"""from tools.environments.ssh import SSHEnvironment
from tools.environments.base import EnvironmentConnectionError
try:
    env = SSHEnvironment("10.203.82.3", "runner", port=2222,
                         key_path="/run/agent-ssh/id_ed25519", probe_only=True, ssh_config="/etc/ssh/ssh_config.d/99-private-hermes.conf")
except EnvironmentConnectionError:
    assert not {trusted!r}, "the configured host key was refused"
else:
    env.cleanup()
    assert {trusted!r}, "SSH accepted a connection without its configured host key"
""")


def check_model_terminal_read(page, mode):
    """Use the renderer's selected tab and the model tool through authenticated chat."""
    streams = []

    def watch(socket):
        if '/api/host-terminal?' in socket.url:
            output = bytearray()
            streams.append(output)

            def append(frame):
                if isinstance(frame, bytes):
                    output.extend(frame)

            socket.on('framereceived', append)

    page.on('websocket', watch)
    page.get_by_text('ready', exact=True).first.wait_for(timeout=30000)
    editor = page.locator('[data-slot="composer-rich-input"]').first
    send = page.get_by_role('button', name='Send', exact=True).first
    editor.fill('qualification-stream')
    send.click()
    page.get_by_text('PRIVATE-CHAT-STREAM-OK', exact=False).first.wait_for(timeout=30000)
    page.keyboard.press('Control+Backquote')
    tabs = page.get_by_role('tablist', name='Terminals')
    terminal_input = page.locator('[data-interactive-terminal]:not(.invisible) .xterm-helper-textarea')
    prefix = mode.upper()
    first_history, first_visible, second = [f'{prefix}-{secrets.token_hex(10)}' for _ in range(3)]

    def wait_for_stream(index, marker=None):
        for _ in range(300):
            if len(streams) > index and streams[index] and (marker is None or marker.encode() in streams[index]):
                return
            page.wait_for_timeout(100)
        raise AssertionError('Terminal did not start or print its fixture marker')

    def shell(index, command, marker):
        wait_for_stream(index)
        terminal_input.first.focus()
        page.keyboard.insert_text(command)
        page.keyboard.press('Enter')
        wait_for_stream(index, marker)

    def print_marker(marker):
        label, nonce = marker.split('-', 1)
        return f"printf '%s-%s\\n' {label} {nonce}"

    shell(0, f"{print_marker(first_history)}; seq 1 80; {print_marker(first_visible)}", first_visible)
    previous_tab = tabs.get_by_role('tab').first
    tabs.get_by_role('button', name='New terminal', exact=True).click()
    expect(tabs.get_by_role('tab')).to_have_count(2)
    shell(1, print_marker(second), second)
    results = page.get_by_text(re.compile(r'^PRIVATE-TERMINAL-READ-(OK|WRONG|TOOL-MISSING)$'))

    def read(index, marker, other_tab, excluded, view):
        editor.fill(f'qualification-terminal-read {marker} {other_tab} {excluded} {view}')
        send.click()
        expect(results).to_have_count(index, timeout=45000)
        assert results.nth(index - 1).inner_text() == 'PRIVATE-TERMINAL-READ-OK'

    read(1, second, first_visible, first_history, 'viewport')
    previous_tab.click()
    read(2, first_visible, second, first_history, 'viewport')
    read(3, first_history, second, first_visible, 'scrollback')
    print(f'PASS: {mode} model terminal read checks the selected tab for viewport and scrollback', flush=True)

    if mode == 'agent':
        marker = f'AGENT-{secrets.token_hex(10)}'
        editor.fill(f'qualification-terminal-selection {marker}')
        shell(0, f"printf '\\033[2J\\033[H'; {print_marker(marker)}", marker)
        page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
        screen = page.locator('[data-interactive-terminal]:not(.invisible) .xterm-screen').first
        box = screen.bounding_box()
        assert box is not None
        page.mouse.move(box['x'] + 2, box['y'] + 5)
        page.mouse.down()
        page.mouse.move(box['x'] + min(box['width'] - 3, 360), box['y'] + 55, steps=8)
        page.mouse.up()
        page.get_by_role('button', name=re.compile(r'^Add to chat')).click()
        editor.locator('[data-ref-kind="terminal"]').wait_for(timeout=10000)
        send.click()
        sent = page.get_by_text(re.compile(r'^PRIVATE-TERMINAL-SELECTION-(OK|WRONG)$'))
        sent.wait_for(timeout=30000)
        assert sent.inner_text() == 'PRIVATE-TERMINAL-SELECTION-OK'
        print('PASS: operator can select Agent terminal output and send it to chat', flush=True)


def run(password_path, mode):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            '--host-resolver-rules=MAP webapp-test.example.ts.net 127.0.0.1', '--no-proxy-server'])
        try:
            for origin in (LOCAL, PUBLIC):
                context = browser.new_context(ignore_https_errors=True)
                page = context.new_page()
                page.goto(origin + '/login')
                page.locator('input[name=username]').fill('admin')
                page.locator('input[name=password]').fill(Path(password_path).read_text())
                page.locator('button[type=submit]').click()
                page.wait_for_url(lambda u: '/login' not in u)
                page.wait_for_function('() => window.hermesDesktop?.terminal !== undefined')
                receiver_mode = 'executor' if mode == 'code' else 'gateway'
                assert page.evaluate('window.__HERMES_TERMINAL_ENVIRONMENT__') == receiver_mode
                if origin == LOCAL:
                    check_model_terminal_read(page, mode)
                open_shell(page, environment='gateway' if mode == 'code' else 'executor', action='start')
                page.wait_for_function('() => testShell.closed !== null', timeout=30000)
                assert page.evaluate('testShell.meta === null && testShell.closed.reason.includes("environment changed")')
                # The held-probe fixture uses Debian Bash's noninteractive
                # sshd startup hook. Lean Alpine still qualifies normal
                # startup, strict host keys, and the full terminal lifecycle.
                if mode == 'code' and origin == LOCAL and os.environ.get('COMPUTER_USE_ENABLED') == 'true':
                    cancel_starting_code_tab(page)
                if mode == 'code' and origin == LOCAL:
                    cancel_unacknowledged_code_shell(page)
                open_shell(page, environment=receiver_mode, action='start', startup=True)
                meta = metadata(page)
                assert meta['environment'] == receiver_mode and meta['shell'].startswith(mode.title() + ' · '), meta
                assert page.evaluate('testShell.preparing && testShell.ackStartup') is True
                if mode == 'code':
                    assert meta['cwd'] == '/workspace', meta
                    output = command(page, "printf 'USER-%s\\n' \"$(id -u)\"; printf 'browser-terminal\\n' > /workspace/webapp-terminal-proof; pwd")
                    assert 'USER-10000' in output and '/workspace' in output
                    out = command(page, "test -z \"$AGENT_ONLY_SENTINEL\" && test ! -e /opt/data/config.yaml && test ! -e /run/agent-ssh/id_ed25519 && test ! -e /run/webapp/auth.json && test ! -e /var/lib/x402 && printf 'ISOLATED-%s\\n' 'OK'")
                    assert 'ISOLATED-OK' in out, out
                    capability_check = """from pathlib import Path
s=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert all(int(s[k].strip(),16)==0 for k in ('CapEff','CapPrm','CapInh','CapAmb')),s
assert s['NoNewPrivs'].strip()=='1',s
print('CAPABILITIES-'+'ZERO')
"""
                    assert 'CAPABILITIES-ZERO' in command(page, 'python3 -c ' + shlex.quote(capability_check))
                    model_check("from tools.terminal_tool import terminal_tool; r=terminal_tool(command=" + repr('python3 -c ' + shlex.quote(capability_check)) + "); assert 'CAPABILITIES-ZERO' in str(r),r")
                    denied_network = """import socket
for host, port in (('10.203.83.3',8337),('10.203.85.2',9120),('10.203.84.10',8000),('169.254.169.254',80),('192.168.1.1',80)):
    try: socket.create_connection((host,port),timeout=.5)
    except OSError: pass
    else: raise AssertionError((host,port))
print('POLICY-'+'OK')
"""
                    out = command(page, 'python3 -c ' + shlex.quote(denied_network))
                    assert 'POLICY-OK' in out, out
                    smoke.python('executor', "from pathlib import Path; assert Path('/workspace/webapp-terminal-proof').read_text().strip()=='browser-terminal'")
                    smoke.python('hermes', "from pathlib import Path; assert not Path('/workspace/webapp-terminal-proof').exists()")
                    file = page.evaluate("async () => {const r=await fetch('/api/fs/read-text?path=/workspace/webapp-terminal-proof');return {status:r.status,text:await r.text()}}")
                    assert file['status'] == 200 and 'browser-terminal' in file['text'], file
                    # Same backend used by model commands reads the file.
                    model_check("from tools.terminal_tool import terminal_tool; import json; r=terminal_tool(command='cat /workspace/webapp-terminal-proof'); assert 'browser-terminal' in str(r),r")
                else:
                    smoke.python('executor', "from pathlib import Path; assert Path('/workspace/webapp-terminal-proof').read_text().strip()=='browser-terminal'")
                    output = command(page, "printf 'browser-terminal\\n' > /tmp/webapp-agent-terminal-proof; test -f /opt/data/config.yaml && printf 'AGENT-%s\\n' 'STATE'")
                    assert 'AGENT-STATE' in output
                    smoke.python('hermes', "from pathlib import Path; assert Path('/tmp/webapp-agent-terminal-proof').read_text().strip()=='browser-terminal'")
                    smoke.python('executor', "from pathlib import Path; assert not Path('/tmp/webapp-agent-terminal-proof').exists()")
                # Native detach/reattach retains shell PID and replay.
                replay_marker = 'REPLAY-' + secrets.token_hex(10)
                output = command(page, "printf '%s' $$ > /tmp/webapp-terminal-pid; printf 'REPLAY-%s\\n' " +
                                 shlex.quote(replay_marker.removeprefix('REPLAY-')))
                assert replay_marker in output, output
                page.evaluate('testShell.ws.close()')
                page.wait_for_function('() => testShell.closed !== null')
                open_shell(page, attach=meta['terminalId'])
                resumed = metadata(page)
                assert resumed['reconnected'] and resumed['terminalId'] == meta['terminalId']
                # Metadata precedes replay. Check actual output, independent of
                # readline's presentation of an earlier command being typed.
                page.wait_for_function('marker => testShell.output.includes(marker)',
                                       arg=replay_marker, timeout=30000)
                output = command(page, 'test "$$" = "$(cat /tmp/webapp-terminal-pid)" && ' +
                                 "printf 'REATTACHED-%s\\n' 'OK'")
                assert 'REATTACHED-OK' in output, output
                page.evaluate("testShell.ws.send('\\x1b[RESIZE:103;37]')")
                output = command(page, "stty size")
                assert '37 103' in output, output
                # A foreground command responds to Ctrl-C and leaves shell alive.
                page.evaluate("testShell.ws.send('sleep 60\\n')")
                time.sleep(.3)
                page.evaluate("testShell.ws.send('\\x03')")
                assert 'INTERRUPT-OK' in command(page, "printf 'INTERRUPT-%s\\n' 'OK'")
                service = 'executor' if mode == 'code' else 'hermes'
                pid = smoke.python(service, "from pathlib import Path; print(Path('/tmp/webapp-terminal-pid').read_text())").stdout.strip()
                page.evaluate("testShell.ws.send('sleep 60 & echo $! > /tmp/webapp-terminal-child; wait\\n')")
                child = None
                for attempt in range(50):
                    result = smoke.python(service, "from pathlib import Path; print(Path('/tmp/webapp-terminal-child').read_text())", check=False)
                    if result.returncode == 0:
                        child = int(result.stdout.strip())
                        break
                    time.sleep(.1)
                assert child is not None, 'Foreground child did not start'
                close_shell(page, meta)
                # Explicit close cleans ordinary remote shell; detached jobs are outside this contract.
                for attempt in range(50):
                    result = smoke.python(service, f'import os; os.kill({int(pid)},0); os.kill({child},0)', check=False)
                    if result.returncode:
                        break
                    time.sleep(.1)
                else:
                    raise AssertionError('Closed terminal shell survived')
                for dead_pid in (int(pid), child):
                    result = smoke.python(service, f'from pathlib import Path; p=Path("/proc/{dead_pid}/stat"); assert not p.exists() or p.read_text().split()[2]=="Z"', check=False)
                    assert result.returncode == 0, f'Closed terminal left live process {dead_pid}'
                if mode == 'code':
                    path = "/workspace/terminal space ü ' $(touch SHOULD_NOT_EXIST) ; trailing "
                    smoke.python('executor', 'from pathlib import Path; p=Path(' + repr(path) + '); p.mkdir(exist_ok=True); (p/"file").touch()')
                    session = page.evaluate("""async path => {
                      const api=window.hermesDesktop.terminal;
                      const session=await api.start({cwd:path, cols:80, rows:24});
                      window.testBridgeOutput='';
                      api.onData(session.id, data=>window.testBridgeOutput+=data);
                      return session;
                    }""", path)
                    assert session['cwd'] == path and session['shell'].startswith('Code'), session
                    page.wait_for_function('() => testBridgeOutput.includes("file://executor")')
                    page.evaluate('id => window.hermesDesktop.terminal.dispose(id)', session['id'])
                    for cwd in (path, path + '/file'):
                        open_shell(page, cwd=cwd)
                        meta = metadata(page)
                        assert meta['cwd'] == path, meta
                        # Actual bridge consumes OSC; test the output's exact encoded path here too.
                        out = command(page, "pwd")
                        assert 'file://executor' + quote(path, safe='/') in out, out
                        assert path in out
                        close_shell(page, meta)
                    smoke.python('executor', "from pathlib import Path; assert not Path('/workspace/SHOULD_NOT_EXIST').exists()")
                    unsafe_target = '/workspace/terminal\ncontrol'
                    safe_link = '/workspace/terminal-control-link'
                    smoke.python('executor', f'''from pathlib import Path
target = Path({unsafe_target!r})
target.mkdir(exist_ok=True)
link = Path({safe_link!r})
link.unlink(missing_ok=True)
link.symlink_to(target)
''')
                    for cwd in ('/workspace/does-not-exist', 'relative', '/tmp/new\nline'):
                        denied(page, cwd)
                    denied(page, safe_link, reason='invalid cwd')
                    if origin == LOCAL:
                        try:
                            change_identity('missing')
                            denied(page)
                            change_identity('restore')
                            change_identity('rejected')
                            denied(page)
                            change_identity('restore')
                            change_identity('host')
                            denied(page)
                            check_model_host_key(trusted=False)
                            change_identity('host-missing')
                            denied(page)
                            check_model_host_key(trusted=False)
                        finally:
                            change_identity('finish')
                        check_model_host_key(trusted=True)
                        open_shell(page)
                        close_shell(page, metadata(page))
                    error = page.evaluate("""async () => {
                      try { await window.hermesDesktop.terminal.start({cwd:'/workspace/does-not-exist'}); }
                      catch (error) { return error.message; }
                      return '';
                    }""")
                    assert 'cwd is missing or inaccessible' in error, error
                    # Unavailable executor fails visibly; native agent mode needs no readiness check.
                    smoke.compose('stop', 'executor')
                    try:
                        denied(page)
                    finally:
                        smoke.compose('up', '-d', '--no-deps', '--wait', '--wait-timeout', '600', 'executor')
                    open_shell(page)
                    close_shell(page, metadata(page))
                else:
                    smoke.compose('stop', 'executor')
                    try:
                        open_shell(page)
                        meta = metadata(page)
                        assert 'LOCAL-OK' in command(page, "printf 'LOCAL-%s\\n' 'OK'")
                        close_shell(page, meta)
                        path = '/tmp/local terminal cwd '
                        smoke.python('hermes', f'from pathlib import Path; Path({path!r}).mkdir(exist_ok=True)')
                        open_shell(page, cwd=path)
                        meta = metadata(page)
                        assert meta['cwd'] == path, meta
                        close_shell(page, meta)
                    finally:
                        smoke.compose('up', '-d', '--no-deps', '--wait', '--wait-timeout', '600', 'executor')
                if mode == 'code' and origin == LOCAL:
                    open_shell(page)
                    meta = metadata(page)
                    command(page, "printf '%s' $$ > /tmp/webapp-backend-loss-pid")
                    lost_pid = int(smoke.python('executor', "from pathlib import Path; print(Path('/tmp/webapp-backend-loss-pid').read_text())").stdout.strip())
                    smoke.compose('restart', 'hermes')
                    wait_ready()
                    page.wait_for_function('() => testShell.closed !== null', timeout=30000)
                    for attempt in range(50):
                        result = smoke.python('executor', f'from pathlib import Path; p=Path("/proc/{lost_pid}/stat"); assert not p.exists() or p.read_text().split()[2]=="Z"', check=False)
                        if result.returncode == 0:
                            break
                        time.sleep(.1)
                    else:
                        raise AssertionError('Remote shell survived backend shutdown')
                    open_shell(page)
                    metadata(page)
                    page.evaluate("testShell.ws.send('exit\\n')")
                    page.wait_for_function('() => testShell.closed !== null', timeout=30000)
                    assert page.evaluate('testShell.closed.code') == 4410
                context.close()
                print(f'PASS: {mode} terminal {origin}: placement, identity, cwd, replay, resize, Ctrl-C, close, outage/recovery', flush=True)
        finally:
            browser.close()


if __name__ == '__main__':
    run(sys.argv[1], sys.argv[2])
