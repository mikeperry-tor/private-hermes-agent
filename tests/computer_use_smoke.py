#!/usr/bin/env python3
"""Desktop checks inside the disposable SSH/network smoke project; no inference."""
from pathlib import Path
import json
import os
import subprocess
import smoke


def check():
    fixture = Path(__file__).parent / 'fixtures/computer-use.py'
    try:
        result = smoke.python('hermes', fixture.read_text())
    except subprocess.CalledProcessError as error:
        print(error.stdout, error.stderr, flush=True)
        raise RuntimeError('Disposable desktop fixture failed; see diagnostics above') from None
    print(result.stdout, flush=True)


def switching_checks():
    """Exercise native persistence and dependency loss in the existing test project."""
    smoke.execute('executor', 'python3', '-c', """import errno
from pathlib import Path
for name in ('/etc/cu-root-canary','/run/executor-auth/cu-root-canary'):
 p=Path(name)
 try: p.write_text('fixture')
 except OSError as e: assert e.errno==errno.EROFS,(name,e)
 else:
  p.unlink()
  raise AssertionError('root could write a read-only mount: '+name)
""", user='0:0')
    smoke.python('executor', "from pathlib import Path; p=Path('/home/runner/.hermes/bot-desktop/browser-profile'); p.mkdir(parents=True,exist_ok=True); (p/'fixture-state').write_text('preserved')")
    browser_check = """import glob,subprocess,threading,json
from http.server import BaseHTTPRequestHandler,HTTPServer
chrome=glob.glob('/opt/playwright/chromium-*/chrome-linux*/chrome')[0]
args=[chrome,'--headless','--disable-gpu','--no-first-run','--disable-background-networking',
'--user-data-dir=/home/runner/.hermes/bot-desktop/browser-profile','--dump-dom']
class Cookies(BaseHTTPRequestHandler):
 def do_GET(self):
  seeded=self.path.startswith('/seed')
  present='desktop_fixture=browser-cookie-preserved' in self.headers.get('Cookie','')
  self.send_response(200)
  self.send_header('Content-Type','text/html')
  if seeded: self.send_header('Set-Cookie','desktop_fixture=browser-cookie-preserved; Path=/; Max-Age=3600; HttpOnly; SameSite=Lax')
  self.end_headers()
  cookie='browser-cookie-preserved' if seeded or present else 'missing-cookie'
  seed='localStorage.setItem(\"desktop-fixture\",\"browser-state-preserved\");' if seeded else ''
  script=seed+'document.body.textContent=(localStorage.getItem(\"desktop-fixture\")||\"missing\")+\"|\"+'+json.dumps(cookie)+';'
  self.wfile.write(('<html><body><script>'+script+'</script></body></html>').encode())
 def log_message(self,*args): pass
# A stable HTTP origin measures web storage across separate browser processes.
server=HTTPServer(('127.0.0.1',18071),Cookies)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
 result=subprocess.run([*args,f'http://127.0.0.1:{server.server_port}/'+('seed' if cookie_seed else 'read')],capture_output=True,text=True)
 assert result.returncode==0,result.stderr[-2000:]
 assert '<body>browser-state-preserved|browser-cookie-preserved</body>' in result.stdout,result.stdout[-2000:]
finally: server.shutdown();server.server_close();thread.join()
"""
    smoke.python('executor', 'cookie_seed=True\n' + browser_check)
    proof = """import hashlib,json
from pathlib import Path
print(json.dumps({p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (
'/workspace/computer-use-marker',
'/home/runner/.hermes/bot-desktop/browser-profile/fixture-state')}))
"""
    def snapshot():
        state = json.loads(smoke.python('executor', proof).stdout)
        # The auth directory is deliberately root-only on native Linux binds.
        # Inspect only its public identity through the authorized test exec.
        state['host_public_key'] = smoke.execute('executor', 'sha256sum',
            '/run/executor-auth/ssh_host_ed25519_key.pub', user='0:0').stdout.strip()
        return state

    original = snapshot()
    for enabled in ('false', 'true'):
        environment = dict(os.environ, COMPUTER_USE_ENABLED=enabled)
        smoke.compose('build', 'executor', env=environment)
        smoke.compose('up', '-d', '--wait', '--no-deps', 'executor', 'hermes', env=environment)
        assert snapshot() == original
        result = smoke.python('hermes', """import model_tools
from hermes_bootstrap import PRIVATE_HERMES_COMPUTER_USE
from tools.hosted_tool_policy import tool_refusal
from tools.computer_use.tool import check_computer_use_requirements
from tools.browser_use_cli import browser_exec_available
assert (tool_refusal('computer_use') is None) == PRIVATE_HERMES_COMPUTER_USE
assert (tool_refusal('browser_exec') is None) == PRIVATE_HERMES_COMPUTER_USE
assert check_computer_use_requirements() == PRIVATE_HERMES_COMPUTER_USE
assert browser_exec_available() == PRIVATE_HERMES_COMPUTER_USE
""")
        if enabled == 'false':
            # An enabled gateway with an actually lean executor must not use
            # its own installed driver as corroboration of missing GUI binaries.
            smoke.compose('up', '-d', '--no-deps', '--force-recreate', 'hermes')
            smoke.python('hermes', """from tools.computer_use.tool import check_computer_use_requirements
from tools.browser_use_cli import browser_exec_available, browser_exec
from tools.bot_desktop import runtime
assert not check_computer_use_requirements()
assert not browser_exec_available()
status = runtime.status()
assert not status.installed and 'COMPUTER_USE_ENABLED=true' in status.blocker, status
import json
assert json.loads(browser_exec('raise AssertionError("must not run beside Hermes")')).get('error')
try: runtime.start()
except RuntimeError as e: assert 'needs' in str(e) or 'lacks' in str(e), str(e)
else: raise AssertionError('desktop started with missing executor binaries')
""")
    # Reattach after executor recreation, then prove dependency loss gives a
    # scoped error rather than consulting the gateway's local desktop packages.
    smoke.python('hermes', "from tools.bot_desktop import runtime; assert runtime.start().running")
    smoke.compose('stop', 'executor')
    smoke.python('hermes', """from tools.computer_use.tool import check_computer_use_requirements
from tools.browser_use_cli import browser_exec_available
from tools.bot_desktop import runtime
assert not check_computer_use_requirements()
assert not browser_exec_available()
# A real transport outage must retain usable UI/RPC status, not an installed verdict.
status = runtime.status()
assert not status.installed and not status.running and status.blocker, status
from tui_gateway.methods_display import _display_snapshot
snapshot = _display_snapshot()
assert not snapshot['installed'] and snapshot['blocker'], snapshot
try: runtime.start()
except (OSError, RuntimeError) as e:
    assert any(detail in str(e) for detail in ('SSH', 'sandbox', 'executor', "recorded desktop's terminal settings")), str(e)
else: raise AssertionError('desktop started with executor stopped')
""")
    smoke.compose('up', '-d', '--wait', '--no-deps', 'executor')
    smoke.python('hermes', "from tools.bot_desktop import runtime; assert runtime.start().running")
    assert snapshot() == original
    smoke.python('executor', 'cookie_seed=False\n' + browser_check)
    print('PASS: on/off/on builds preserve executor identity, workspace and actual Chromium localStorage/cookies; missing binaries/SSH refuse desktop and restart recovers', flush=True)


if __name__ == '__main__':
    import sys
    os.environ['COMPUTER_USE_ENABLED'] = 'true'
    if '--desktop-only' not in sys.argv:
        smoke.main()
    else:
        with smoke.storage_fixture():
            failed = True
            try:
                smoke.start_stack()
                check()
                switching_checks()
                failed = False
            except Exception as error:
                if isinstance(error, subprocess.CalledProcessError):
                    print(error.stdout or '', error.stderr or '', flush=True)
                print(smoke.compose('logs', '--tail', '10', 'executor', check=False).stdout)
                raise
            finally:
                if not failed or os.getenv('KEEP_FAILED_TEST_STACK') != '1':
                    smoke.compose('down', '--volumes', '--remove-orphans', check=False)
