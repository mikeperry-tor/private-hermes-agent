"""Ordinary terminal runtime checks through authenticated native WebSockets/bridge."""
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
import time
from urllib.parse import quote

from playwright.sync_api import sync_playwright
import smoke
from webapp_smoke import wait_ready

LOCAL = 'http://127.0.0.1:19120'
PUBLIC = 'https://webapp-test.example.ts.net:10000'


def model_check(code):
    # The production WebApp runs model tooling as Hermes, even though its s6
    # container entrypoint is root. Never create native PM state as root in tests.
    return smoke.execute('hermes', '/opt/hermes/.venv/bin/python', '-c', code, user='10000:10000')


def open_shell(page, cwd=None, attach=None, environment=None):
    return page.evaluate('''async (args) => {
      const response = await fetch('/api/webapp/socket-ticket?socket=host-terminal',{method:'POST'});
      if (!response.ok) throw new Error('ticket '+response.status);
      const url = new URL('/api/host-terminal', location.origin.replace(/^http/,'ws'));
      url.searchParams.set('ticket',(await response.json()).ticket);
      for (const [key,value] of Object.entries(args)) if(value!==null) url.searchParams.set(key,value);
      const state = window.testShell = {output:'', meta:null, closed:null};
      const ws = state.ws = new WebSocket(url); ws.binaryType='arraybuffer';
      ws.onmessage = e => {
        if(typeof e.data==='string' && e.data.startsWith('\\0HERMES_TERMINAL_META:')) {
          state.meta=JSON.parse(e.data.slice('\\0HERMES_TERMINAL_META:'.length));
        } else state.output += typeof e.data==='string' ? e.data : new TextDecoder().decode(e.data);
      };
      ws.onclose=e=>state.closed={code:e.code,reason:e.reason};
    }''', {'cwd': cwd, 'attach': attach, 'environment': environment})


def metadata(page):
    page.wait_for_function('() => testShell.meta !== null || testShell.closed !== null', timeout=30000)
    state = page.evaluate('({meta:testShell.meta, closed:testShell.closed, output:testShell.output})')
    assert state['meta'] is not None, state
    return state['meta']


def command(page, command):
    token = secrets.token_hex(10)
    page.evaluate("args => testShell.ws.send(args.command + \"; printf '\\n__DONE_%s__\\n' '\" + args.token + \"'\\n\")",
                  {'command': command, 'token': token})
    page.wait_for_function('token => testShell.output.includes("__DONE_"+token+"__")', arg=token, timeout=30000)
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


def denied(page, cwd=None):
    open_shell(page, cwd=cwd)
    page.wait_for_function('() => testShell.closed !== null', timeout=30000)
    state = page.evaluate('({meta:testShell.meta, output:testShell.output, closed:testShell.closed})')
    assert state['meta'] is None, state
    assert state['closed']['code'] == 4411 and 'Code terminal' in state['closed']['reason'], state


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
                assert page.evaluate('window.__PRIVATE_HERMES_TERMINAL_ENVIRONMENT__') == mode
                open_shell(page, environment='agent' if mode == 'code' else 'code')
                page.wait_for_function('() => testShell.closed !== null', timeout=30000)
                assert page.evaluate('testShell.meta === null && testShell.closed.reason.includes("environment changed")')
                open_shell(page)
                meta = metadata(page)
                assert meta['environment'] == mode and meta['shell'].startswith(mode.title() + ' · '), meta
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
                command(page, "printf '%s' $$ > /tmp/webapp-terminal-pid")
                page.evaluate('testShell.ws.close()')
                page.wait_for_function('() => testShell.closed !== null')
                open_shell(page, attach=meta['terminalId'])
                resumed = metadata(page)
                assert resumed['reconnected'] and resumed['terminalId'] == meta['terminalId']
                assert 'browser-terminal' in command(page, "printf 'REATTACHED-%s\\n' 'OK'")
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
                    for cwd in ('/workspace/does-not-exist', 'relative', '/tmp/new\nline'):
                        denied(page, cwd)
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
                        finally:
                            change_identity('finish')
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
